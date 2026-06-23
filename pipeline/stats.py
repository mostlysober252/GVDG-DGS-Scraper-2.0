"""Pure transforms for per-member tournament-history ``stats.json`` — NO I/O.

Slice A2 is a *transform* over the rated rounds that slice A1's
:class:`pipeline.pdga.PdgaScraper` already scrapes — it does NOT add any new
pdga.com scraping. :func:`build_stats_record` takes a scraped
:class:`pipeline.pdga.Player` and groups its rated rounds by event
``(tournament, date)`` into a newest-first tournament history plus a career
``summary``. The orchestrator that turns a roster into ``stats.json`` lives in
:mod:`pipeline.build_stats`.

This module also ports :func:`count_scores`, a pure score-distribution tally
(aces / eagles+ / birdies / pars / bogeys / doubles+) from hole-by-hole data.

    NOTE: hole-by-hole scoring data is NOT available from pdga.com — the
    ratings-detail page only exposes a per-round *rating*, not the individual
    hole scores. :func:`count_scores` is therefore NOT populated in
    ``stats.json`` v1; it is provided for future udisclive-tracked events
    (https://udisclive.com), which DO expose hole-by-hole scores. It is kept
    here, pure and tested, so that future slice can wire it in directly.

Credit for :func:`count_scores`: cclark20/disc-golf-data
(https://github.com/cclark20/disc-golf-data, MIT license), ``src/udisc_live.py``.
"""

import math

import pandas as pd

from pipeline.pdga import Player


def count_scores(pars: list[int], scores: list[int]) -> dict[str, int]:
    """Tally a round's score distribution from hole-by-hole data.

    A faithful port of ``count_scores`` from cclark20/disc-golf-data's
    ``src/udisc_live.py`` (MIT). ``pars`` and ``scores`` are parallel
    per-hole lists (``scores[i]`` is the strokes taken on the hole whose par
    is ``pars[i]``). Categories are non-exclusive only where the source makes
    them so: an ace (score of 1) is also counted toward ``eagles+`` when it is
    two-or-more under par, exactly as upstream.

    Returns a dict with integer counts for keys ``aces``, ``eagles+``,
    ``birdies``, ``pars``, ``bogeys`` and ``doubles+``.

    NOT used by ``stats.json`` v1 — pdga.com exposes no hole-by-hole data.
    See the module docstring.
    """
    results = {
        "aces": 0,
        "eagles+": 0,
        "birdies": 0,
        "pars": 0,
        "bogeys": 0,
        "doubles+": 0,
    }
    for i in range(len(scores)):
        if scores[i] == 1:
            results["aces"] += 1
        if scores[i] <= pars[i] - 2:
            results["eagles+"] += 1
        if scores[i] == pars[i] - 1:
            results["birdies"] += 1
        if scores[i] == pars[i]:
            results["pars"] += 1
        if scores[i] == pars[i] + 1:
            results["bogeys"] += 1
        if scores[i] >= pars[i] + 2:
            results["doubles+"] += 1
    return results


def _iso_date(value) -> str:
    """Render a ratings-detail date cell as an ISO ``YYYY-MM-DD`` string."""
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def _build_events(df: pd.DataFrame) -> list[dict]:
    """Group a ratings-detail frame into a newest-first list of events.

    One event per ``(tournament, date)``. Each event carries its rounds
    (``round`` number + ``rating``, ordered by round number), the event's
    ``division`` and ``tier`` (from the first round of that event), the
    ``high_round`` (max round rating) and the ``avg_round`` (mean round
    rating, rounded to the nearest int).
    """
    if df is None or df.empty:
        return []

    events: list[dict] = []
    # groupby with sort=False preserves first-seen order within a key; we sort
    # the resulting events explicitly (newest event first) below.
    for (tournament, date), group in df.groupby(
        ["tournament", "date"], sort=False
    ):
        group = group.copy()
        # round numbers come off the page as strings (see pdga._parse_ratings_detail);
        # sort numerically when possible, falling back to string order.
        try:
            group["_round_sort"] = group["round"].astype(int)
        except (ValueError, TypeError):
            group["_round_sort"] = group["round"]
        group = group.sort_values("_round_sort")

        rounds = [
            {"round": _coerce_round(r), "rating": int(rating)}
            for r, rating in zip(group["round"], group["rating"])
        ]
        ratings = [rd["rating"] for rd in rounds]
        first = group.iloc[0]

        events.append(
            {
                "tournament": str(tournament),
                "date": _iso_date(date),
                "division": _opt_str(first["division"]),
                "tier": _opt_str(first["tier"]),
                "rounds": rounds,
                "high_round": max(ratings),
                "avg_round": int(round(sum(ratings) / len(ratings))),
            }
        )

    # newest event first; ties broken by tournament name for determinism.
    events.sort(key=lambda e: (e["date"], e["tournament"]), reverse=True)
    return events


def _coerce_round(value) -> int | str:
    """Return the round number as an int when it parses, else the raw string."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return str(value)


def _opt_str(value) -> str | None:
    """Stringify a cell, mapping pandas/NaN-ish blanks to ``None``."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    return text


def _build_summary(events: list[dict]) -> dict:
    """Compute the career summary block from the (newest-first) events list.

    Fields:
      * ``events_count``   — number of distinct events.
      * ``rated_rounds``   — total rated rounds across all events.
      * ``latest_rating``  — round rating of the newest event's last round
        (the most recent rated round chronologically), or ``None``.
      * ``peak_rating``    — highest single round rating ever, or ``None``.
      * ``first_event_date`` / ``last_event_date`` — ISO date bounds, or ``None``.
    """
    rated_rounds = sum(len(e["rounds"]) for e in events)

    all_ratings: list[int] = [r["rating"] for e in events for r in e["rounds"]]
    peak_rating = max(all_ratings) if all_ratings else None

    # events is newest-first; its last round is the most recent rated round.
    latest_rating = events[0]["rounds"][-1]["rating"] if events else None

    last_event_date = events[0]["date"] if events else None
    first_event_date = events[-1]["date"] if events else None

    return {
        "events_count": len(events),
        "rated_rounds": rated_rounds,
        "latest_rating": latest_rating,
        "peak_rating": peak_rating,
        "first_event_date": first_event_date,
        "last_event_date": last_event_date,
    }


def build_stats_record(player: Player) -> dict:
    """Build one player's ``stats.json`` record from a scraped ``Player``.

    Groups ``player``'s rated rounds into a newest-first ``events`` list and a
    career ``summary`` (see the module / schema docs). Returns the per-player
    dict; callers (the orchestrator) decide how to key/skip it. A player with
    no rated rounds yields an empty ``events`` list and an all-``None`` /
    zeroed summary — the orchestrator skips such players, mirroring
    ``build_players``.
    """
    events = _build_events(player.ratings_detail_df)
    return {
        "pdga_no": int(player.pdga_no),
        "name": player.name,
        "summary": _build_summary(events),
        "events": events,
    }
