"""stats.json transform + orchestrator tests — fully offline.

Reuses the slice-A1 ``FakeFetcher`` pattern (a URL -> fixture-HTML map) so the
scraper and the stats orchestrator run end-to-end without any network access.
Asserts the stats.json schema, event grouping (incl. a real multi-round
event), newest-first ordering, and summary math; plus pure unit tests for the
ported ``count_scores`` tally.
"""

import json

import pytest

from pipeline.build_stats import build, build_stats_for
from pipeline.pdga import PdgaParseError, PdgaScraper
from pipeline.stats import build_stats_record, count_scores
from tests.conftest import FIXTURES_DIR


class FakeFetcher:
    """Maps a pdga.com URL to fixture HTML; records every URL requested.

    Mirrors tests/test_build_players.py's FakeFetcher: a URL ending in
    ``/details`` is the detail page, otherwise the profile page.
    """

    def __init__(self, mapping):
        self._mapping = mapping
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        if url not in self._mapping:
            raise AssertionError(f"unexpected URL requested offline: {url}")
        return (FIXTURES_DIR / self._mapping[url]).read_text()


def _scraper_for(*pdga_nos, extra=None):
    """Build a PdgaScraper wired to fixtures for the given PDGA numbers."""
    mapping = {}
    for n in pdga_nos:
        mapping[f"https://www.pdga.com/player/{n}"] = f"profile_{n}.html"
        mapping[f"https://www.pdga.com/player/{n}/details"] = f"detail_{n}.html"
    if extra:
        mapping.update(extra)
    fetcher = FakeFetcher(mapping)
    return PdgaScraper(fetch_html=fetcher), fetcher


def _write_roster(tmp_path, pdga_numbers):
    roster = tmp_path / "roster.json"
    roster.write_text(json.dumps({"pdga_numbers": pdga_numbers}))
    return roster


# --- single-player stats record ----------------------------------------------
class TestBuildStatsRecord:
    def test_pat_greenville_schema_and_summary(self):
        """100100: 9 single-round events @ 940/960, newest = Greenville Open 960."""
        scraper, _ = _scraper_for(100100)
        player = scraper.fetch_player(100100)
        rec = build_stats_record(player)

        assert set(rec.keys()) == {"pdga_no", "name", "summary", "events"}
        assert rec["pdga_no"] == 100100
        assert rec["name"] == "Pat Greenville"

        summary = rec["summary"]
        assert set(summary.keys()) == {
            "events_count",
            "rated_rounds",
            "latest_rating",
            "peak_rating",
            "first_event_date",
            "last_event_date",
        }
        assert summary["events_count"] == 9
        assert summary["rated_rounds"] == 9  # one round per event in this fixture
        assert summary["peak_rating"] == 960
        assert summary["latest_rating"] == 960  # Greenville Open round 1 @ 960
        assert summary["last_event_date"] == "2026-03-01"
        assert summary["first_event_date"] == "2025-11-09"

    def test_events_newest_first_and_shape(self):
        scraper, _ = _scraper_for(100100)
        rec = build_stats_record(scraper.fetch_player(100100))
        events = rec["events"]
        assert len(events) == 9

        # newest-first ordering (descending dates)
        dates = [e["date"] for e in events]
        assert dates == sorted(dates, reverse=True)
        assert events[0]["date"] == "2026-03-01"
        assert events[0]["tournament"] == "Greenville Open"

        # each event carries the documented keys/types
        for e in events:
            assert set(e.keys()) == {
                "tournament",
                "date",
                "division",
                "tier",
                "rounds",
                "high_round",
                "avg_round",
            }
            assert isinstance(e["tournament"], str)
            assert len(e["date"]) == 10 and e["date"][4] == "-"  # ISO YYYY-MM-DD
            assert isinstance(e["high_round"], int)
            assert isinstance(e["avg_round"], int)
            assert e["rounds"], "every event has at least one round"
            for rd in e["rounds"]:
                assert set(rd.keys()) == {"round", "rating"}
                assert isinstance(rd["round"], int)
                assert isinstance(rd["rating"], int)

        # single-round event => high == avg == the round's rating
        top = events[0]
        assert top["rounds"] == [{"round": 1, "rating": 960}]
        assert top["high_round"] == 960 and top["avg_round"] == 960
        assert top["division"] == "MA1"
        assert top["tier"] == "A"

    def test_multi_round_event_grouping_and_avg(self):
        """298827: 'The Southern Maryland Classic' has rounds 773 & 747 on one date."""
        scraper, _ = _scraper_for(298827)
        rec = build_stats_record(scraper.fetch_player(298827))

        by_name = {e["tournament"]: e for e in rec["events"]}
        smc = by_name["The Southern Maryland Classic"]
        # two rounds grouped under one event, ordered by round number
        assert smc["date"] == "2025-04-06"
        assert smc["rounds"] == [
            {"round": 1, "rating": 773},
            {"round": 2, "rating": 747},
        ]
        assert smc["high_round"] == 773
        assert smc["avg_round"] == 760  # round((773 + 747) / 2) == 760
        assert smc["division"] == "MA4"

        # 4 rated rounds across 3 events (incl. the Unrated event, which is
        # still rated DATA we keep — matches build_players' behavior).
        assert rec["summary"]["events_count"] == 3
        assert rec["summary"]["rated_rounds"] == 4
        # newest event is Presidents Day Singles (2026-02-16) -> latest 783
        assert rec["events"][0]["date"] == "2026-02-16"
        assert rec["summary"]["latest_rating"] == 783
        assert rec["summary"]["last_event_date"] == "2026-02-16"
        assert rec["summary"]["first_event_date"] == "2025-04-06"

    def test_no_rounds_yields_empty_events(self):
        scraper, _ = _scraper_for(999999)
        rec = build_stats_record(scraper.fetch_player(999999))
        assert rec["events"] == []
        assert rec["summary"]["events_count"] == 0
        assert rec["summary"]["rated_rounds"] == 0
        assert rec["summary"]["peak_rating"] is None
        assert rec["summary"]["latest_rating"] is None
        assert rec["summary"]["first_event_date"] is None
        assert rec["summary"]["last_event_date"] is None


