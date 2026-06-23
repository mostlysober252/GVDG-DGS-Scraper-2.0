"""Orchestrator tests — fully offline via a fake fetcher.

A ``FakeFetcher`` maps pdga.com URLs to saved fixture HTML, so the scraper
and orchestrator are exercised end-to-end without any network access. Tests
assert the emitted players.json schema + values and the resilience paths
(no-rounds players skipped, schema-drift raises a typed error).
"""

import json

import pytest

from pipeline.build_players import build, build_player_record
from pipeline.pdga import PdgaParseError, PdgaScraper
from tests.conftest import FIXTURES_DIR


class FakeFetcher:
    """Maps a pdga.com URL to fixture HTML; records every URL requested.

    URL -> fixture-file mapping mirrors pipeline.pdga's PROFILE_URL / DETAIL_URL
    shapes: a URL ending in ``/details`` is the detail page, otherwise profile.
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


# --- single-player record ----------------------------------------------------
class TestBuildPlayerRecord:
    def test_pat_greenville_known_values(self):
        """Deterministic fixture: 7 rounds @940 + 2 most-recent @960.

        9 evaluated rounds -> last 25% (round(9*0.25)=2) double-weighted.
        weighted avg = (940*7 + 960*2*2) / (7 + 4) = 10420/11 = 947.27
        -> ceil = 948. No outliers (ratings tightly clustered).
        """
        scraper, _ = _scraper_for(100100)
        record = build_player_record(100100, scraper)
        assert record["pdga_no"] == 100100
        assert record["name"] == "Pat Greenville"
        assert record["official_rating"] == 949
        assert record["live_rating"] == 948

    def test_rating_history_shape_and_order(self):
        scraper, _ = _scraper_for(100100)
        record = build_player_record(100100, scraper)
        history = record["rating_history"]
        assert len(history) == 9  # one entry per event
        # oldest-first ordering
        dates = [h["date"] for h in history]
        assert dates == sorted(dates)
        # each entry has the documented keys/types
        for h in history:
            assert set(h.keys()) == {"date", "rating", "event"}
            assert isinstance(h["rating"], int)
            assert isinstance(h["event"], str)
            # ISO YYYY-MM-DD
            assert len(h["date"]) == 10 and h["date"][4] == "-"
        # most recent event is the highest-dated one
        assert history[-1]["date"] == "2026-03-01"
        assert history[-1]["event"] == "Greenville Open"

    def test_tyler_adkins_matches_official(self):
        """Real fixture: Tyler Adkins, official 768, incl. an Unrated event."""
        scraper, _ = _scraper_for(298827)
        record = build_player_record(298827, scraper)
        assert record["name"] == "Tyler Adkins"
        assert record["official_rating"] == 768
        assert abs(record["live_rating"] - 768) <= 2
        # Unrated tournament still appears in history (it is rated data we keep)
        events = {h["event"] for h in record["rating_history"]}
        assert "SOMD ICE BOWL (Unrated)" in events

    def test_no_rounds_returns_none(self):
        scraper, _ = _scraper_for(999999)
        assert build_player_record(999999, scraper) is None

    def test_only_two_urls_fetched_per_player(self):
        scraper, fetcher = _scraper_for(100100)
        build_player_record(100100, scraper)
        assert fetcher.requested == [
            "https://www.pdga.com/player/100100",
            "https://www.pdga.com/player/100100/details",
        ]


# --- schema drift ------------------------------------------------------------
class TestSchemaDrift:
    def test_scraper_raises_on_missing_columns(self):
        extra = {
            "https://www.pdga.com/player/424242": "profile_100100.html",
            "https://www.pdga.com/player/424242/details": "detail_drift.html",
        }
        scraper, _ = _scraper_for(extra=extra)
        with pytest.raises(PdgaParseError):
            scraper.fetch_player(424242)

    def test_build_record_swallows_drift_and_returns_none(self):
        extra = {
            "https://www.pdga.com/player/424242": "profile_100100.html",
            "https://www.pdga.com/player/424242/details": "detail_drift.html",
        }
        scraper, _ = _scraper_for(extra=extra)
        # A drifted player must not abort the run — it is logged and skipped.
        assert build_player_record(424242, scraper) is None


# --- full build orchestration -----------------------------------------------
class TestBuild:
    def test_emits_schema_and_writes_file(self, tmp_path):
        roster = _write_roster(tmp_path, [100100, 298827, 999999])
        out = tmp_path / "players.json"
        scraper, _ = _scraper_for(100100, 298827, 999999)

        result = build(
            roster_path=str(roster), output_path=str(out), scraper=scraper
        )

        # top-level schema
        assert set(result.keys()) == {"lastUpdated", "players"}
        assert isinstance(result["lastUpdated"], str) and "T" in result["lastUpdated"]

        players = result["players"]
        # 999999 has no rounds -> skipped; keys are string PDGA numbers
        assert set(players.keys()) == {"100100", "298827"}

        pat = players["100100"]
        assert set(pat.keys()) == {
            "pdga_no",
            "name",
            "official_rating",
            "live_rating",
            "photo",
            "rating_history",
        }
        assert pat["live_rating"] == 948

        # file written and round-trips to the same structure
        on_disk = json.loads(out.read_text())
        assert on_disk == result

    def test_build_handles_drift_player_without_aborting(self, tmp_path):
        roster = _write_roster(tmp_path, [424242, 100100])
        out = tmp_path / "players.json"
        extra = {
            "https://www.pdga.com/player/424242": "profile_100100.html",
            "https://www.pdga.com/player/424242/details": "detail_drift.html",
        }
        scraper, _ = _scraper_for(100100, extra=extra)

        result = build(
            roster_path=str(roster), output_path=str(out), scraper=scraper
        )
        # drift player skipped, good player still emitted
        assert set(result["players"].keys()) == {"100100"}

    def test_accepts_bare_list_roster(self, tmp_path):
        roster = tmp_path / "roster.json"
        roster.write_text(json.dumps([100100]))
        out = tmp_path / "players.json"
        scraper, _ = _scraper_for(100100)
        result = build(
            roster_path=str(roster), output_path=str(out), scraper=scraper
        )
        assert "100100" in result["players"]
