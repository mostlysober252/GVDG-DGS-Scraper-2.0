"""Pure PDGA live-rating algorithm — NO I/O.

This is a faithful port of the ``calculate_rating`` function from
cclark20/pdga-whats-my-rating (MIT license), specifically:

    pdga_whats_my_rating/utils/rating_calc.py

The only intentional difference from the source is the removal of the
``@st.cache_data`` Streamlit decorator (this package has no Streamlit
dependency). The numeric behaviour — window selection, double-weighting,
and iterative outlier removal — is identical to the source so that the
ported test suite (tests/test_rating.py, ported from the upstream
test_rating_calc.py / test_rating_accuracy.py) continues to hold.

PDGA rating rules implemented here:
  * 12-month evaluation window, extended to 24 months when fewer than 8
    rounds fall in the last 12 months.
  * The most recent 25% of evaluated rounds are double-weighted, but only
    when there are >= 9 evaluated rounds.
  * Outlier rounds are dropped iteratively. A round is an outlier when its
    rating is at or below the drop threshold, where the threshold is
    ``ceil(avg - floor(2.5*SD)) + 5`` when ``2.5*SD < 100``, otherwise
    ``ceil(avg - 100)``. Outlier removal only runs with >= 7 evaluated
    rounds.
  * XM-tier rounds and "(Unrated)" tournaments are excluded.

Credit: cclark20/pdga-whats-my-rating (https://github.com/cclark20/pdga-whats-my-rating)
"""

import math

import numpy as np
import pandas as pd


def calculate_rating(df):
    """Compute a player's live (unofficial) PDGA rating from round history.

    Args:
        df: A pandas DataFrame of rated rounds with (at least) the columns
            ``rating``, ``date``, ``tier``, ``round`` and ``tournament``.

    Returns:
        A 4-tuple ``(df, rating, threshold, window_months)`` where:
          * ``df`` is the input augmented with ``weight``, ``evaluated``,
            ``used``, ``mavg_5`` and ``mavg_15`` columns and sorted most
            recent first;
          * ``rating`` is the integer calculated rating (0 if no rounds
            qualify);
          * ``threshold`` is the final outlier drop threshold;
          * ``window_months`` is 12 or 24.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], format="mixed")
    df = df.sort_values(by=["date", "round"], ascending=[False, True]).reset_index(
        drop=True
    )
    df["weight"] = 0  # init weights at 0
    df["evaluated"] = "No"
    df["used"] = "No"

    df = df[df.tier != "XM"]
    unrated = df.tournament.str.contains("(Unrated)", case=False, na=False, regex=False)

    # set valid dates to 1
    max_date = df.loc[~unrated, "date"].max()
    min_date = max_date - pd.DateOffset(years=1)
    valid_dates = (df["date"] >= min_date) & ~unrated

    # If <8 rounds in 12 months, extend to 24 months (PDGA rule)
    window_months = 12
    if valid_dates.sum() < 8:
        min_date = max_date - pd.DateOffset(years=2)
        valid_dates = (df["date"] >= min_date) & ~unrated
        window_months = 24

    df.loc[valid_dates, "weight"] = 1
    df.loc[valid_dates, "evaluated"] = "Yes"

    # double the last 25% (computed before outlier removal)
    # only when >=9 evaluated rounds (PDGA rule)
    evaluated_count = valid_dates.sum()
    if evaluated_count >= 9:
        num_double = round(evaluated_count * 0.25)
        df.loc[: (num_double - 1), "weight"] = 2

    # iteratively remove outliers — dropping a round shifts the
    # avg/std, which may expose additional outliers.
    # Only when >=7 evaluated rounds (PDGA rule).
    # 10 is just a safety cap; typically converges in 2-3 passes.
    threshold = 0
    if (df["weight"] > 0).sum() >= 7:
        for _ in range(10):
            used_mask = df["weight"] > 0
            if used_mask.sum() == 0:
                break
            std = df.loc[used_mask, "rating"].std(ddof=0)
            if std == 0:
                break
            avg = df.loc[used_mask, "rating"].mean()
            if (2.5 * std) < 100:
                new_threshold = math.ceil(avg - math.floor(2.5 * std)) + 5
            else:
                new_threshold = math.ceil(avg - 100)
            if new_threshold == threshold:
                break
            threshold = new_threshold
            df.loc[df["rating"] <= threshold, "weight"] = 0

    # set used col
    df.loc[df["weight"] > 0, "used"] = "Yes"

    # set moving avgs
    avg1 = 5
    avg2 = 15

    df_asc = df.sort_values(by=["date", "round"], ascending=True)
    df["mavg_5"] = df_asc.rating.rolling(avg1, min_periods=1).mean()
    df["mavg_15"] = df_asc.rating.rolling(avg2, min_periods=1).mean()

    # rating
    if df["weight"].sum() == 0:
        return df, 0, threshold, window_months

    rating = np.average(df.rating, weights=df.weight)

    return df, int(math.ceil(rating)), threshold, window_months