# --- orchestrator: build_stats_for + build -----------------------------------
class TestBuildStatsFor:
    def test_no_rounds_skipped(self):
        scraper, _ = _scraper_for(999999)
        assert build_stats_for(999999, scraper) is None

    def test_only_two_urls_fetched_per_player(self):
        scraper, fetcher = _scraper_for(100100)
        build_stats_for(100100, scraper)
        assert fetcher.requested == [
            "https://www.pdga.com/player/100100",
            "https://www.pdga.com/player/100100/details",
        ]

    def test_drift_swallowed_returns_none(self):
        extra = {
            "https://www.pdga.com/player/424242": "profile_100100.html",
            "https://www.pdga.com/player/424242/details": "detail_drift.html",
        }
        scraper, _ = _scraper_for(extra=extra)
        # a drifted player must be logged + skipped, never abort the run
        assert build_stats_for(424242, scraper) is None
        # the scraper itself still surfaces drift loudly
        with pytest.raises(PdgaParseError):
            scraper.fetch_player(424242)


class TestBuild:
    def test_emits_schema_and_writes_file(self, tmp_path):
        roster = _write_roster(tmp_path, [100100, 298827, 999999])
        out = tmp_path / "stats.json"
        scraper, _ = _scraper_for(100100, 298827, 999999)

        result = build(roster_path=str(roster), output_path=str(out), scraper=scraper)

        # top-level schema
        assert set(result.keys()) == {"lastUpdated", "players"}
        assert isinstance(result["lastUpdated"], str) and "T" in result["lastUpdated"]

        players = result["players"]
        # 999999 has no rounds -> skipped; keys are string PDGA numbers
        assert set(players.keys()) == {"100100", "298827"}

        pat = players["100100"]
        assert set(pat.keys()) == {"pdga_no", "name", "summary", "events"}
        assert pat["summary"]["events_count"] == 9

        # file written and round-trips to the same structure
        on_disk = json.loads(out.read_text())
        assert on_disk == result

    def test_build_handles_drift_player_without_aborting(self, tmp_path):
        roster = _write_roster(tmp_path, [424242, 100100])
        out = tmp_path / "stats.json"
        extra = {
            "https://www.pdga.com/player/424242": "profile_100100.html",
            "https://www.pdga.com/player/424242/details": "detail_drift.html",
        }
        scraper, _ = _scraper_for(100100, extra=extra)

        result = build(roster_path=str(roster), output_path=str(out), scraper=scraper)
        # drift player skipped, good player still emitted
        assert set(result["players"].keys()) == {"100100"}

    def test_accepts_bare_list_roster(self, tmp_path):
        roster = tmp_path / "roster.json"
        roster.write_text(json.dumps([100100]))
        out = tmp_path / "stats.json"
        scraper, _ = _scraper_for(100100)
        result = build(roster_path=str(roster), output_path=str(out), scraper=scraper)
        assert "100100" in result["players"]


# --- ported count_scores tally (pure) ----------------------------------------
class TestCountScores:
    def test_ace_counts_as_ace_and_eagle(self):
        # par-3 hole aced: ace, and (1 <= 3-2) so also eagle+ — matches upstream.
        result = count_scores([3], [1])
        assert result["aces"] == 1
        assert result["eagles+"] == 1
        assert result["birdies"] == 0
        assert result["pars"] == 0
        assert result["bogeys"] == 0
        assert result["doubles+"] == 0

    def test_eagle_on_par_5(self):
        # 3 on a par-5 is two under: eagle+, not an ace.
        result = count_scores([5], [3])
        assert result == {
            "aces": 0,
            "eagles+": 1,
            "birdies": 0,
            "pars": 0,
            "bogeys": 0,
            "doubles+": 0,
        }

    def test_birdie(self):
        assert count_scores([4], [3])["birdies"] == 1

    def test_par(self):
        assert count_scores([3], [3])["pars"] == 1

    def test_bogey(self):
        assert count_scores([3], [4])["bogeys"] == 1

    def test_double_plus(self):
        # +2 and +3 both fall into doubles+.
        result = count_scores([3, 4], [5, 7])
        assert result["doubles+"] == 2
        assert result["bogeys"] == 0

    def test_full_round_distribution(self):
        pars = [3, 3, 4, 5, 3, 4, 3, 4, 5]
        scores = [1, 2, 4, 3, 4, 4, 3, 6, 8]
        #          ace bir par eag bog par par dbl dbl
        result = count_scores(pars, scores)
        assert result == {
            "aces": 1,
            "eagles+": 2,  # the par-5 three, plus the ace (1 <= 3-2)
            "birdies": 1,
            "pars": 3,
            "bogeys": 1,
            "doubles+": 2,
        }

    def test_empty_round_is_all_zero(self):
        assert count_scores([], []) == {
            "aces": 0,
            "eagles+": 0,
            "birdies": 0,
            "pars": 0,
            "bogeys": 0,
            "doubles+": 0,
        }
