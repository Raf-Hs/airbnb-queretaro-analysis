"""Compute headline metrics, bootstrap confidence intervals and exploratory tests.

Writes reports/key_metrics.json so every number quoted in the README and the
findings report can be traced back to a reproducible calculation.

Caveats baked into the method:
  * n=99 city listings; bootstrap CIs describe *this sample*, not the market.
  * Tests are exploratory. With 100 observations and many comparisons, p-values
    are not confirmatory and are reported alongside effect sizes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from config import LISTINGS_CLEAN, RATES_CLEAN, REPORTS_DIR

RNG = np.random.default_rng(20261025)
N_BOOT = 10_000


def bootstrap_ci(values: np.ndarray, statistic=np.median, n_boot: int = N_BOOT) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) < 3:
        return (float("nan"), float("nan"))
    draws = RNG.choice(values, size=(n_boot, len(values)), replace=True)
    stats_ = statistic(draws, axis=1)
    return float(np.percentile(stats_, 2.5)), float(np.percentile(stats_, 97.5))


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Probability that a random value from A exceeds one from B, rescaled to [-1, 1]."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    gt = sum((x > b).sum() for x in a)
    lt = sum((x < b).sum() for x in a)
    return (gt - lt) / (len(a) * len(b))


def compare(city: pd.DataFrame, mask_a: pd.Series, mask_b: pd.Series, label: str) -> dict:
    out = {"comparison": label}
    for col in ("price_mxn", "occupancy", "revenue_mxn"):
        a = city.loc[mask_a, col].dropna().to_numpy()
        b = city.loc[mask_b, col].dropna().to_numpy()
        if len(a) < 3 or len(b) < 3:
            continue
        u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
        out[col] = {
            "group_a_median": float(np.median(a)),
            "group_b_median": float(np.median(b)),
            "ratio_a_to_b": float(np.median(a) / np.median(b)) if np.median(b) else None,
            "mann_whitney_p": float(p),
            "cliffs_delta": float(cliffs_delta(a, b)),
            "n_a": int(len(a)),
            "n_b": int(len(b)),
        }
    return out


def main() -> None:
    listings = pd.read_csv(LISTINGS_CLEAN, dtype={"listing_id": str, "postal_code": str})
    rates = pd.read_csv(RATES_CLEAN, dtype={"listing_id": str}, parse_dates=["month_start"])
    city = listings[listings["is_city_core"]].copy()
    monthly = rates[rates["listing_id"].isin(city["listing_id"])].copy()
    complete = monthly[monthly["month_start"] <= "2026-04-01"].copy()

    metrics: dict = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": {
            "listings_total": int(len(listings)),
            "listings_city": int(len(city)),
            "rural_outliers": int((~listings["is_city_core"]).sum()),
            "hosts": int(city["host_id"].nunique()),
            "superhosts": int(city["superhost"].sum()),
            "professionally_managed": int(city["professional_management"].sum()),
            "professional_hosts": int(city.loc[city["professional_management"] == 1, "host_id"].nunique()),
            "entire_homes": int((city["room_type"] == "entire_home").sum()),
            "private_rooms": int((city["room_type"] == "private_room").sum()),
            "within_1km_pct": float(100 * (city["distance_centro_km"] <= 1).mean()),
            "months": int(monthly["month_start"].nunique()),
        },
        "headline": {},
        "bootstrap_ci_95": {},
        "room_type": {},
        "seasonality": {},
        "concentration": {},
        "correlations": {},
        "tests": [],
    }

    for col in ("price_mxn", "occupancy", "adjusted_occupancy", "revenue_mxn", "revpar_mxn"):
        s = city[col].dropna().to_numpy()
        metrics["headline"][col] = {
            "n": int(len(s)),
            "mean": float(np.mean(s)),
            "median": float(np.median(s)),
            "p25": float(np.percentile(s, 25)),
            "p75": float(np.percentile(s, 75)),
            "min": float(np.min(s)),
            "max": float(np.max(s)),
        }
        lo, hi = bootstrap_ci(s, np.median)
        metrics["bootstrap_ci_95"][col] = {"statistic": "median", "low": lo, "high": hi}

    # Room-type split
    for room, label in (("entire_home", "entire_home"), ("private_room", "private_room")):
        sub = city[city["room_type"] == room]
        metrics["room_type"][label] = {
            "n": int(len(sub)),
            "share_pct": float(100 * len(sub) / len(city)),
            "median_adr_mxn": float(sub["price_mxn"].median()),
            "median_occupancy": float(sub["occupancy"].median()),
            "median_revenue_mxn": float(sub["revenue_mxn"].median()),
            "revenue_share_pct": float(100 * sub["revenue_mxn"].sum() / city["revenue_mxn"].sum()),
        }

    # Seasonality on the complete window
    month = (
        complete.groupby("month_start")
        .agg(
            listings=("listing_id", "nunique"),
            reserved=("reserved_days", "sum"),
            available=("nights_available", "sum"),
            revenue=("revenue_mxn", "sum"),
            adr_quoted=("adr_quoted_mxn", "median"),
            adr_booked=("adr_booked_mxn", "median"),
        )
        .reset_index()
    )
    month["occupancy"] = month["reserved"] / month["available"]
    metrics["seasonality"] = {
        "complete_window": ["2025-08-01", "2026-04-01"],
        "note": "May-Jul 2026 are right-censored by the data snapshot and excluded from realised-demand claims.",
        "months": [
            {
                "month": r.month_start.strftime("%Y-%m"),
                "occupancy": round(float(r.occupancy), 4),
                "median_adr_quoted": round(float(r.adr_quoted), 1),
                "median_adr_booked": None if pd.isna(r.adr_booked) else round(float(r.adr_booked), 1),
                "revenue_mxn": round(float(r.revenue), 0),
            }
            for r in month.itertuples()
        ],
        "peak_occupancy_month": month.loc[month["occupancy"].idxmax(), "month_start"].strftime("%Y-%m"),
        "peak_revenue_month": month.loc[month["revenue"].idxmax(), "month_start"].strftime("%Y-%m"),
        "lowest_occupancy_month": month.loc[month["occupancy"].idxmin(), "month_start"].strftime("%Y-%m"),
    }

    # Concentration
    rev = np.sort(city["revenue_mxn"].to_numpy())
    n = len(rev)
    cum = np.cumsum(rev) / rev.sum()
    metrics["concentration"] = {
        "total_revenue_mxn": float(rev.sum()),
        "gini": float((n + 1 - 2 * np.sum(cum)) / n),
        "top10_pct_share": float(rev[::-1][: int(np.ceil(n * 0.10))].sum() / rev.sum() * 100),
        "top20_pct_share": float(rev[::-1][: int(np.ceil(n * 0.20))].sum() / rev.sum() * 100),
        "top50_pct_share": float(rev[::-1][: int(np.ceil(n * 0.50))].sum() / rev.sum() * 100),
        "top_host_listings": int(city["host_id"].value_counts().iloc[0]),
        "top_host_share_pct": float(
            100 * city.loc[city["host_id"] == city["host_id"].value_counts().idxmax(), "revenue_mxn"].sum()
            / city["revenue_mxn"].sum()
        ),
    }

    # Correlations (Spearman, pairwise complete)
    pairs = [
        ("price_mxn", "occupancy"),
        ("price_mxn", "distance_centro_km"),
        ("price_mxn", "guests"),
        ("price_mxn", "bedrooms"),
        ("revenue_mxn", "occupancy"),
        ("revenue_mxn", "price_mxn"),
        ("occupancy", "num_reviews"),
        ("rating_overall", "occupancy"),
        ("rating_overall", "price_mxn"),
    ]
    city["_bedrooms_float"] = city["bedrooms"].astype(float)
    for a, b in pairs:
        sub = city[[a, b]].dropna()
        rho, p = stats.spearmanr(sub[a], sub[b])
        metrics["correlations"][f"{a}__{b}"] = {
            "spearman_rho": float(rho),
            "p_value": float(p),
            "n": int(len(sub)),
        }

    # Exploratory group comparisons
    metrics["tests"].append(
        compare(city, city["room_type"] == "entire_home", city["room_type"] == "private_room",
                "entire_home vs private_room")
    )
    metrics["tests"].append(
        compare(city, city["superhost"] == 1, city["superhost"] == 0, "superhost vs not")
    )
    metrics["tests"].append(
        compare(city, city["professional_management"] == 1, city["professional_management"] == 0,
                "professionally managed vs independent")
    )

    # Within-listing price changes: controls for the fact that the monthly
    # median can move because of composition, not repricing.
    price_pivot = monthly.pivot_table(
        index="listing_id", columns="month_start", values="adr_quoted_mxn"
    )
    occ_pivot = monthly.pivot_table(
        index="listing_id", columns="month_start", values="occupancy"
    )
    base = price_pivot[pd.Timestamp("2025-08-01")]
    paired = pd.DataFrame(
        {"aug": base, "apr": price_pivot[pd.Timestamp("2026-04-01")]}
    ).dropna()
    paired["change"] = paired["apr"] / paired["aug"] - 1

    price_index = price_pivot.div(base, axis=0).mul(100)
    occ_change = occ_pivot.sub(occ_pivot[pd.Timestamp("2025-08-01")], axis=0).mul(100)

    metrics["within_listing"] = {
        "paired_listings": int(len(paired)),
        "median_adr_change_pct_aug_to_apr": float(paired["change"].median() * 100),
        "mean_adr_change_pct_aug_to_apr": float(paired["change"].mean() * 100),
        "share_raising_adr_pct": float((paired["change"] > 0).mean() * 100),
        "price_index_aug100": {
            str(k.date()): {
                "median": round(float(v), 1),
                "p25": round(float(price_index[k].quantile(0.25)), 1),
                "p75": round(float(price_index[k].quantile(0.75)), 1),
            }
            for k, v in price_index.median().items()
        },
        "occupancy_change_pp_vs_aug": {
            str(k.date()): {
                "median": round(float(v), 1),
                "p25": round(float(occ_change[k].quantile(0.25)), 1),
                "p75": round(float(occ_change[k].quantile(0.75)), 1),
            }
            for k, v in occ_change.median().items()
        },
        "note": "Median across listings of each listing's ratio to its own Aug-2025 ADR. "
                "A 9-month window cannot separate a repricing trend from seasonal pricing.",
    }

    # Consistency: monthly revenue vs the TTM field
    monthly_sum = float(monthly["revenue_mxn"].sum())
    metrics["consistency"] = {
        "monthly_revenue_sum_mxn": monthly_sum,
        "ttm_revenue_sum_mxn": float(city["revenue_mxn"].sum()),
        "difference_pct": float(100 * (city["revenue_mxn"].sum() - monthly_sum) / monthly_sum),
        "monthly_reserved_nights": int(monthly["reserved_days"].sum()),
        "ttm_reserved_nights": int(city["ttm_reserved_days"].sum()),
        "note": "Reserved nights match exactly; TTM revenue is slightly higher, consistent with fees "
                "collected outside the nightly rate (cleaning/extra-guest).",
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "key_metrics.json"
    out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({k: metrics[k] for k in ("sample", "headline", "concentration")}, indent=2)[:3500])
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
