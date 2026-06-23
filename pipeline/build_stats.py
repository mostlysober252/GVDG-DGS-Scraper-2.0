"""Orchestrator: roster.json -> scrape + transform -> stats.json.

Reads the club roster (a JSON list of PDGA numbers), fetches each player via
the injectable :class:`pipeline.pdga.PdgaScraper` (the SAME scraper slice A1
uses — no new pdga.com scraping logic), turns each player's rated rounds into
a per-member tournament history + career summary via
:func:`pipeline.stats.build_stats_record`, and writes ``stats.json`` in the
schema documented in PIPELINE.md.

This deliberately mirrors :mod:`pipeline.build_players`: it reuses
``load_roster``, skips-and-logs any player that fails (parse error, outage, or
no rated rounds) so a single bad player never aborts the run, and exposes the
same ``--roster`` / ``--out`` CLI. One scrape run can refresh both
``players.json`` and ``stats.json``.

Run as a module:

    python -m pipeline.build_stats                      # live scrape
    python -m pipeline.build_stats --roster roster.json --out stats.json

In tests, call :func:`build` directly with a ``PdgaScraper`` constructed from
a fake fetcher so nothing touches the network.
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pipeline.build_players import load_roster
from pipeline.pdga import PdgaParseError, PdgaScraper
from pipeline.stats import build_stats_record

logger = logging.getLogger(__name__)

DEFAULT_ROSTER = "roster.json"
DEFAULT_OUTPUT = "stats.json"


def build_stats_for(pdga_no: int, scraper: PdgaScraper) -> dict | None:
    """Scrape + transform one player into a stats record, or ``None``.

    Returns ``None`` (and logs) when the player cannot be built — no rated
    rounds, schema-drift, or a network error — so a single bad player never
    aborts the whole run, exactly like ``build_players.build_player_record``.
    """
    try:
        player = scraper.fetch_player(pdga_no)
    except PdgaParseError:
        logger.exception("Schema drift / parse error for PDGA #%s", pdga_no)
        return None
    except Exception:
        logger.exception("Failed to fetch PDGA #%s", pdga_no)
        return None

    if player.ratings_detail_df is None or player.ratings_detail_df.empty:
        logger.warning("PDGA #%s has no rated rounds; skipping", pdga_no)
        return None

    return build_stats_record(player)


def build(
    roster_path: str = DEFAULT_ROSTER,
    output_path: str = DEFAULT_OUTPUT,
    scraper: PdgaScraper | None = None,
) -> dict:
    """Build ``stats.json`` for every player in the roster.

    Args:
        roster_path: Path to the roster JSON file.
        output_path: Where to write stats.json (``None`` to skip writing).
        scraper: A :class:`PdgaScraper`. Defaults to a live scraper; tests
            pass one wrapping a fake fetcher.

    Returns:
        The output dict (also written to ``output_path`` when provided).
    """
    if scraper is None:
        scraper = PdgaScraper()

    roster = load_roster(roster_path)
    players: dict[str, dict] = {}
    for pdga_no in roster:
        record = build_stats_for(pdga_no, scraper)
        if record is not None:
            players[str(pdga_no)] = record

    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "players": players,
    }

    if output_path is not None:
        Path(output_path).write_text(json.dumps(output, indent=2) + "\n")
        logger.info("Wrote stats for %s player(s) to %s", len(players), output_path)
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build stats.json for GVDG.")
    parser.add_argument("--roster", default=DEFAULT_ROSTER, help="roster JSON path")
    parser.add_argument("--out", default=DEFAULT_OUTPUT, help="output JSON path")
    parser.add_argument(
        "--log-level", default="INFO", help="logging level (e.g. INFO, DEBUG)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper())
    build(roster_path=args.roster, output_path=args.out)


if __name__ == "__main__":
    main()
