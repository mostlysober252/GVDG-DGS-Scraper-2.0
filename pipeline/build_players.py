"""Orchestrator: roster.json -> scrape + compute -> players.json.

Reads a club roster (a JSON list of PDGA numbers) from ``roster.json``,
fetches and computes the live rating for each player via the injectable
scraper, and writes ``players.json`` in the schema documented in PIPELINE.md.

Run as a module:

    python -m pipeline.build_players                      # live scrape
    python -m pipeline.build_players --roster roster.json --out players.json

In tests, call :func:`build` directly with a ``PdgaScraper`` constructed
from a fake fetcher so nothing touches the network.
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline.pdga import PdgaParseError, PdgaScraper
from pipeline.rating import calculate_rating

logger = logging.getLogger(__name__)

DEFAULT_ROSTER = "roster.json"
DEFAULT_OUTPUT = "players.json"


def load_roster(path: str) -> list[int]:
    """Load a roster file.

    Accepts either a bare JSON list of PDGA numbers, e.g. ``[12345, 67890]``,
    or an object with a ``"pdga_numbers"`` key, e.g.
    ``{"pdga_numbers": [12345, 67890]}``.
    """
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = data.get("pdga_numbers", [])
    return [int(n) for n in data]


def _build_rating_history(df: pd.DataFrame) -> list[dict]:
    """Build a per-event rating-history list from a ratings-detail frame.

    One entry per (tournament, date), using the best (max) round rating for
    that event, ordered oldest-first. Dates are ISO ``YYYY-MM-DD`` strings.
    """
    if df is None or df.empty:
        return []
    grouped = (
        df.groupby(["tournament", "date"], as_index=False)["rating"]
        .max()
        .sort_values("date", ascending=True)
    )
    history = []
    for _, row in grouped.iterrows():
        history.append(
            {
                "date": pd.to_datetime(row["date"]).strftime("%Y-%m-%d"),
                "rating": int(row["rating"]),
                "event": str(row["tournament"]),
            }
        )
    return history


def build_player_record(pdga_no: int, scraper: PdgaScraper) -> dict | None:
    """Scrape + compute one player. Returns a players.json record, or None.

    Returns ``None`` (and logs) when the player cannot be built — e.g. no
    rated rounds, or a schema-drift / network error — so a single bad player
    never aborts the whole run.
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

    _, live_rating, _, _ = calculate_rating(player.ratings_detail_df)

    return {
        "pdga_no": int(pdga_no),
        "name": player.name,
        "official_rating": player.official_rating,
        "live_rating": live_rating,
        "rating_history": _build_rating_history(player.ratings_detail_df),
    }


def build(
    roster_path: str = DEFAULT_ROSTER,
    output_path: str = DEFAULT_OUTPUT,
    scraper: PdgaScraper | None = None,
) -> dict:
    """Build ``players.json`` for every player in the roster.

    Args:
        roster_path: Path to the roster JSON file.
        output_path: Where to write players.json (``None`` to skip writing).
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
        record = build_player_record(pdga_no, scraper)
        if record is not None:
            players[str(pdga_no)] = record

    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "players": players,
    }

    if output_path is not None:
        Path(output_path).write_text(json.dumps(output, indent=2) + "\n")
        logger.info(
            "Wrote %s player(s) to %s", len(players), output_path
        )
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build players.json for GVDG.")
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
