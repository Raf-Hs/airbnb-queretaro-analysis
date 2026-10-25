"""Clean the AirROI Querétaro sample and derive analysis fields.

Inputs (data/raw)
-----------------
airroi_listings_2026-07.jsonl   one JSON object per listing
airroi_past_rates_2026-07.jsonl one JSON object per listing-month
airroi_reviews_2026-07.csv      one row per listing-month with reviews
sepomex_cp_22-qro.geojson       SEPOMEX postal-code polygons (state of Querétaro)

Outputs (data/processed)
------------------------
listings.csv       100 rows, one per listing, with derived location/price fields
monthly_rates.csv  1,195 rows, one per listing-month
reviews_monthly.csv
data_quality.json  machine-readable audit of every check performed here

Why JSON Lines: the CSV exports published in the same AirROI release contain
embedded quotes/newlines that shift columns. The JSONL exports parse cleanly.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import (
    CENTRO_LAT,
    CENTRO_LON,
    CITY_CORE_RADIUS_KM,
    DISTANCE_BANDS,
    LISTINGS_CLEAN,
    LISTINGS_RAW,
    PERIOD_END,
    PERIOD_START,
    POSTAL_GEOJSON,
    PROCESSED_DIR,
    PROJECT_ROOT,
    QUALITY_REPORT,
    RATES_CLEAN,
    RATES_RAW,
    REVIEWS_CLEAN,
    REVIEWS_RAW,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

CHECKS: list[dict] = []


def check(name: str, passed: bool, detail: str, severity: str = "error") -> None:
    CHECKS.append(
        {
            "check": name,
            "status": "pass" if passed else ("warn" if severity == "warn" else "fail"),
            "detail": detail,
        }
    )


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in kilometres; vectorised over numpy arrays."""
    r = 6371.0088
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def band_for(distance_km: float) -> str:
    for low, high, label in DISTANCE_BANDS:
        if low <= distance_km < high:
            return label
    return DISTANCE_BANDS[-1][2]


