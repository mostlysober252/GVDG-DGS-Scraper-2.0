# GVDG Players Ratings Pipeline

Scrapes pdga.com for each club member, computes a **live (unofficial) PDGA
rating** from their round history, and emits `players.json` for the GVDG
member portal. Runs daily via GitHub Actions.

The rating algorithm is a faithful port of
[`cclark20/pdga-whats-my-rating`](https://github.com/cclark20/pdga-whats-my-rating)
(MIT). See [`NOTICE`](NOTICE) and the docstring in `pipeline/rating.py`.

## Layout

| Path | Purpose |
|------|---------|
| `pipeline/rating.py` | **Pure** rating algorithm (12-mo window, last-25% double-weight, iterative outlier removal). No I/O. |
| `pipeline/pdga.py` | pdga.com scraping behind an **injectable** `fetch_html` callable. Raises `PdgaParseError` on HTML/schema drift. |
| `pipeline/build_players.py` | Orchestrator: roster.json → scrape + compute → players.json. |
| `pipeline/stats.py` | **Pure** transforms over the scraped rounds: groups a player's rated rounds into a tournament history + career summary (`build_stats_record`). Also ports `count_scores` (see below). No I/O. |
| `pipeline/build_stats.py` | Orchestrator: roster.json → scrape (same `PdgaScraper`) + transform → stats.json. |
| `roster.json` | Club roster: a list of PDGA numbers to build ratings for. |
| `tests/` | pytest suite (offline; never touches the network). |
| `tests/fixtures/` | Saved pdga.com HTML + regression CSVs used by the tests. |
| `.github/workflows/players.yml` | Daily cron that runs the pipeline and commits `players.json` **and** `stats.json` (one scrape refreshes both). |

## Run locally

```bash
pip install -r requirements.txt
python -m pipeline.build_players                 # reads roster.json, writes players.json
python -m pipeline.build_stats                   # reads roster.json, writes stats.json
# or override paths:
python -m pipeline.build_players --roster roster.json --out players.json
python -m pipeline.build_stats   --roster roster.json --out stats.json
```

Each makes live HTTP requests to pdga.com (one profile page + one
ratings-detail page per roster entry). `build_stats` reuses the **same**
`PdgaScraper` as `build_players` — it adds no new scraping logic, only a
transform over the rounds A1 already scrapes. The daily Action
(`players.yml`) runs both in one job so a single scrape refreshes both
`players.json` and `stats.json`.

## Run tests

```bash
pip install -r requirements.txt
pytest          # from the repo root
```

The whole suite is **offline**: rating tests use checked-in CSV fixtures, and
the orchestrator test injects a fake fetcher that returns saved HTML. No test
makes a network request.

## roster.json format

Either a bare list of PDGA numbers:

```json
[167210, 204766, 298827]
```

…or an object with a `pdga_numbers` key (the shipped sample uses this form so
it can carry a comment):

```json
{ "pdga_numbers": [167210, 204766, 298827] }
```

## players.json schema

Keyed by PDGA number (string keys). A player with **no rated rounds** is
omitted. `official_rating` is `null` when pdga.com shows no current rating
(e.g. lapsed membership).

```json
{
  "lastUpdated": "2026-06-23T12:00:00+00:00",
  "players": {
    "12345": {
      "pdga_no": 12345,
      "name": "Jane Doe",
      "official_rating": 945,
      "live_rating": 951,
      "rating_history": [
        { "date": "2026-05-01", "rating": 948, "event": "Down East Players Cup" }
      ]
    }
  }
}
```

Field notes:

- `live_rating` — integer, computed by `pipeline.rating.calculate_rating`.
- `official_rating` — integer or `null`, scraped from the pdga.com profile.
- `rating_history` — one entry per event (tournament + date), using that
  event's best round rating, ordered **oldest-first**. `date` is ISO
  `YYYY-MM-DD`.

## stats.json schema

A per-member **tournament history** + **career summary**, also keyed by PDGA
number (string keys). It is a transform over the same rated rounds used for
`players.json`: a player's rounds are grouped by event `(tournament, date)`,
**newest event first**. A player with no rated rounds is omitted.

```json
{
  "lastUpdated": "2026-06-23T12:00:00+00:00",
  "players": {
    "12345": {
      "pdga_no": 12345,
      "name": "Jane Doe",
      "summary": {
        "events_count": 12,
        "rated_rounds": 41,
        "latest_rating": 951,
        "peak_rating": 968,
        "first_event_date": "2019-05-01",
        "last_event_date": "2026-05-01"
      },
      "events": [
        {
          "tournament": "Down East Players Cup",
          "date": "2026-05-01",
          "division": "MPO",
          "tier": "A",
          "rounds": [{ "round": 1, "rating": 948 }],
          "high_round": 962,
          "avg_round": 951
        }
      ]
    }
  }
}
```

Field notes:

- `events` — one entry per `(tournament, date)`, ordered **newest-first**
  (date descending; ties broken by tournament name). `date` is ISO
  `YYYY-MM-DD`. `division` / `tier` come from the event's first round and may
  be `null` if pdga.com leaves them blank.
- `rounds` — the event's rated rounds, ordered by round number; each is
  `{ "round": <int>, "rating": <int> }`.
- `high_round` — the event's best (max) round rating.
- `avg_round` — the event's mean round rating, rounded to the nearest int.
- `summary.latest_rating` — the most recent rated round's rating (the last
  round of the newest event); `null` if the player has no rated rounds.
- `summary.peak_rating` — the highest single round rating ever; `null` if none.
- `summary.first_event_date` / `last_event_date` — ISO date bounds of the
  event history; `null` if the player has no rated rounds.

### `count_scores` (not in stats.json v1)

`pipeline/stats.py` also ports `count_scores(pars, scores)` — a pure tally of
a round's score distribution (aces / eagles+ / birdies / pars / bogeys /
doubles+) from hole-by-hole data (credit: cclark20/disc-golf-data, MIT).

**pdga.com exposes no hole-by-hole data** — only a per-round *rating* — so
`count_scores` is **NOT populated in stats.json v1**. It is included, pure and
tested, for a future slice that ingests
[udisclive](https://udisclive.com)-tracked events, which do expose hole scores.

## Schema-drift behavior

pdga.com HTML changes break scrapers silently. To make drift loud:

- All selectors / expected column names are centralized at the top of
  `pipeline/pdga.py`.
- If the ratings-detail table is missing an expected column (or the profile
  has no `<title>`), the scraper raises `PdgaParseError` with a message naming
  what was expected.
- In `build_players`, a `PdgaParseError` (or any fetch error) for one player
  is logged and that player is skipped, so a single drift/outage never aborts
  the whole run. Watch the Action logs for "Schema drift / parse error".

## Updating the roster

Replace the sample PDGA numbers in `roster.json` with the club's real member
numbers. The sample numbers are real pdga.com players borrowed from the
upstream test fixtures and are placeholders only.
