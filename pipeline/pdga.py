"""pdga.com scraping for the GVDG players-ratings pipeline.

This module isolates ALL network access behind an injectable ``fetch_html``
callable, so the orchestrator and tests can run fully offline against saved
fixture HTML. No Selenium is used — only ``requests`` + ``pandas.read_html`` /
``BeautifulSoup``, mirroring the style of cclark20/pdga-whats-my-rating's
``classes/player.py`` and discgolfdata's ``players.py``.

Two pdga.com pages are scraped per player:
  * Profile  : https://www.pdga.com/player/<n>          (name, official rating)
  * Detail   : https://www.pdga.com/player/<n>/details  (per-round ratings table)

Resilience to HTML drift:
  * All selectors / expected column names are centralized as module
    constants below.
  * When an expected table or element is missing, a typed ``PdgaParseError``
    is raised with a clear message naming what was expected, so a schema
    drift fails loudly instead of silently producing wrong data.
"""

import re
from collections.abc import Callable
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

# --- centralized pdga.com URLs -------------------------------------------------
PROFILE_URL = "https://www.pdga.com/player/{pdga_no}"
DETAIL_URL = "https://www.pdga.com/player/{pdga_no}/details"

# --- centralized selectors / expected column names ----------------------------
# Profile page (BeautifulSoup selectors)
SEL_CURRENT_RATING = ("li", {"class": "current-rating"})
SEL_RATING_DATE = ("small", {"class": "rating-date"})
SEL_LOCATION = ("li", {"class": "location"})
SEL_MEMBERSHIP_LABEL_RE = re.compile(r"Membership Status")

# Ratings-detail table: columns we read out of the pdga.com details table.
DETAIL_COLUMNS = [
    "Tournament",
    "Date",
    "Tier",
    "Division",
    "Round",
    "Rating",
    "Evaluated",
    "Included",
]
DETAIL_RENAME = {
    "Tournament": "tournament",
    "Date": "date",
    "Tier": "tier",
    "Division": "division",
    "Round": "round",
    "Rating": "rating",
    "Evaluated": "evaluated",
    "Included": "used",
}

REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class PdgaParseError(Exception):
    """Raised when an expected pdga.com element/table/column is missing.

    A ``PdgaParseError`` almost always means pdga.com changed its HTML
    structure (schema drift). Centralizing it here makes such failures
    obvious and actionable rather than silent.
    """


def requests_fetch_html(url: str) -> str:
    """Default live fetcher: GET ``url`` and return decoded HTML text.

    Tests inject a fake fetcher instead of this, so it is never exercised
    offline. Network errors propagate as ``requests`` exceptions.
    """
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.text


def clean_player_name(title_segment: str) -> str:
    """Strip the trailing ``#<pdga-number>`` that pdga.com appends to the page title.

    e.g. ``"Casey Clark #167210"`` -> ``"Casey Clark"``. A plain name is returned as-is.
    """
    return re.sub(r"\s*#\d+\s*$", "", title_segment).strip()


class Player:
    """A scraped pdga.com player: name, official rating, and round history.

    Construct via :meth:`PdgaScraper.fetch_player`. ``ratings_detail_df`` is
    ``None`` when the player has no rated rounds.
    """

    def __init__(self, pdga_no: int):
        self.pdga_no = int(pdga_no)
        self.name: str | None = None
        self.location: str | None = None
        self.official_rating: int | None = None
        self.rating_date: str | None = None
        self.membership_status: str | None = None
        self.ratings_detail_df: pd.DataFrame | None = None


class PdgaScraper:
    """Scrapes pdga.com player pages through an injectable HTML fetcher.

    Args:
        fetch_html: Callable taking a URL and returning HTML text. Inject a
            fake here in tests to run offline; defaults to
            :func:`requests_fetch_html` for live use.
    """

    def __init__(self, fetch_html: Callable[[str], str] = requests_fetch_html):
        self._fetch_html = fetch_html

    # -- public API -----------------------------------------------------------
    def fetch_player(self, pdga_no: int) -> Player:
        """Fetch + parse a player's profile and ratings-detail pages."""
        player = Player(pdga_no)
        profile_html = self._fetch_html(PROFILE_URL.format(pdga_no=player.pdga_no))
        self._parse_profile(player, profile_html)

        detail_html = self._fetch_html(DETAIL_URL.format(pdga_no=player.pdga_no))
        player.ratings_detail_df = self._parse_ratings_detail(detail_html)
        return player

    # -- parsing (pure given HTML) -------------------------------------------
    def _parse_profile(self, player: Player, html: str) -> None:
        soup = BeautifulSoup(html, "html.parser")

        if soup.title is None or not soup.title.string:
            raise PdgaParseError(
                f"No <title> on profile page for PDGA #{player.pdga_no}; "
                "pdga.com profile layout may have changed."
            )
        player.name = clean_player_name(soup.title.string.split(" | ")[0])

        location = soup.find(*SEL_LOCATION)
        if location and ": " in location.text:
            player.location = location.text.split(": ")[1].strip()

        cur_rating = soup.find(*SEL_CURRENT_RATING)
        if cur_rating:
            match = re.search(r"\d+", cur_rating.get_text())
            player.official_rating = int(match.group()) if match else None

        rating_date = soup.find(*SEL_RATING_DATE)
        player.rating_date = rating_date.text.strip() if rating_date else None

        membership_label = soup.find("strong", string=SEL_MEMBERSHIP_LABEL_RE)
        if membership_label:
            parts = []
            for sibling in membership_label.next_siblings:
                if hasattr(sibling, "get_text"):
                    parts.append(sibling.get_text())
                else:
                    parts.append(str(sibling))
            player.membership_status = " ".join("".join(parts).split())

    def _parse_ratings_detail(self, html: str) -> pd.DataFrame | None:
        """Parse the per-round ratings table; returns None if there is none."""
        try:
            # Pin flavor to lxml so parsing is deterministic and never falls back to
            # html5lib (an unpinned optional dep) on sparse/no-table pages.
            tables = pd.read_html(StringIO(html), flavor="lxml")
        except ValueError:
            # No tables at all => player has no rated rounds.
            return None
        if not tables:
            return None

        df = tables[0]

        missing = [c for c in DETAIL_COLUMNS if c not in df.columns]
        if missing:
            raise PdgaParseError(
                "pdga.com ratings-detail table is missing expected column(s) "
                f"{missing}; got columns {list(df.columns)}. "
                "pdga.com details layout may have changed."
            )

        df = df[DETAIL_COLUMNS].copy()
        # Date cells can be a range "A to B"; keep the end date.
        df["Date"] = df["Date"].apply(lambda x: str(x).split(" to ")[-1])
        df["Date"] = pd.to_datetime(df["Date"], format="mixed")

        df = df.rename(columns=DETAIL_RENAME)
        df["round"] = df["round"].astype(str)
        return df
