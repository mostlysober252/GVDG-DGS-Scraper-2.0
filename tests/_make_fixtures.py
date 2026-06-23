"""Generate pdga.com-shaped HTML fixtures for the offline build_players test.

This is a DEV helper, not part of the test run. It writes:
  * tests/fixtures/profile_<n>.html  — a minimal profile page (name, rating)
  * tests/fixtures/detail_<n>.html   — the per-round ratings-detail table

The detail table mirrors the real pdga.com column layout
(Tournament, Date, Tier, Division, Round, Rating, Evaluated, Included)
so pandas.read_html parses it exactly like the live page. Round data is
seeded from the upstream regression CSVs.

Run:  python tests/_make_fixtures.py
"""

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
FIX = HERE / "fixtures"

PROFILE_TMPL = """<!doctype html>
<html>
<head><title>{name} | Professional Disc Golf Association</title></head>
<body>
  <div class="pane-content">
    <ul class="player-info">
      <li class="location">Location: Greenville, North Carolina, United States</li>
      <li class="current-rating">Current Rating: {rating}
        <small class="rating-date">(as of {rating_date})</small>
      </li>
    </ul>
    <p><strong>Membership Status:</strong> Current (through 31-Dec-2026)</p>
  </div>
</body>
</html>
"""

DETAIL_TMPL = """<!doctype html>
<html>
<head><title>{name} Ratings Detail | Professional Disc Golf Association</title></head>
<body>
  <div class="pane-content">
    {table}
  </div>
</body>
</html>
"""


def _detail_table_html(df: pd.DataFrame) -> str:
    """Render a detail DataFrame as a pdga.com-shaped HTML table."""
    out = df.rename(
        columns={
            "tournament": "Tournament",
            "date": "Date",
            "tier": "Tier",
            "division": "Division",
            "round": "Round",
            "rating": "Rating",
            "evaluated": "Evaluated",
            "used": "Included",
        }
    )
    cols = [
        "Tournament",
        "Date",
        "Tier",
        "Division",
        "Round",
        "Rating",
        "Evaluated",
        "Included",
    ]
    for c in cols:
        if c not in out.columns:
            out[c] = ""
    out = out[cols]
    return out.to_html(index=False, table_id="player-results-details")


def make_for(pdga_no: int, name: str, rating: int, rating_date: str, csv_name: str):
    df = pd.read_csv(FIX / csv_name)
    profile = PROFILE_TMPL.format(name=name, rating=rating, rating_date=rating_date)
    detail = DETAIL_TMPL.format(name=name, table=_detail_table_html(df))
    (FIX / f"profile_{pdga_no}.html").write_text(profile)
    (FIX / f"detail_{pdga_no}.html").write_text(detail)
    print(f"wrote profile_{pdga_no}.html and detail_{pdga_no}.html")


if __name__ == "__main__":
    # Tyler Adkins — small fixture incl. an "(Unrated)" tournament + low round.
    make_for(298827, "Tyler Adkins", 768, "10-Mar-2026", "player_298827_2026-03-10.csv")
    # David Caravas — mid-size fixture.
    make_for(204766, "David Caravas", 857, "11-Nov-2025", "player_204766_2025-11-11.csv")
    # A "no rated rounds" profile: profile present, detail page has no table.
    name = "Empty Player"
    (FIX / "profile_999999.html").write_text(
        PROFILE_TMPL.format(name=name, rating="", rating_date="01-Jan-2026")
    )
    (FIX / "detail_999999.html").write_text(
        "<!doctype html><html><head><title>%s | PDGA</title></head>"
        "<body><p>No ratings detail available.</p></body></html>" % name
    )
    print("wrote profile_999999.html and detail_999999.html (no-rounds case)")
