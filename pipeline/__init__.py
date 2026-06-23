"""GVDG players-ratings pipeline.

Scrapes pdga.com player profiles, computes a live (unofficial) PDGA rating
from each player's round history, and emits ``players.json`` for the GVDG
member portal.

Public surface:
    - ``pipeline.rating.calculate_rating`` — the pure rating algorithm.
    - ``pipeline.pdga.PdgaScraper`` / ``pipeline.pdga.Player`` — scraping.
    - ``pipeline.build_players.build`` — orchestrator that emits players.json.

The rating algorithm is a faithful port of cclark20/pdga-whats-my-rating
(MIT). See NOTICE and pipeline/rating.py for attribution.
"""

__all__ = ["rating", "pdga", "build_players"]
