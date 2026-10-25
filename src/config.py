"""Central configuration for the Querétaro Airbnb analysis.

All paths are resolved relative to the project root so the pipeline can run
from any working directory.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
SQL_DIR = PROJECT_ROOT / "sql"
REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
DB_PATH = PROJECT_ROOT / "airbnb_queretaro.db"

LISTINGS_RAW = RAW_DIR / "airroi_listings_2026-07.jsonl"
RATES_RAW = RAW_DIR / "airroi_past_rates_2026-07.jsonl"
REVIEWS_RAW = RAW_DIR / "airroi_reviews_2026-07.csv"
POSTAL_GEOJSON = RAW_DIR / "sepomex_cp_22-qro.geojson"

LISTINGS_CLEAN = PROCESSED_DIR / "listings.csv"
RATES_CLEAN = PROCESSED_DIR / "monthly_rates.csv"
REVIEWS_CLEAN = PROCESSED_DIR / "reviews_monthly.csv"
QUALITY_REPORT = PROCESSED_DIR / "data_quality.json"

# Plaza de Armas, Centro Histórico de Santiago de Querétaro (approximate).
CENTRO_LAT = 20.5931
CENTRO_LON = -100.3899

# Distance bands (km, straight-line) used as a reproducible location proxy.
# The data has no neighbourhood field; see data/README.md.
DISTANCE_BANDS = [
    (0.0, 1.0, "Centro (0-1 km)"),
    (1.0, 2.0, "Centro extendido (1-2 km)"),
    (2.0, 4.0, "Corona urbana (2-4 km)"),
    (4.0, 8.0, "Periferia (4-8 km)"),
    (8.0, 15.0, "Zona metropolitana (8-15 km)"),
    (15.0, float("inf"), "Exterior (>15 km)"),
]

# Listings beyond this radius are kept in the dataset but excluded from
# city-level comparisons (one rural farm stay, 47 km east of the centro).
CITY_CORE_RADIUS_KM = 15.0

# Analysis year window present in the AirROI 2026-07 release.
PERIOD_START = "2025-08-01"
PERIOD_END = "2026-07-01"

# Plot styling shared by every figure.
PALETTE = {
    "navy": "#1f3b57",
    "teal": "#2a9d8f",
    "sand": "#e9c46a",
    "orange": "#f4a261",
    "red": "#e76f51",
    "grey": "#8d99ae",
    "light": "#f4f1ec",
    "dark": "#2b2d42",
}

MONTH_LABELS_EN = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}