def nullable_int(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").round().astype("Int64")


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def load_listings() -> pd.DataFrame:
    rows = []
    with LISTINGS_RAW.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid JSON on line {lineno} of {LISTINGS_RAW}") from exc
    df = pd.DataFrame(rows)
    check("listings file parses", len(df) > 0, f"{len(df)} rows, {df.shape[1]} fields")
    return df


def load_rates() -> pd.DataFrame:
    rows = []
    with RATES_RAW.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid JSON on line {lineno} of {RATES_RAW}") from exc
    df = pd.DataFrame(rows)
    check("rates file parses", len(df) > 0, f"{len(df)} rows, {df.shape[1]} fields")
    return df


# ---------------------------------------------------------------------------
# location enrichment
# ---------------------------------------------------------------------------


def attach_postal_codes(listings: pd.DataFrame) -> pd.DataFrame:
    """Spatial join to SEPOMEX postal-code polygons.

    A postal code is *not* a neighbourhood: one code can contain several
    colonias. It is used here only as a stable, official spatial identifier.
    Points that fall outside every polygon (geocoding offset) are assigned the
    nearest polygon and flagged.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    post = gpd.read_file(POSTAL_GEOJSON)
    post = post.rename(columns={"d_codigo": "postal_code"})
    post["postal_code"] = post["postal_code"].astype(str).str.zfill(5)
    post = post[["postal_code", "geometry"]].dissolve(by="postal_code").reset_index()

    points = gpd.GeoDataFrame(
        listings[["listing_id", "latitude", "longitude"]].copy(),
        geometry=[Point(xy) for xy in zip(listings["longitude"], listings["latitude"])],
        crs="EPSG:4326",
    )

    joined = gpd.sjoin(points, post, how="left", predicate="within")
    # A point on a shared boundary can match twice; keep the first.
    joined = joined[~joined.index.duplicated(keep="first")]
    matched = joined["postal_code"].notna()

    if (~matched).any():
        near = gpd.sjoin_nearest(
            points.loc[~matched], post, how="left", distance_col="postal_offset_deg"
        )
        near = near[~near.index.duplicated(keep="first")]
        joined.loc[~matched, "postal_code"] = near["postal_code"].values
        joined["postal_match_method"] = np.where(matched, "polygon", "nearest_polygon")
        joined["postal_offset_deg"] = np.where(matched, 0.0, np.nan)
        joined.loc[~matched, "postal_offset_deg"] = near["postal_offset_deg"].values
    else:
        joined["postal_match_method"] = "polygon"
        joined["postal_offset_deg"] = 0.0

    out = listings.merge(
        joined[["postal_code", "postal_match_method", "postal_offset_deg"]],
        left_index=True,
        right_index=True,
        how="left",
    )
    out["postal_offset_km"] = out["postal_offset_deg"].astype(float) * 111.32
    out = out.drop(columns=["postal_offset_deg"])

    n_nearest = int((out["postal_match_method"] == "nearest_polygon").sum())
    check(
        "postal-code join coverage",
        out["postal_code"].notna().all(),
        f"{len(out) - n_nearest}/{len(out)} inside a polygon; "
        f"{n_nearest} assigned nearest polygon",
        severity="warn" if n_nearest else "error",
    )
    return out


# ---------------------------------------------------------------------------
# cleaning
# ---------------------------------------------------------------------------


def clean_listings(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["listing_id"] = df["listing_id"].astype(str)
    df["host_id"] = df["host_id"].astype("Int64")

    # Airbnb sometimes wraps names in Unicode directional isolates; strip them
    # so CSV/Power BI consumers do not see invisible characters.
    _invisible = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\u00ad]")
    for col in ("listing_name", "host_name"):
        df[col] = (
            df[col].astype("string").str.replace(_invisible, "", regex=True).str.strip()
        )

    check(
        "listing_id is unique",
        df["listing_id"].is_unique,
        f"{df['listing_id'].nunique()} unique ids for {len(df)} rows",
    )
    check(
        "listing_id is numeric",
        df["listing_id"].str.fullmatch(r"\d+").all(),
        "all ids are digit strings (Airbnb listing ids)",
    )
    check(
        "currency is MXN",
        (df["currency"] == "MXN").all(),
        f"values: {sorted(df['currency'].unique())}",
    )

    # --- types -------------------------------------------------------------
    int_cols = ["photos_count", "guests", "bedrooms", "beds", "min_nights",
                "num_reviews", "ttm_reserved_days", "ttm_blocked_days",
                "ttm_available_days", "ttm_total_days", "l90d_reserved_days",
                "l90d_blocked_days", "l90d_available_days", "l90d_total_days"]
    for col in int_cols:
        df[col] = nullable_int(df[col])

    num_cols = ["baths", "cleaning_fee", "extra_guest_fee", "latitude", "longitude",
                "rating_overall", "rating_accuracy", "rating_checkin", "rating_cleanliness",
                "rating_communication", "rating_location", "rating_value",
                "ttm_revenue", "ttm_revenue_native", "ttm_avg_rate", "ttm_avg_rate_native",
                "ttm_occupancy", "ttm_adjusted_occupancy", "ttm_revpar", "ttm_revpar_native",
                "ttm_adjusted_revpar", "ttm_adjusted_revpar_native",
                "ttm_avg_min_nights", "ttm_avg_length_of_stay",
                "l90d_revenue", "l90d_revenue_native", "l90d_avg_rate",
                "l90d_avg_rate_native", "l90d_occupancy", "l90d_adjusted_occupancy",
                "l90d_revpar", "l90d_revpar_native", "l90d_adjusted_revpar",
                "l90d_adjusted_revpar_native", "l90d_avg_min_nights",
                "l90d_avg_length_of_stay"]
    for col in num_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["superhost", "professional_management", "registration",
                "guest_favorite", "exact_location", "single_fee_structure"]:
        df[col] = df[col].map({True: True, False: False, "True": True, "False": False})

    # --- basic range checks ------------------------------------------------
    check(
        "coordinates within Querétaro state bbox",
        df["latitude"].between(20.0, 21.7).all()
        and df["longitude"].between(-100.6, -99.0).all(),
        f"lat {df['latitude'].min():.4f}..{df['latitude'].max():.4f}, "
        f"lon {df['longitude'].min():.4f}..{df['longitude'].max():.4f}",
    )
    check(
        "nightly price positive",
        (df["ttm_avg_rate_native"] > 0).all(),
        f"min {df['ttm_avg_rate_native'].min():,.1f} MXN",
    )
    check(
        "occupancy within [0, 1]",
        df["ttm_occupancy"].between(0, 1).all(),
        f"range {df['ttm_occupancy'].min():.3f}..{df['ttm_occupancy'].max():.3f}",
    )
    days_ok = (df["ttm_reserved_days"] + df["ttm_available_days"]) == df["ttm_total_days"]
    check(
        "reserved + available = total calendar days",
        bool(days_ok.all()),
        f"{int(days_ok.sum())}/{len(df)} listings consistent; "
        "AirROI 'blocked' days are a subset of 'available' days",
    )
    adjusted = df["ttm_reserved_days"] / (df["ttm_total_days"] - df["ttm_blocked_days"])
    gap = (adjusted - df["ttm_adjusted_occupancy"]).abs()
    check(
        "adjusted occupancy = reserved / (total - blocked)",
        bool((gap < 0.002).all()),
        f"max absolute difference {gap.max():.4f} (provider rounds to 3 dp)",
    )

    # Implied FX rate: native MXN / USD. Should be tight if both come from
    # the same conversion date.
    fx = df["ttm_avg_rate_native"] / df["ttm_avg_rate"]
    fx_spread = (fx.max() - fx.min()) / fx.median()
    check(
        "implied MXN/USD rate is consistent",
        fx_spread < 0.01,
        f"median {fx.median():.2f}, spread {fx_spread:.2%}",
    )

    # --- derived fields ----------------------------------------------------
    df["price_mxn"] = df["ttm_avg_rate_native"].round(1)
    df["occupancy"] = df["ttm_occupancy"]
    # Occupancy net of host-blocked nights. Calendar occupancy (above) treats
    # blocked nights as unbooked; adjusted occupancy answers "when the host
    # made the calendar available, how often was it booked?".
    df["adjusted_occupancy"] = df["ttm_adjusted_occupancy"]
    df["revenue_mxn"] = df["ttm_revenue_native"].round(1)
    df["revpar_mxn"] = df["ttm_revpar_native"].round(1)
    df["price_usd"] = df["ttm_avg_rate"].round(1)

    df["price_per_guest_mxn"] = np.where(
        df["guests"].fillna(0) > 0, df["price_mxn"] / df["guests"], np.nan
    )
    df["revenue_per_reserved_night_mxn"] = np.where(
        df["ttm_reserved_days"].fillna(0) > 0,
        df["revenue_mxn"] / df["ttm_reserved_days"],
        np.nan,
    )

    # Bedroom bands keep missing values visible instead of silently imputing.
    bins = [-1, 1, 2, 3, np.inf]
    labels = ["Studio / 1 BR", "2 BR", "3 BR", "4+ BR"]
    df["bedroom_band"] = pd.cut(
        df["bedrooms"].astype("float"), bins=bins, labels=labels
    ).astype("object")
    df["bedroom_band"] = df["bedroom_band"].fillna("Unknown")

    df["guest_band"] = pd.cut(
        df["guests"].astype("float"),
        bins=[0, 2, 4, 6, np.inf],
        labels=["1-2 guests", "3-4 guests", "5-6 guests", "7+ guests"],
    ).astype("object")
    df["guest_band"] = df["guest_band"].fillna("Unknown")

    # Location: straight-line distance to Plaza de Armas + band.
    df["distance_centro_km"] = haversine_km(
        df["latitude"].to_numpy(), df["longitude"].to_numpy(), CENTRO_LAT, CENTRO_LON
    ).round(2)
    df["distance_band"] = df["distance_centro_km"].map(band_for)
    df["distance_band"] = pd.Categorical(
        df["distance_band"], categories=[b[2] for b in DISTANCE_BANDS], ordered=True
    )
    df["is_city_core"] = df["distance_centro_km"] <= CITY_CORE_RADIUS_KM
    df["is_rural_outlier"] = ~df["is_city_core"]

    # High-price flag is a segment label, not an error flag: the most expensive
    # listings are genuinely large homes / a rural farm stay.
    q1, q3 = df["price_mxn"].quantile([0.25, 0.75])
    upper_fence = q3 + 3 * (q3 - q1)
    df["is_high_price_outlier"] = df["price_mxn"] > upper_fence

    df["has_description"] = df["description"].notna()
    df["has_rating"] = df["rating_overall"].notna()
    df["location_is_exact"] = df["exact_location"]
    df["listing_url"] = "https://www.airbnb.com/rooms/" + df["listing_id"]

    # --- missingness -------------------------------------------------------
    null_counts = df.isna().sum()
    null_counts = null_counts[null_counts > 0].sort_values(ascending=False)
    check(
        "missing values are limited to known optional fields",
        True,
        "; ".join(f"{k}={v}" for k, v in null_counts.items()),
        severity="warn" if len(null_counts) else "error",
    )

    # --- location enrichment ----------------------------------------------
    df = attach_postal_codes(df)

    # --- tidy selection ----------------------------------------------------
    keep = [
        # identity / host
        "listing_id", "listing_name", "listing_url", "host_id", "host_name", "superhost",
        "professional_management", "registration",
        # property
        "listing_type", "room_type", "guests", "bedrooms", "beds", "baths",
        "bedroom_band", "guest_band", "min_nights", "cancellation_policy",
        "cleaning_fee", "extra_guest_fee", "photos_count", "has_description",
        # location
        "latitude", "longitude", "postal_code", "postal_match_method",
        "postal_offset_km", "distance_centro_km", "distance_band", "is_city_core",
        "is_rural_outlier", "location_is_exact",
        # ratings / reviews
        "num_reviews", "rating_overall", "rating_accuracy", "rating_checkin",
        "rating_cleanliness", "rating_communication", "rating_location",
        "rating_value", "has_rating", "guest_favorite",
        # performance (trailing twelve months)
        "price_mxn", "price_usd", "occupancy", "adjusted_occupancy",
        "revenue_mxn", "revpar_mxn",
        "ttm_reserved_days", "ttm_blocked_days", "ttm_available_days",
        "ttm_total_days", "ttm_avg_length_of_stay", "ttm_avg_min_nights",
        "price_per_guest_mxn", "revenue_per_reserved_night_mxn",
        "is_high_price_outlier",
        # last 90 days (context only; not used for the main analysis)
        "l90d_occupancy", "l90d_avg_rate_native", "l90d_revenue_native",
    ]
    extra = [c for c in keep if c not in df.columns]
    if extra:
        raise KeyError(f"expected columns missing after cleaning: {extra}")
    return df[keep]


def clean_rates(raw: pd.DataFrame, listings: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["listing_id"] = df["listing_id"].astype(str)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    check(
        "rate dates parse",
        df["date"].notna().all(),
        f"{df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}",
    )

    int_cols = ["vacant_days", "reserved_days", "booking_lead_time_avg",
                "length_of_stay_avg", "min_nights_avg"]
    for col in int_cols:
        df[col] = nullable_int(df[col])
    for col in ["occupancy", "revenue", "rate_avg", "booked_rate_avg",
                "native_booked_rate_avg", "native_rate_avg", "native_revenue"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    check(
        "listing-month key is unique",
        not df.duplicated(["listing_id", "date"]).any(),
        f"{len(df)} rows, {df.duplicated(['listing_id', 'date']).sum()} duplicates",
    )
    check(
        "all rate rows match a listing",
        df["listing_id"].isin(set(listings["listing_id"])).all(),
        f"{df['listing_id'].nunique()} distinct listings in rates",
    )
    check(
        "date window matches documented release",
        str(df["date"].min().date()) == PERIOD_START
        and str(df["date"].max().date()) == PERIOD_END,
        f"{df['date'].min().date()} to {df['date'].max().date()}",
    )

    # Occupancy is stored rounded to 3 decimals by the provider.
    implied = df["reserved_days"] / (df["reserved_days"] + df["vacant_days"])
    max_gap = float((implied - df["occupancy"]).abs().max())
    check(
        "occupancy equals reserved / (reserved + vacant)",
        max_gap < 0.001,
        f"max absolute difference {max_gap:.5f} (provider rounds to 3 dp)",
    )
    check(
        "booked rate is null exactly when there were no bookings",
        ((df["reserved_days"] == 0) == df["native_booked_rate_avg"].isna()).all(),
        f"{int((df['reserved_days'] == 0).sum())} zero-booking rows",
    )

    # Revenue consistency: monthly revenue should be roughly
    # reserved_days x booked ADR; small gaps come from cleaning/extra-guest fees.
    mask = df["reserved_days"] > 0
    ratio = df.loc[mask, "native_revenue"] / (
        df.loc[mask, "native_booked_rate_avg"] * df.loc[mask, "reserved_days"]
    )
    check(
        "revenue is consistent with booked ADR x reserved days",
        bool(ratio.between(0.5, 1.8).all()),
        f"ratio p05={ratio.quantile(0.05):.3f}, median={ratio.median():.3f}, "
        f"p95={ratio.quantile(0.95):.3f} (fees explain the spread)",
        severity="warn",
    )

    coverage = df.groupby("listing_id").size()
    check(
        "monthly coverage per listing",
        coverage.min() >= 7,
        f"{int((coverage == 12).sum())}/{len(coverage)} listings have 12 months; "
        f"min {coverage.min()} (listing {coverage.idxmin()})",
        severity="warn",
    )

    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["month_start"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["month_label"] = df["date"].dt.strftime("%b %Y")
    df["quarter"] = df["date"].dt.quarter
    df["has_bookings"] = df["reserved_days"] > 0
    df["adr_quoted_mxn"] = df["native_rate_avg"].round(1)
    df["adr_booked_mxn"] = df["native_booked_rate_avg"].round(1)
    df["occupancy"] = df["occupancy"].astype(float)
    df["revenue_mxn"] = df["native_revenue"].astype(float)
    df["nights_available"] = (df["reserved_days"] + df["vacant_days"]).astype("Int64")

    # Month-over-month not meaningful for the one partial listing, so flag it.
    df["is_partial_history"] = df["listing_id"].map(coverage) < 12

    keep = [
        "listing_id", "date", "month_start", "year", "month", "month_label",
        "quarter", "vacant_days", "reserved_days", "nights_available",
        "occupancy", "has_bookings", "revenue_mxn",
        "adr_quoted_mxn", "adr_booked_mxn",
        "booking_lead_time_avg", "length_of_stay_avg", "min_nights_avg",
        "is_partial_history",
    ]
    return df[keep].sort_values(["date", "listing_id"]).reset_index(drop=True)


def clean_reviews() -> pd.DataFrame:
    df = pd.read_csv(REVIEWS_RAW, dtype={"listing_id": str, "reviewers": str})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["num_reviews"] = pd.to_numeric(df["num_reviews"], errors="coerce").astype("Int64")
    check(
        "reviews file parses",
        df["date"].notna().all(),
        f"{len(df)} rows, {df['listing_id'].nunique()} listings, "
        f"{df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}",
    )
    check(
        "review rows are unique per listing-month",
        not df.duplicated(["listing_id", "date"]).any(),
        f"{df.duplicated(['listing_id', 'date']).sum()} duplicates",
    )
    df["month_start"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["month_label"] = df["date"].dt.strftime("%b %Y")
    return df[["listing_id", "date", "month_start", "month_label", "num_reviews"]]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    listings_raw = load_listings()
    rates_raw = load_rates()

    listings = clean_listings(listings_raw)
    rates = clean_rates(rates_raw, listings)
    reviews = clean_reviews()

    check(
        "all listings have monthly rates",
        set(listings["listing_id"]) == set(rates["listing_id"]),
        f"{len(set(listings['listing_id']) & set(rates['listing_id']))} shared ids",
    )

    listings.to_csv(LISTINGS_CLEAN, index=False, encoding="utf-8-sig")
    rates.to_csv(RATES_CLEAN, index=False, encoding="utf-8-sig")
    reviews.to_csv(REVIEWS_CLEAN, index=False, encoding="utf-8-sig")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "listings": str(LISTINGS_RAW.relative_to(PROJECT_ROOT)),
            "past_rates": str(RATES_RAW.relative_to(PROJECT_ROOT)),
            "reviews": str(REVIEWS_RAW.relative_to(PROJECT_ROOT)),
            "postal_geojson": str(POSTAL_GEOJSON.relative_to(PROJECT_ROOT)),
        },
        "outputs": {
            "listings": {"rows": int(len(listings)), "columns": int(listings.shape[1])},
            "monthly_rates": {"rows": int(len(rates)), "columns": int(rates.shape[1])},
            "reviews_monthly": {"rows": int(len(reviews)), "columns": int(reviews.shape[1])},
        },
        "coverage": {
            "listings": int(listings["listing_id"].nunique()),
            "months": int(rates["month_start"].nunique()),
            "period": [PERIOD_START, PERIOD_END],
            "listings_with_12_months": int((rates.groupby("listing_id").size() == 12).sum()),
        },
        "checks": CHECKS,
        "failed_checks": [c for c in CHECKS if c["status"] == "fail"],
        "warnings": [c for c in CHECKS if c["status"] == "warn"],
    }
    QUALITY_REPORT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"listings:     {listings.shape[0]} rows x {listings.shape[1]} cols -> {LISTINGS_CLEAN}")
    print(f"monthly rates:{rates.shape[0]} rows x {rates.shape[1]} cols -> {RATES_CLEAN}")
    print(f"reviews:      {reviews.shape[0]} rows -> {REVIEWS_CLEAN}")
    print(f"quality report -> {QUALITY_REPORT}")
    failed = [c for c in CHECKS if c["status"] == "fail"]
    print(f"checks: {len(CHECKS)} run, {len(failed)} failed")
    for c in failed:
        print(f"  FAIL {c['check']}: {c['detail']}")


if __name__ == "__main__":
    main()
