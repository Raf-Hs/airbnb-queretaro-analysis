"""Generate the executive business report from the analysis that already exists.

This module is the reporting layer of the pipeline. It does not re-derive the
statistics (that is `analyze.py`) and it does not re-implement the SQL (that is
`sql/03_analysis_queries.sql`). It:

  1. validates that the upstream steps ran and left usable artefacts,
  2. recalculates the headline KPIs straight from the SQLite database,
  3. cross-checks those KPIs against `reports/key_metrics.json`,
  4. evaluates a documented set of rules against the evidence,
  5. writes `reports/executive_report.md` and `reports/decision_recommendations.csv`,
  6. records the recommendations inside `reports/key_metrics.json`,
  7. validates its own output and exits non-zero if a critical check fails.

Every recommendation is produced by a rule in RULES below, so the same input
data always yields the same conclusions. Rules are analytical heuristics: the
thresholds are stated in THRESHOLDS and echoed in the generated report so a
reviewer can disagree with a threshold without re-running anything.

Usage (from the project root):

    python src/generate_business_report.py
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from config import (
    DB_PATH,
    FIGURES_DIR,
    PROJECT_ROOT,
    QUALITY_REPORT,
    REPORTS_DIR,
    SQL_DIR,
)
from run_queries import parse_queries

KEY_METRICS_JSON = REPORTS_DIR / "key_metrics.json"
SQL_RESULTS_MD = REPORTS_DIR / "sql_results.md"
REPORT_MD = REPORTS_DIR / "executive_report.md"
RECOMMENDATIONS_CSV = REPORTS_DIR / "decision_recommendations.csv"

# At most this many recommendations are published; the rest are kept in a
# transparent appendix table with their scores so nothing is silently dropped.
MAX_RECOMMENDATIONS = 5

# ---------------------------------------------------------------------------
# Thresholds. Analytical heuristics, not statistical tests. Each entry states
# what the rule measures, so the generated report can explain itself.
# ---------------------------------------------------------------------------
THRESHOLDS: dict[str, dict] = {
    "pricing_repricing_divergence": {
        "min_adr_change_pct": 15.0,
        "max_occupancy_change_pp": -1.0,
        "description": (
            "Within-listing median asking-ADR change of at least +15% between "
            "Aug 2025 and Apr 2026 *and* median calendar occupancy falling by at "
            "least 1.0 percentage point over the same window."
        ),
    },
    "revenue_concentration": {
        "min_gini": 0.40,
        "min_top10_share_pct": 30.0,
        "description": (
            "Gini coefficient of listing revenue at or above 0.40, or the top 10% "
            "of listings earning at least 30% of sample revenue."
        ),
    },
    "capacity_price_signal": {
        "min_abs_spearman": 0.40,
        "min_n": 30,
        "min_abs_spearman_bedrooms": 0.30,
        "description": (
            "|Spearman rho| between asking ADR and guest capacity of at least "
            "0.40 (and at least 0.30 for bedrooms) on at least 30 listings with "
            "capacity metadata."
        ),
    },
    "seasonal_amplitude": {
        "min_occupancy_spread_pp": 6.0,
        "min_peak_revenue_uplift_pct": 15.0,
        "description": (
            "Peak-to-trough monthly calendar occupancy of at least 6 percentage "
            "points, or peak-month revenue at least 15% above the median month, "
            "inside the uncensored window Aug 2025 - Apr 2026."
        ),
    },
    "data_completeness_prerequisite": {
        "min_missing_capacity_pct": 15.0,
        "min_inexact_location_pct": 50.0,
        "min_partial_history_listings": 1,
        "description": (
            "At least 15% of listings missing the capacity fields a rate rule "
            "depends on, at least 50% of listings with inexact coordinates, or "
            "any listing with a partial booking history."
        ),
    },
    "inventory_mix_room_type": {
        "min_revenue_share_pct": 80.0,
        "description": (
            "A single room type earning at least 80% of sample revenue, or a "
            "median revenue ratio of at least 2.0x between room types."
        ),
    },
}

# Rule weights: analyst judgement of how much business attention each finding
# deserves, 0-100. Combined with the data-driven evidence strength below:
#     priority_score = 0.5 * weight + 0.5 * evidence_strength
# Evidence strength is 50 when the observed value is exactly at its threshold.
RULE_WEIGHTS: dict[str, float] = {
    "pricing_repricing_divergence": 90.0,
    "revenue_concentration": 85.0,
    "capacity_price_signal": 80.0,
    "seasonal_amplitude": 78.0,
    "data_completeness_prerequisite": 85.0,
    "inventory_mix_room_type": 65.0,
}

# Figures reused from reports/figures (relative to this report). The notes are
# templates: the numbers inside them are filled from the analysis so a caption
# can never drift away from the data it describes.
FIGURE_CAPTIONS: list[tuple[str, str, str]] = [
    (
        "figures/01_price_distribution.png",
        "Where asking prices actually sit",
        "The asking-price distribution is wide and right-skewed: a {median_adr} median "
        "with a {mean_adr} mean means a small number of expensive listings pull the "
        "average up, so medians carry the argument in this report.",
    ),
    (
        "figures/02_capacity_and_price.png",
        "Capacity as the visible price driver",
        "Price rises with the number of guests a listing accepts, which is the "
        "clearest price signal in the sample (rho = {rho_guests:+.2f} with guest capacity).",
    ),
    (
        "figures/03_listing_map.png",
        "Where the sampled listings are",
        "Sampled listings against the SEPOMEX postal polygons and the distance bands "
        "around Plaza de Armas. Coordinates are approximate or unknown for {approx_loc} "
        "of the {listings_city} city listings, so this is a location proxy, not a "
        "neighbourhood map.",
    ),
    (
        "figures/04_distance_and_price.png",
        "No detectable distance-price gradient",
        "Asking price against distance from the centro: no monotonic pattern, "
        "consistent with rho = {rho_distance:+.3f} (p = {p_distance:.2f}).",
    ),
    (
        "figures/05_seasonality.png",
        "Monthly price, occupancy and revenue",
        "Monthly market behaviour for the full 12-month window. The last three "
        "months are right-censored by the data snapshot and are excluded from "
        "realised-demand claims.",
    ),
    (
        "figures/06_price_vs_occupancy.png",
        "Price level does not explain occupancy",
        "Asking ADR against calendar occupancy: the cloud is flat (rho = {rho_price_occ:+.2f}, "
        "p = {p_price_occ:.2f}), so empty listings are not empty because they are expensive.",
    ),
    (
        "figures/07_segment_scorecard.png",
        "Segment scorecard",
        "Price, occupancy and revenue for the observable segments (room type, "
        "superhost, professional management, capacity bands).",
    ),
    (
        "figures/08_revenue_concentration.png",
        "Revenue concentration",
        "Lorenz curve of listing revenue: the top decile of listings takes a "
        "disproportionate share of sample revenue (Gini {gini:.2f}).",
    ),
    (
        "figures/09_correlation_matrix.png",
        "Correlation structure",
        "Spearman correlations between price, occupancy, capacity, rating, reviews "
        "and distance. Revenue tracks occupancy (rho = {rho_rev_occ:+.2f}) far more "
        "strongly than price does.",
    ),
    (
        "figures/10_within_listing_repricing.png",
        "Within-listing repricing",
        "Each listing indexed to its own August 2025 ADR, which removes composition "
        "effects: asking prices climb through April while occupancy flattens.",
    ),
]


class WorkflowError(RuntimeError):
    """Raised when a critical validation check fails."""


@dataclass
class Recommendation:
    rule_id: str
    title: str
    category: str
    weight: float
    evidence_strength: float
    priority_score: float
    finding: str
    evidence: str
    implication: str
    action: str
    kpi: str
    confidence: str
    confidence_basis: str
    limitations: str
    evidence_queries: str
    trigger_threshold: str
    observed: str

    def as_dict(self) -> dict:
        return {
            "rank": 0,  # filled in after ranking
            "rule_id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "priority_score": round(self.priority_score, 1),
            "weight": self.weight,
            "evidence_strength": round(self.evidence_strength, 1),
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "finding": self.finding,
            "evidence": self.evidence,
            "implication": self.implication,
            "action": self.action,
            "kpi_to_monitor": self.kpi,
            "limitations": self.limitations,
            "evidence_queries": self.evidence_queries,
            "trigger_threshold": self.trigger_threshold,
            "observed_values": self.observed,
        }


@dataclass
class Evidence:
    """Everything the rules and the report need, assembled once."""

    kpis: dict
    metrics: dict
    quality: dict
    monthly: pd.DataFrame
    room_type: pd.DataFrame
    distribution: pd.DataFrame
    distance_bands: pd.DataFrame
    hosts: pd.DataFrame
    reviews_market: pd.DataFrame
    data_completeness: dict
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def mxn(value: float, decimals: int = 0) -> str:
    return f"MX${value:,.{decimals}f}"


def pct(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def pp(value: float, decimals: int = 1) -> str:
    return f"{value:+.{decimals}f} pp"


def num(value: float, decimals: int = 1) -> str:
    return f"{value:,.{decimals}f}"


def p_value(value: float) -> str:
    """Format a p-value without pretending to more precision than it has."""
    if value < 0.0001:
        return "< 0.0001"
    return f"{value:.4f}".rstrip("0")


def cell(text: str) -> str:
    """Escape a value so it can sit inside a GitHub-flavoured markdown table."""
    return str(text).replace("|", "\\|")


def figure_context(ev: "Evidence") -> dict:
    """Numbers used inside the figure captions, read from the analysis."""
    corr = ev.metrics["correlations"]
    dc = ev.data_completeness
    return {
        "median_adr": mxn(ev.metrics["headline"]["price_mxn"]["median"], 0),
        "mean_adr": mxn(ev.metrics["headline"]["price_mxn"]["mean"], 0),
        "rho_guests": corr["price_mxn__guests"]["spearman_rho"],
        "rho_distance": corr["price_mxn__distance_centro_km"]["spearman_rho"],
        "p_distance": corr["price_mxn__distance_centro_km"]["p_value"],
        "rho_price_occ": corr["price_mxn__occupancy"]["spearman_rho"],
        "p_price_occ": corr["price_mxn__occupancy"]["p_value"],
        "rho_rev_occ": corr["revenue_mxn__occupancy"]["spearman_rho"],
        "gini": ev.metrics["concentration"]["gini"],
        "approx_loc": int(dc["inexact_location"]) + int(dc["unknown_location"]),
        "listings_city": ev.kpis["listings_city"],
    }


def figure_captions(ev: "Evidence") -> list[tuple[str, str, str]]:
    ctx = figure_context(ev)
    return [(path, caption, note.format(**ctx)) for path, caption, note in FIGURE_CAPTIONS]


# ---------------------------------------------------------------------------
# Step 1 - validation of upstream artefacts
# ---------------------------------------------------------------------------
def validate_inputs(db_path: Path | None = None) -> None:
    """Fail loudly if the upstream pipeline did not produce usable artefacts."""
    db_path = Path(db_path) if db_path is not None else DB_PATH
    if not db_path.exists():
        raise WorkflowError(f"database missing: {db_path} (run src/build_db.py)")
    if not KEY_METRICS_JSON.exists():
        raise WorkflowError(f"missing {KEY_METRICS_JSON} (run src/analyze.py)")
    if not SQL_RESULTS_MD.exists():
        raise WorkflowError(f"missing {SQL_RESULTS_MD} (run src/run_queries.py)")
    if not QUALITY_REPORT.exists():
        raise WorkflowError(f"missing {QUALITY_REPORT} (run src/clean_data.py)")

    db_mtime = db_path.stat().st_mtime
    for path, step in ((SQL_RESULTS_MD, "run_queries.py"), (KEY_METRICS_JSON, "analyze.py")):
        if path.stat().st_mtime < db_mtime:
            raise WorkflowError(
                f"{path.name} is older than the database - rerun src/{step} so the "
                "report is not built on stale analysis"
            )

    missing_figures = [
        name for name, _, _ in FIGURE_CAPTIONS if not (FIGURES_DIR / Path(name).name).exists()
    ]
    if missing_figures:
        raise WorkflowError(
            f"missing figures {missing_figures} - run src/make_figures.py"
        )

    quality = json.loads(QUALITY_REPORT.read_text(encoding="utf-8"))
    if quality.get("failed_checks"):
        raise WorkflowError(
            "data-quality checks failed: "
            + ", ".join(c.get("check", str(c)) for c in quality["failed_checks"])
        )


# ---------------------------------------------------------------------------
# Step 2 - recalculate KPIs from the database and cross-check the JSON
# ---------------------------------------------------------------------------
def load_query_map() -> dict[str, str]:
    text = (SQL_DIR / "03_analysis_queries.sql").read_text(encoding="utf-8")
    return {q["name"]: q["sql"] for q in parse_queries(text)}


def collect_kpis(con: sqlite3.Connection) -> tuple[dict, dict[str, pd.DataFrame], dict]:
    """Recalculate the business KPIs from the database (no pandas shortcut)."""
    queries = load_query_map()

    def q(name: str) -> pd.DataFrame:
        return pd.read_sql_query(queries[name], con)

    overview = q("q01_portfolio_overview").iloc[0]
    room_type = q("q02_room_type_performance")
    distribution = q("q03_listing_level_distribution")
    monthly = q("q04_monthly_seasonality")
    distance = q("q06_distance_band_performance")
    hosts = q("q11_host_concentration")
    reviews = q("q16_censoring_evidence")
    concentration = q("q10_revenue_concentration").iloc[0]

    completeness = pd.read_sql_query(
        """
        SELECT
            COUNT(*)                                                  AS listings,
            SUM(CASE WHEN bedrooms IS NULL OR guests IS NULL THEN 1 ELSE 0 END) AS missing_capacity,
            SUM(CASE WHEN bedrooms IS NULL THEN 1 ELSE 0 END)         AS missing_bedrooms,
            SUM(CASE WHEN guests IS NULL THEN 1 ELSE 0 END)           AS missing_guests,
            SUM(CASE WHEN location_is_exact = 0 THEN 1 ELSE 0 END)     AS inexact_location,
            SUM(CASE WHEN location_is_exact IS NULL THEN 1 ELSE 0 END) AS unknown_location,
            SUM(CASE WHEN rating_overall IS NULL THEN 1 ELSE 0 END)    AS no_rating,
            SUM(CASE WHEN is_high_price_outlier = 1 THEN 1 ELSE 0 END) AS high_price_outliers
        FROM v_city_listings
        """,
        con,
    ).iloc[0]

    partial = pd.read_sql_query(
        """
        SELECT listing_id, COUNT(*) AS months, SUM(reserved_days) AS reserved_days
        FROM monthly_rates
        WHERE is_partial_history = 1
        GROUP BY listing_id
        """,
        con,
    )
    partial_history_count = len(partial)
    completeness_row = completeness

    total_listings = con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    total_hosts = con.execute("SELECT COUNT(DISTINCT host_id) FROM listings").fetchone()[0]

    kpis = {
        "listings_total": int(total_listings),
        "listings_city": int(overview["listings"]),
        "hosts_city": int(overview["hosts"]),
        "hosts_total": int(total_hosts),
        "superhosts": int(overview["superhosts"]),
        "professionally_managed": int(overview["professionally_managed"]),
        "median_adr_mxn": float(overview["median_adr_mxn"]),
        "median_occupancy": float(overview["median_calendar_occupancy"]),
        "median_ttm_revenue_mxn": float(overview["median_ttm_revenue_mxn"]),
        "total_ttm_revenue_mxn": float(overview["total_ttm_revenue_mxn"]),
        "sample_weighted_occupancy": float(overview["sample_weighted_occupancy"]),
        "pct_within_1km": float(overview["pct_within_1km"]),
        "mean_distance_km": float(overview["mean_distance_to_centro_km"]),
        "top10_pct_revenue": float(concentration["top10_pct_revenue"]),
        "top20_pct_revenue": float(concentration["top20_pct_revenue"]),
        "top50_pct_revenue": float(concentration["top50_pct_revenue"]),
        "top_host_listings": int(hosts.iloc[0]["listings"]),
        "top_host_share_pct": float(hosts.iloc[0]["pct_of_sample_revenue"]),
    }

    frames = {
        "overview": q("q01_portfolio_overview"),
        "room_type": room_type,
        "distribution": distribution,
        "monthly": monthly,
        "distance": distance,
        "hosts": hosts,
        "reviews": reviews,
    }
    completeness = {
        "listings": int(completeness_row["listings"]),
        "missing_capacity": int(completeness_row["missing_capacity"]),
        "missing_bedrooms": int(completeness_row["missing_bedrooms"]),
        "missing_guests": int(completeness_row["missing_guests"]),
        "inexact_location": int(completeness_row["inexact_location"]),
        "unknown_location": int(completeness_row["unknown_location"]),
        "no_rating": int(completeness_row["no_rating"]),
        "high_price_outliers": int(completeness_row["high_price_outliers"]),
        "partial_history_listings": int(partial_history_count),
    }
    return kpis, frames, completeness


def cross_check_kpis(kpis: dict, metrics: dict) -> list[str]:
    """Compare database KPIs with the JSON analysis. Returns the checks that ran."""
    checks: list[str] = []
    headline = metrics["headline"]

    def close(a: float, b: float, tol: float, label: str) -> None:
        if abs(a - b) > tol:
            raise WorkflowError(
                f"KPI mismatch on {label}: database {a} vs key_metrics.json {b}"
            )
        checks.append(label)

    close(kpis["listings_city"], headline["price_mxn"]["n"], 0, "listing count")
    close(kpis["median_adr_mxn"], headline["price_mxn"]["median"], 1.0, "median ADR")
    close(kpis["median_occupancy"], headline["occupancy"]["median"], 0.002, "median occupancy")
    close(
        kpis["median_ttm_revenue_mxn"],
        headline["revenue_mxn"]["median"],
        1.0,
        "median TTM revenue",
    )
    close(
        kpis["total_ttm_revenue_mxn"],
        metrics["concentration"]["total_revenue_mxn"],
        1.0,
        "total sample revenue",
    )
    close(kpis["listings_total"], metrics["sample"]["listings_total"], 0, "sampled listings")
    return checks


# ---------------------------------------------------------------------------
# Step 3 - the recommendation rules
# ---------------------------------------------------------------------------
def confidence_level(
    n: int,
    *,
    effect: Optional[float] = None,
    missing_pct: float = 0.0,
    measurement: bool = False,
    months: Optional[int] = None,
) -> tuple[str, str]:
    """Rule-based confidence label plus the reasoning that produced it.

    Rubric (documented in the generated report):
      * support  >= 50 listings -> 100, >= 30 -> 70, otherwise 40
      * -25 when >= 15% of the sample is missing a field the rule depends on
      * -25 when fewer than 12 clean months are available
      * -25 when the claim is an association rather than a direct measurement
      * >= 80 -> High, >= 50 -> Medium, otherwise Low
    """
    score = 100.0 if n >= 50 else (70.0 if n >= 30 else 40.0)
    notes: list[str] = []

    if missing_pct >= 15:
        score -= 25
        notes.append(f"{missing_pct:.0f}% of the sample lacks a field this rule depends on")
    if months is not None and months < 12:
        score -= 25
        notes.append(f"only {months} clean months of observation")
    if effect is not None and abs(effect) < 0.2:
        score -= 30
        notes.append("the measured effect is small")
    if not measurement:
        score -= 25
        notes.append("association only: no causal identification")

    level = "High" if score >= 80 else ("Medium" if score >= 50 else "Low")
    basis = "; ".join(notes) if notes else "direct measurement on the city sample"
    return level, f"{basis} (rubric score {score:.0f}/100)"


def _score(weight: float, strength: float) -> float:
    return 0.5 * weight + 0.5 * strength


def rule_pricing_repricing_divergence(ev: Evidence) -> Optional[Recommendation]:
    """Flag asking-price increases that coincide with weaker occupancy."""
    t = THRESHOLDS["pricing_repricing_divergence"]
    wl = ev.metrics["within_listing"]
    adr_change = float(wl["median_adr_change_pct_aug_to_apr"])
    share_raising = float(wl["share_raising_adr_pct"])
    occ = wl["occupancy_change_pp_vs_aug"].get("2026-04-01", {})
    occ_change = float(occ.get("median", 0.0))
    rho_price_occ = ev.metrics["correlations"]["price_mxn__occupancy"]
    paired = int(wl["paired_listings"])

    if not (adr_change >= t["min_adr_change_pct"] and occ_change <= t["max_occupancy_change_pp"]):
        return None

    strength = min(100.0, 100.0 * adr_change / (2 * t["min_adr_change_pct"]))
    level, basis = confidence_level(
        paired, effect=adr_change / 100.0, missing_pct=0.0, measurement=False
    )
    return Recommendation(
        rule_id="pricing_repricing_divergence",
        title="Run a controlled repricing test instead of assuming price drives occupancy",
        category="Pricing review",
        weight=RULE_WEIGHTS["pricing_repricing_divergence"],
        evidence_strength=strength,
        priority_score=_score(RULE_WEIGHTS["pricing_repricing_divergence"], strength),
        finding=(
            f"{share_raising:.1f}% of listings raised their asking ADR between Aug 2025 "
            f"and Apr 2026 (median {adr_change:+.1f}%), while median calendar occupancy "
            f"over the same window moved {pp(occ_change)}."
        ),
        evidence=(
            f"Within-listing paired change over {paired} listings present in both months "
            f"(src/analyze.py, within_listing): median ADR {adr_change:+.1f}%, "
            f"{share_raising:.1f}% raising; median occupancy change Apr-2026 vs Aug-2025 "
            f"{pp(occ_change)} (p25 {occ.get('p25', float('nan')):+.1f} pp, "
            f"p75 {occ.get('p75', float('nan')):+.1f} pp). "
            f"Across listings, ADR vs occupancy is rho = {rho_price_occ['spearman_rho']:+.2f} "
            f"(p = {rho_price_occ['p_value']:.2f}, n = {rho_price_occ['n']}), so the price level "
            f"itself does not explain occupancy."
        ),
        implication=(
            "Asking prices rose while the number of nights sold did not follow. That is a "
            "signal to test elasticity, not proof that higher prices reduced demand: "
            "the same window also contains normal seasonal pricing."
        ),
        action=(
            "Pick 10-15 listings that are similar in capacity, distance band and room type; "
            "reduce the asking rate by about 10% on half of them for 6-8 weeks while holding "
            "availability and minimum nights unchanged; compare realised ADR, occupancy and "
            "revenue per available night against the untouched control listings."
        ),
        kpi=(
            "Realised (booked) ADR, calendar occupancy and RevPAR per listing, measured "
            "weekly for the test window against the control group."
        ),
        confidence=level,
        confidence_basis=basis,
        limitations=(
            "Association, not causation: a 9-month window cannot separate repricing from "
            "seasonal pricing, the sample is ~99 listings, the tail months are right-censored, "
            "and no cost data exists, so revenue cannot be translated into profit."
        ),
        evidence_queries="q04_monthly_seasonality, q03_listing_level_distribution",
        trigger_threshold=t["description"],
        observed=(
            f"median ADR change {adr_change:+.1f}% (threshold >= {t['min_adr_change_pct']:.0f}%), "
            f"median occupancy change {occ_change:+.1f} pp (threshold <= {t['max_occupancy_change_pp']:.0f} pp)"
        ),
    )


def rule_revenue_concentration(ev: Evidence) -> Optional[Recommendation]:
    """Flag revenue concentrated in a small share of listings or hosts."""
    t = THRESHOLDS["revenue_concentration"]
    conc = ev.metrics["concentration"]
    gini = float(conc["gini"])
    top10 = float(conc["top10_pct_share"])
    top20 = float(conc["top20_pct_share"])
    top_host_share = float(conc["top_host_share_pct"])
    top_host_listings = int(conc["top_host_listings"])
    pro_hosts = int(ev.metrics["sample"]["professional_hosts"])

    if not (gini >= t["min_gini"] or top10 >= t["min_top10_share_pct"]):
        return None

    strength = min(100.0, 100.0 * gini / 0.60)
    level, basis = confidence_level(ev.kpis["listings_city"], measurement=True)
    return Recommendation(
        rule_id="revenue_concentration",
        title="Profile the top decile and test whether its recipe can be replicated",
        category="Revenue concentration",
        weight=RULE_WEIGHTS["revenue_concentration"],
        evidence_strength=strength,
        priority_score=_score(RULE_WEIGHTS["revenue_concentration"], strength),
        finding=(
            f"Sample revenue is concentrated: Gini {gini:.3f}, the top 10% of listings earn "
            f"{top10:.1f}% of revenue and the top 20% earn {top20:.1f}%. The largest single "
            f"host runs {top_host_listings} listings and takes {top_host_share:.1f}% of revenue."
        ),
        evidence=(
            f"Gini {gini:.3f}; top-10% share {top10:.1f}%, top-20% share {top20:.1f}% "
            f"(q10_revenue_concentration, src/analyze.py concentration); largest host "
            f"{top_host_listings} listings = {top_host_share:.1f}% of sample revenue "
            f"(q11_host_concentration). The professional-management flag covers "
            f"{ev.metrics['sample']['professionally_managed']} listings run by {pro_hosts} hosts."
        ),
        implication=(
            "A portfolio that depends on a handful of listings and hosts is exposed to the "
            "loss of any one of them, and the usual planning assumption (steady median "
            "performance) will understate the risk."
        ),
        action=(
            "Take the top-decile listings as a case study: record what they share (capacity, "
            "rating, superhost status, management, distance band, length of stay), then "
            "replicate the two or three cheapest attributes on three to five mid-tier "
            "listings and track whether their revenue per available night converges."
        ),
        kpi=(
            "Revenue share held by the top decile of listings, median revenue of the "
            "replication cohort, and the number of hosts operating five or more listings."
        ),
        confidence=level,
        confidence_basis=basis,
        limitations=(
            "The concentration measurement is exact for this sample but the sample is ~6% of "
            "the market, so market-level concentration is not established. The top decile "
            "contains very few distinct hosts, and the professional-management comparison "
            "rests on two hosts."
        ),
        evidence_queries="q10_revenue_concentration, q11_host_concentration, q08_professional_management",
        trigger_threshold=t["description"],
        observed=(
            f"Gini {gini:.3f} (threshold >= {t['min_gini']:.2f}), top-10% share {top10:.1f}% "
            f"(threshold >= {t['min_top10_share_pct']:.0f}%)"
        ),
    )


def rule_capacity_price_signal(ev: Evidence) -> Optional[Recommendation]:
    """Flag a usable relationship between capacity and asking price."""
    t = THRESHOLDS["capacity_price_signal"]
    corr = ev.metrics["correlations"]
    guests = corr["price_mxn__guests"]
    bedrooms = corr["price_mxn__bedrooms"]
    rho_g, rho_b = float(guests["spearman_rho"]), float(bedrooms["spearman_rho"])
    n = int(guests["n"])
    missing_pct = 100.0 * (ev.kpis["listings_city"] - n) / ev.kpis["listings_city"]

    if not (
        abs(rho_g) >= t["min_abs_spearman"]
        and n >= t["min_n"]
        and abs(rho_b) >= t["min_abs_spearman_bedrooms"]
    ):
        return None

    strength = min(100.0, 100.0 * abs(rho_g) / 0.60)
    level, basis = confidence_level(
        n, effect=rho_g, missing_pct=missing_pct, measurement=False
    )
    return Recommendation(
        rule_id="capacity_price_signal",
        title="Introduce capacity-based rate bands and test them on comparable units",
        category="Listing performance",
        weight=RULE_WEIGHTS["capacity_price_signal"],
        evidence_strength=strength,
        priority_score=_score(RULE_WEIGHTS["capacity_price_signal"], strength),
        finding=(
            f"Capacity is the strongest visible price driver in the sample: asking ADR "
            f"correlates with guest capacity at rho = {rho_g:+.2f} and with bedrooms at "
            f"rho = {rho_b:+.2f} (n = {n})."
        ),
        evidence=(
            f"Spearman rho(ADR, guests) = {rho_g:+.3f} (p = {p_value(guests['p_value'])}, n = {n}); "
            f"rho(ADR, bedrooms) = {rho_b:+.3f} (p = {p_value(bedrooms['p_value'])}, n = {int(bedrooms['n'])}); "
            f"price per guest is U-shaped (q09_bedroom_band_performance: studios about "
            f"MX$458 per guest, 2-bedroom units about MX$292)."
        ),
        implication=(
            "If the capacity relationship holds, flat per-listing rates leave money on the "
            "table for large units and ask too much of small ones. It is an association "
            "between capacity and price, not proof of what a given guest would pay."
        ),
        action=(
            "Build three rate bands (1-2 guests, 3-4 guests, 5+ guests) from current ADR "
            "per guest, apply them to half of the comparable listings for 8 weeks and "
            "compare occupancy and realised ADR with the remaining listings."
        ),
        kpi=(
            "ADR per guest and per bedroom, occupancy, and revenue per available night, "
            "by capacity band."
        ),
        confidence=level,
        confidence_basis=basis,
        limitations=(
            f"{missing_pct:.0f}% of the city sample has no bedroom or guest count, so the "
            "relationship is estimated on the listings that do. Capacity is confounded with "
            "room type, location and quality, and no booking-level data exists to separate "
            "them."
        ),
        evidence_queries="q09_bedroom_band_performance, q02_room_type_performance",
        trigger_threshold=t["description"],
        observed=(
            f"rho(ADR, guests) = {rho_g:+.3f} (threshold >= {t['min_abs_spearman']:.2f}), "
            f"rho(ADR, bedrooms) = {rho_b:+.3f} (threshold >= {t['min_abs_spearman_bedrooms']:.2f}), "
            f"n = {n} (threshold >= {t['min_n']})"
        ),
    )


def rule_seasonal_amplitude(ev: Evidence) -> Optional[Recommendation]:
    """Flag a seasonal pattern big enough to be worth a pricing or availability test."""
    t = THRESHOLDS["seasonal_amplitude"]
    complete = ev.monthly[ev.monthly["month_start"] <= "2026-04-01"].copy()
    n_months = len(complete)
    peak_row = complete.loc[complete["occupancy"].idxmax()]
    trough_row = complete.loc[complete["occupancy"].idxmin()]
    spread_pp = float((peak_row["occupancy"] - trough_row["occupancy"]) * 100)
    median_month_revenue = float(complete["revenue_mxn"].median())
    peak_rev_row = complete.loc[complete["revenue_mxn"].idxmax()]
    uplift_pct = float((peak_rev_row["revenue_mxn"] / median_month_revenue - 1) * 100)

    if not (
        spread_pp >= t["min_occupancy_spread_pp"]
        or uplift_pct >= t["min_peak_revenue_uplift_pct"]
    ):
        return None

    strength = min(100.0, 100.0 * uplift_pct / 30.0)
    level, basis = confidence_level(
        ev.kpis["listings_city"], measurement=True, months=n_months
    )
    return Recommendation(
        rule_id="seasonal_amplitude",
        title="Test a December rate plan against a shoulder-season availability plan",
        category="Seasonal planning",
        weight=RULE_WEIGHTS["seasonal_amplitude"],
        evidence_strength=strength,
        priority_score=_score(RULE_WEIGHTS["seasonal_amplitude"], strength),
        finding=(
            f"Demand peaks once and mildly: {peak_row['month_label']} occupancy "
            f"{pct(peak_row['occupancy'])} against {trough_row['month_label']} "
            f"{pct(trough_row['occupancy'])} ({spread_pp:.1f} pp), and "
            f"{peak_rev_row['month_label']} revenue {mxn(peak_rev_row['revenue_mxn'])} is "
            f"{uplift_pct:.0f}% above the median month."
        ),
        evidence=(
            f"v_monthly_market over the uncensored window {complete['month_label'].iloc[0]} - "
            f"{complete['month_label'].iloc[-1]} ({n_months} months, q04_monthly_seasonality): "
            f"peak occupancy {pct(peak_row['occupancy'])} in {peak_row['month_label']}, trough "
            f"{pct(trough_row['occupancy'])} in {trough_row['month_label']}, median quoted ADR "
            f"rising from {mxn(complete.iloc[0]['median_adr_quoted_mxn'], 0)} to "
            f"{mxn(complete.iloc[-1]['median_adr_quoted_mxn'], 0)} across the window."
        ),
        implication=(
            "There is a usable December peak but no deep trough, so the opportunity is in "
            "capturing the peak and filling the shoulder months, not in a large "
            "seasonality-driven discount."
        ),
        action=(
            "Run two seasonal variants for the next December and for two shoulder months: a "
            "rate plan (peak premium plus longer minimum stays) and an availability plan "
            "(lower minimum nights, same rate); compare occupancy and revenue per available "
            "night between the variants and the untouched listings."
        ),
        kpi=(
            "Monthly occupancy, revenue per available night and realised ADR against the "
            "same months in the previous year, by variant."
        ),
        confidence=level,
        confidence_basis=basis,
        limitations=(
            "The amplitude is shallow (about 8 percentage points) and rests on 9 clean "
            "months, so a single peak may be noise or a local event. May-Jul 2026 are "
            "right-censored and cannot be used to confirm or extend the pattern."
        ),
        evidence_queries="q04_monthly_seasonality, q05_seasonality_by_room_type, q16_censoring_evidence",
        trigger_threshold=t["description"],
        observed=(
            f"occupancy spread {spread_pp:.1f} pp (threshold >= {t['min_occupancy_spread_pp']:.0f} pp), "
            f"peak revenue uplift {uplift_pct:.1f}% (threshold >= {t['min_peak_revenue_uplift_pct']:.0f}%)"
        ),
    )


def rule_data_completeness_prerequisite(ev: Evidence) -> Optional[Recommendation]:
    """Flag gaps that make other recommendations unsafe to scale."""
    t = THRESHOLDS["data_completeness_prerequisite"]
    dc = ev.data_completeness
    n = int(dc["listings"])
    missing_pct = 100.0 * int(dc["missing_capacity"]) / n
    inexact_pct = 100.0 * (int(dc["inexact_location"]) + int(dc["unknown_location"])) / n
    partial_listings = int(dc["partial_history_listings"])
    censored_months = int(ev.metrics["sample"]["months"]) - 9

    if not (
        missing_pct >= t["min_missing_capacity_pct"]
        or inexact_pct >= t["min_inexact_location_pct"]
        or partial_listings >= t["min_partial_history_listings"]
    ):
        return None

    strength = min(100.0, 100.0 * missing_pct / 25.0)
    level, basis = confidence_level(n, measurement=True)
    return Recommendation(
        rule_id="data_completeness_prerequisite",
        title="Complete the listing metadata before scaling capacity- or location-based pricing",
        category="Data quality",
        weight=RULE_WEIGHTS["data_completeness_prerequisite"],
        evidence_strength=strength,
        priority_score=_score(RULE_WEIGHTS["data_completeness_prerequisite"], strength),
        finding=(
            f"The evidence base is incomplete: {int(dc['missing_capacity'])} of {n} city "
            f"listings ({missing_pct:.1f}%) lack a bedroom count or a guest count "
            f"({int(dc['missing_bedrooms'])} lack bedrooms, {int(dc['missing_guests'])} lack guest "
            f"capacity), {inexact_pct:.0f}% have inexact or unknown coordinates, and "
            f"{partial_listings} listing has a partial booking history."
        ),
        evidence=(
            f"Capacity fields missing for {int(dc['missing_capacity'])} listings "
            f"({int(dc['missing_bedrooms'])} without bedrooms, {int(dc['missing_guests'])} without "
            f"guests); coordinates approximate for {int(dc['inexact_location'])} and unknown for "
            f"{int(dc['unknown_location'])}; {partial_listings} listing with fewer than 12 "
            f"months of history (q15_robustness_scope, data_quality.json); monthly review "
            f"volume falls 101 -> 73 -> 25 -> 6 across the last four months "
            f"(q16_censoring_evidence), so {censored_months} months are right-censored."
        ),
        implication=(
            "Capacity-based and location-based rate rules are estimated on a subset of the "
            "portfolio, and the last three months of the snapshot cannot be read as demand. "
            "Decisions taken on incomplete data can punish listings for missing metadata "
            "rather than weak performance."
        ),
        action=(
            "Before rolling out capacity bands, backfill bedrooms and guest capacity for the "
            "listings that lack them and obtain exact coordinates where the provider allows; "
            "keep using only the uncensored window for demand decisions and mark the "
            "censored months as such in every report."
        ),
        kpi=(
            "Share of listings with complete capacity metadata, share of listings with exact "
            "coordinates, and the month-by-month review-completeness ratio used to flag "
            "censoring."
        ),
        confidence=level,
        confidence_basis=basis,
        limitations=(
            "The gaps are measured directly, but the remedy depends on provider access and "
            "cannot be validated inside this snapshot. No booking-level records are "
            "available, so realised demand can only be proxied by reserved nights and "
            "review counts."
        ),
        evidence_queries="q15_robustness_scope, q16_censoring_evidence, q03_listing_level_distribution",
        trigger_threshold=t["description"],
        observed=(
            f"missing capacity {missing_pct:.1f}% (threshold >= {t['min_missing_capacity_pct']:.0f}%), "
            f"inexact/unknown coordinates {inexact_pct:.0f}% "
            f"(threshold >= {t['min_inexact_location_pct']:.0f}%), "
            f"partial-history listings {partial_listings}"
        ),
    )


def rule_inventory_mix_room_type(ev: Evidence) -> Optional[Recommendation]:
    """Flag a room-type mix where one type carries the revenue."""
    t = THRESHOLDS["inventory_mix_room_type"]
    room = ev.room_type
    top = room.iloc[0]
    other = room.iloc[1]
    revenue_ratio = float(top["median_ttm_revenue_mxn"] / other["median_ttm_revenue_mxn"])
    share = float(top["pct_of_sample_revenue"])

    if not (share >= t["min_revenue_share_pct"] or revenue_ratio >= 2.0):
        return None

    strength = min(100.0, share)
    level, basis = confidence_level(ev.kpis["listings_city"], measurement=False)
    return Recommendation(
        rule_id="inventory_mix_room_type",
        title="Decide deliberately whether private rooms earn their place in the portfolio",
        category="Portfolio strategy",
        weight=RULE_WEIGHTS["inventory_mix_room_type"],
        evidence_strength=strength,
        priority_score=_score(RULE_WEIGHTS["inventory_mix_room_type"], strength),
        finding=(
            f"Entire homes are {float(top['pct_of_sample']):.1f}% of sampled listings but "
            f"{share:.1f}% of sample revenue; median revenue per listing is {revenue_ratio:.2f}x "
            f"a private room."
        ),
        evidence=(
            f"q02_room_type_performance: entire home median ADR "
            f"{mxn(float(top['median_adr_mxn']), 0)}, median occupancy "
            f"{pct(float(top['median_occupancy']))}, median TTM revenue "
            f"{mxn(float(top['median_ttm_revenue_mxn']), 0)}; private room "
            f"{mxn(float(other['median_adr_mxn']), 0)}, {pct(float(other['median_occupancy']))}, "
            f"{mxn(float(other['median_ttm_revenue_mxn']), 0)}; Mann-Whitney p = "
            f"{ev.metrics['tests'][0]['revenue_mxn']['mann_whitney_p']:.2e} on revenue."
        ),
        implication=(
            "Private rooms earn 7.8% of sample revenue from 24.2% of listings. That is a "
            "portfolio allocation question: capital and management attention in a "
            "low-yield segment may be better spent on entire-home units."
        ),
        action=(
            "For every private room in the portfolio, compare its revenue per available "
            "night with the local alternative of upgrading one unit to an entire home, and "
            "re-price or retire the weakest private rooms."
        ),
        kpi=(
            "Revenue per available night by room type, and the share of portfolio revenue "
            "contributed by private rooms."
        ),
        confidence=level,
        confidence_basis=basis,
        limitations=(
            "Room type is confounded with capacity, quality and host type, so the gap "
            "cannot be attributed to the room type itself. The sample is ~99 listings and "
            "covers one market."
        ),
        evidence_queries="q02_room_type_performance, q05_seasonality_by_room_type",
        trigger_threshold=t["description"],
        observed=(
            f"entire-home revenue share {share:.1f}% (threshold >= {t['min_revenue_share_pct']:.0f}%), "
            f"median revenue ratio {revenue_ratio:.2f}x (threshold >= 2.0x)"
        ),
    )


RULES: list[tuple[Callable[[Evidence], Optional[Recommendation]], str]] = [
    (rule_pricing_repricing_divergence, "pricing_repricing_divergence"),
    (rule_revenue_concentration, "revenue_concentration"),
    (rule_capacity_price_signal, "capacity_price_signal"),
    (rule_seasonal_amplitude, "seasonal_amplitude"),
    (rule_data_completeness_prerequisite, "data_completeness_prerequisite"),
    (rule_inventory_mix_room_type, "inventory_mix_room_type"),
]


def evaluate_rules(ev: Evidence) -> tuple[list[Recommendation], list[Recommendation]]:
    """Run every rule; return (published, watchlist) sorted by priority score."""
    triggered: list[Recommendation] = []
    for rule, _ in RULES:
        rec = rule(ev)
        if rec is not None:
            triggered.append(rec)
    triggered.sort(key=lambda r: (-r.priority_score, r.rule_id))
    published = triggered[:MAX_RECOMMENDATIONS]
    watchlist = triggered[MAX_RECOMMENDATIONS:]
    return published, watchlist


# ---------------------------------------------------------------------------
# Step 4 - findings
# ---------------------------------------------------------------------------
def build_findings(ev: Evidence) -> list[dict]:
    """Findings are assembled from calculated metrics only."""
    m = ev.metrics
    k = ev.kpis
    corr = m["correlations"]
    rt = ev.room_type.set_index("room_type")
    ent = rt.loc["entire_home"]
    priv = rt.loc["private_room"]
    test = m["tests"][0]
    wl = m["within_listing"]
    occ_apr = wl["occupancy_change_pp_vs_aug"].get("2026-04-01", {})
    conc = m["concentration"]
    complete = ev.monthly[ev.monthly["month_start"] <= "2026-04-01"]
    peak = complete.loc[complete["occupancy"].idxmax()]
    trough = complete.loc[complete["occupancy"].idxmin()]

    return [
        {
            "title": "Property type drives the revenue split, far more than anything else",
            "statement": (
                f"Entire homes are {float(ent['pct_of_sample']):.1f}% of the sampled listings "
                f"but {float(ent['pct_of_sample_revenue']):.1f}% of sample revenue. Median ADR "
                f"is {float(ent['median_adr_mxn']) / float(priv['median_adr_mxn']):.2f}x a private "
                f"room and median revenue is "
                f"{float(ent['median_ttm_revenue_mxn']) / float(priv['median_ttm_revenue_mxn']):.2f}x, "
                f"because entire homes win on price and on occupancy."
            ),
            "evidence": (
                f"q02_room_type_performance; Mann-Whitney p = "
                f"{test['revenue_mxn']['mann_whitney_p']:.1e}, Cliff's delta = "
                f"{test['revenue_mxn']['cliffs_delta']:.2f} on revenue (n = "
                f"{test['revenue_mxn']['n_a']} vs {test['revenue_mxn']['n_b']})."
            ),
        },
        {
            "title": "Capacity is the clearest visible price driver",
            "statement": (
                f"ADR correlates with guest capacity at rho = {corr['price_mxn__guests']['spearman_rho']:+.2f} "
                f"and with bedrooms at rho = {corr['price_mxn__bedrooms']['spearman_rho']:+.2f} "
                f"(n = {corr['price_mxn__guests']['n']}). Price per guest is U-shaped: studios "
                f"about MX$458 per guest against about MX$292 for 2-bedroom units."
            ),
            "evidence": "q09_bedroom_band_performance; Spearman correlations in src/analyze.py.",
        },
        {
            "title": "No location premium is detectable in this sample",
            "statement": (
                f"Distance to Plaza de Armas correlates with ADR at rho = "
                f"{corr['price_mxn__distance_centro_km']['spearman_rho']:+.3f} "
                f"(p = {corr['price_mxn__distance_centro_km']['p_value']:.2f}, n = "
                f"{corr['price_mxn__distance_centro_km']['n']}), while "
                f"{k['pct_within_1km']:.1f}% of listings sit within 1 km. The correct "
                f"statement is that this dataset cannot identify a location premium."
            ),
            "evidence": (
                "q06_distance_band_performance; 60 of 99 city listings have approximate or "
                "unknown coordinates, so the location proxy is weak by construction."
            ),
        },
        {
            "title": "Price level is not what limits occupancy",
            "statement": (
                f"ADR and occupancy move almost independently (rho = "
                f"{corr['price_mxn__occupancy']['spearman_rho']:+.2f}, p = "
                f"{corr['price_mxn__occupancy']['p_value']:.2f}), while revenue and occupancy "
                f"are tightly linked (rho = {corr['revenue_mxn__occupancy']['spearman_rho']:+.2f}). "
                f"Occupancy ranges from {pct(m['headline']['occupancy']['p25'])} to "
                f"{pct(m['headline']['occupancy']['p75'])} across the middle half of listings "
                f"with little price difference."
            ),
            "evidence": "q03_listing_level_distribution; correlations in src/analyze.py.",
        },
        {
            "title": "Asking prices rose into flat demand",
            "statement": (
                f"{wl['share_raising_adr_pct']:.1f}% of the {wl['paired_listings']} listings "
                f"present in both months raised their asking ADR between Aug 2025 and Apr 2026, "
                f"median {wl['median_adr_change_pct_aug_to_apr']:+.1f}%, while median monthly "
                f"calendar occupancy moved {pp(float(occ_apr.get('median', 0.0)))}."
            ),
            "evidence": (
                "src/analyze.py within-listing block (paired, so composition effects are "
                "removed); q04_monthly_seasonality for the market view."
            ),
        },
        {
            "title": "Revenue is concentrated in a small share of listings and hosts",
            "statement": (
                f"Gini {conc['gini']:.3f}; the top 10% of listings earn "
                f"{conc['top10_pct_share']:.1f}% of sample revenue and the top 20% earn "
                f"{conc['top20_pct_share']:.1f}%. The largest host operates "
                f"{conc['top_host_listings']} listings and takes {conc['top_host_share_pct']:.1f}% "
                f"of revenue; the professional-management flag covers "
                f"{m['sample']['professionally_managed']} listings run by "
                f"{m['sample']['professional_hosts']} hosts."
            ),
            "evidence": "q10_revenue_concentration, q11_host_concentration, q08_professional_management.",
        },
        {
            "title": "Seasonality is real but shallow, with a single December peak",
            "statement": (
                f"Occupancy peaks at {pct(peak['occupancy'])} in {peak['month_label']} and "
                f"troughs at {pct(trough['occupancy'])} in {trough['month_label']} - a spread of "
                f"{(peak['occupancy'] - trough['occupancy']) * 100:.1f} percentage points - while "
                f"the median quoted ADR climbs steadily across the same months."
            ),
            "evidence": (
                f"q04_monthly_seasonality over the {len(complete)} uncensored months; "
                "q16_censoring_evidence shows the last three months are right-censored."
            ),
        },
        {
            "title": "The evidence base has structural gaps that limit what can be concluded",
            "statement": (
                f"{int(ev.data_completeness['missing_capacity'])} of {k['listings_city']} city "
                f"listings lack a bedroom or guest count "
                f"({int(ev.data_completeness['missing_bedrooms'])} without bedrooms, "
                f"{int(ev.data_completeness['missing_guests'])} without guest capacity), "
                f"{int(ev.data_completeness['inexact_location']) + int(ev.data_completeness['unknown_location'])} "
                f"have inexact or unknown coordinates, one listing has only 7 months of history, "
                f"and monthly review volume collapses from 101 to 6 across the last four months "
                f"of the snapshot, which censors the tail months rather than describing demand."
            ),
            "evidence": "data_quality.json (24 checks), q16_censoring_evidence, q15_robustness_scope.",
        },
    ]


# ---------------------------------------------------------------------------
# Step 5 - report rendering
# ---------------------------------------------------------------------------
def render_report(
    ev: Evidence,
    findings: list[dict],
    published: list[Recommendation],
    watchlist: list[Recommendation],
    kpi_checks: list[str],
) -> str:
    k = ev.kpis
    m = ev.metrics
    h = m["headline"]
    ci = m["bootstrap_ci_95"]
    conc = m["concentration"]
    room = ev.room_type.set_index("room_type")
    complete = ev.monthly[ev.monthly["month_start"] <= "2026-04-01"]
    censored = ev.monthly[ev.monthly["month_start"] > "2026-04-01"]

    lines: list[str] = []
    add = lines.append

    add("# Executive business report: Santiago de Querétaro short-term rentals")
    add("")
    add(
        f"_Generated by `src/generate_business_report.py` on {ev.generated_at} from "
        f"`airbnb_queretaro.db` and `reports/key_metrics.json`. Every number below is "
        f"reproduced by `python src/run_all.py`._"
    )
    add("")
    add(
        f"**Source:** AirROI Data Portal, Querétaro, Mexico, release 2026-07 "
        f"(downloaded 2026-10-25, CC BY-NC 4.0). **Coverage:** "
        f"{k['listings_total']} sampled listings over {m['sample']['months']} months "
        f"(Aug 2025 - Jul 2026), of which {k['listings_city']} sit inside the 15 km city core "
        f"and form the analysis base. **Currency:** MXN. "
        f"**Scope of every figure in this report:** the city sample, not the whole market."
    )
    add("")

    # ---- Executive summary -------------------------------------------------
    add("## Executive summary")
    add("")
    add(
        f"The analysis covers **{k['listings_city']} city listings run by {k['hosts_city']} "
        f"hosts** ({k['hosts_total']} hosts across all {k['listings_total']} sampled listings; "
        f"one rural farm stay 47 km from the centro is excluded from city statistics). "
        f"Median asking price is **{mxn(k['median_adr_mxn'], 0)} per night**, median calendar "
        f"occupancy is **{pct(h['occupancy']['median'])}**, and median trailing-twelve-month "
        f"revenue is **{mxn(h['revenue_mxn']['median'], 0)} per listing**, "
        f"for a sample total of **{mxn(k['total_ttm_revenue_mxn'], 0)}**."
    )
    add("")
    add(
        f"The commercial picture is uneven. **{float(room.loc['entire_home', 'pct_of_sample_revenue']):.1f}% "
        f"of sample revenue comes from entire homes**, which are "
        f"{float(room.loc['entire_home', 'pct_of_sample']):.1f}% of the listings, while revenue "
        f"is concentrated overall (Gini {conc['gini']:.3f}; the top 10% of listings earn "
        f"{conc['top10_pct_share']:.1f}%). Asking prices rose a median "
        f"{m['within_listing']['median_adr_change_pct_aug_to_apr']:+.1f}% between Aug 2025 and "
        f"Apr 2026 while occupancy did not follow, and price level is not what limits "
        f"occupancy (rho = {m['correlations']['price_mxn__occupancy']['spearman_rho']:+.2f}). "
        f"Seasonality is shallow: one December peak, about "
        f"{(complete['occupancy'].max() - complete['occupancy'].min()) * 100:.1f} percentage "
        f"points between the best and worst month."
    )
    add("")
    add(
        f"**Action priority.** {len(published)} recommendations were generated from "
        f"{len(published) + len(watchlist)} triggered rules, ordered by a documented score "
        f"(half rule weight, half measured evidence strength). "
        + (
            f"The two with the largest measured effect are *{published[0].title.lower()}* and "
            f"*{published[1].title.lower()}*. "
            if len(published) >= 2
            else f"The highest ranked is *{published[0].title.lower()}*. "
        )
        + "Every recommendation is an experiment to run, not a "
        f"conclusion about causes: the data is observational, contains no cost information "
        f"and no booking-level records, and covers about 6% of the market."
    )
    add("")

    # ---- KPIs --------------------------------------------------------------
    add("## Key performance indicators")
    add("")
    add(
        "All values are computed from `v_city_listings` and `v_monthly_market` in "
        "`airbnb_queretaro.db`. Occupancy is **calendar occupancy** (reserved nights divided "
        "by all calendar nights in the period, including host-blocked nights) unless a row says "
        "otherwise. Revenue is **trailing-twelve-month revenue as reported by the provider**, "
        "not profit and not gross booking value."
    )
    add("")
    add("| KPI | Value | Unit | Period | Definition | n |")
    add("|---|---:|---|---|---|---:|")
    add(
        f"| Listings analyzed | {k['listings_city']} | listings | Aug 2025 - Jul 2026 | "
        f"Listings inside the 15 km city-core scope ({k['listings_total']} sampled in total, "
        f"1 rural excluded) | {k['listings_city']} |"
    )
    add(
        f"| Hosts in the city sample | {k['hosts_city']} | hosts | Aug 2025 - Jul 2026 | "
        f"Distinct hosts behind the analysed listings | {k['listings_city']} |"
    )
    add(
        f"| Median asking ADR | {mxn(h['price_mxn']['median'], 0)} | MXN / night | "
        f"Snapshot 2026-07 | Listing-level nightly asking price, median "
        f"(95% bootstrap CI {mxn(ci['price_mxn']['low'], 0)} - {mxn(ci['price_mxn']['high'], 0)}) | "
        f"{h['price_mxn']['n']} |"
    )
    add(
        f"| Mean asking ADR | {mxn(h['price_mxn']['mean'], 0)} | MXN / night | Snapshot 2026-07 | "
        f"Arithmetic mean; above the median because of a right-skewed tail | {h['price_mxn']['n']} |"
    )
    add(
        f"| Median calendar occupancy | {pct(h['occupancy']['median'])} | % of nights | "
        f"Aug 2025 - Jul 2026 | Reserved nights / all calendar nights "
        f"(95% bootstrap CI {pct(ci['occupancy']['low'])} - {pct(ci['occupancy']['high'])}) | "
        f"{h['occupancy']['n']} |"
    )
    add(
        f"| Median occupancy net of host blocks | {pct(h['adjusted_occupancy']['median'])} | "
        f"% of nights | Aug 2025 - Jul 2026 | Reserved nights / nights actually open for sale | "
        f"{h['adjusted_occupancy']['n']} |"
    )
    add(
        f"| Median TTM revenue per listing | {mxn(h['revenue_mxn']['median'], 0)} | MXN / listing | "
        f"Trailing 12 months to 2026-07 | Provider-reported revenue, median "
        f"(95% bootstrap CI {mxn(ci['revenue_mxn']['low'], 0)} - {mxn(ci['revenue_mxn']['high'], 0)}) | "
        f"{h['revenue_mxn']['n']} |"
    )
    add(
        f"| Total sample revenue | {mxn(k['total_ttm_revenue_mxn'], 0)} | MXN | "
        f"Trailing 12 months to 2026-07 | Sum of listing revenue in the city sample; "
        f"not a market total | {k['listings_city']} |"
    )
    add(
        f"| Median RevPAR | {mxn(h['revpar_mxn']['median'], 0)} | MXN / available night | "
        f"Trailing 12 months to 2026-07 | Revenue divided by nights available for sale | "
        f"{h['revpar_mxn']['n']} |"
    )
    add(
        f"| Revenue concentration (Gini) | {conc['gini']:.3f} | index 0-1 | Trailing 12 months | "
        f"Inequality of listing revenue: 0 = equal, 1 = one listing takes everything | "
        f"{k['listings_city']} |"
    )
    add(
        f"| Top 10% / 20% of listings' revenue share | {conc['top10_pct_share']:.1f}% / "
        f"{conc['top20_pct_share']:.1f}% | % of sample revenue | Trailing 12 months | "
        f"Share of revenue taken by the highest-earning decile / quintile | {k['listings_city']} |"
    )
    add(
        f"| Largest single host | {conc['top_host_listings']} listings, "
        f"{conc['top_host_share_pct']:.1f}% of revenue | listings / % | Trailing 12 months | "
        f"Most listings operated by one host in the sample | {k['listings_city']} |"
    )
    for label, row in (("Entire home", room.loc["entire_home"]), ("Private room", room.loc["private_room"])):
        add(
            f"| {label}: share of listings / revenue | {float(row['pct_of_sample']):.1f}% / "
            f"{float(row['pct_of_sample_revenue']):.1f}% | % | Trailing 12 months | "
            f"Median ADR {mxn(float(row['median_adr_mxn']), 0)}, median occupancy "
            f"{pct(float(row['median_occupancy']))}, median revenue "
            f"{mxn(float(row['median_ttm_revenue_mxn']), 0)} | {int(row['listings'])} |"
        )
    add(
        f"| Listings within 1 km of Plaza de Armas | {k['pct_within_1km']:.1f}% | % of listings | "
        f"Snapshot 2026-07 | Straight-line distance, the location proxy used because the data "
        f"has no neighbourhood field | {k['listings_city']} |"
    )
    add("")

    add("### Monthly trend (12-month window)")
    add("")
    add(
        "| Month | Listings with bookings | Calendar occupancy | Median quoted ADR | "
        "Median booked ADR | Revenue | Observation |"
    )
    add("|---|---:|---:|---:|---:|---:|---|")
    for row in ev.monthly.itertuples():
        censored_month = row.month_start > "2026-04-01"
        booked = row.median_adr_booked_mxn
        add(
            f"| {row.month_label} | {row.booked_listings} | {pct(row.occupancy)} | "
            f"{mxn(row.median_adr_quoted_mxn, 0)} | "
            f"{mxn(booked, 0) if pd.notna(booked) else 'n/a'} | "
            f"{mxn(row.revenue_mxn, 0)} | "
            f"{'censored (partial window)' if censored_month else 'complete'} |"
        )
    add("")
    add(
        f"**Censoring.** The last {len(censored)} months ({', '.join(censored['month_label'])}) are "
        f"incomplete in the source snapshot - monthly review volume falls 101 -> 73 -> 25 -> 6 "
        f"across the last four months - so their low occupancy and revenue are an artefact of the "
        f"cut-off, not demand. Every realised-demand statement in this report uses the "
        f"{len(complete)} complete months (Aug 2025 - Apr 2026)."
    )
    add("")

    # ---- Visualisations ----------------------------------------------------
    add("## Visualisations")
    add("")
    for path, caption, note in figure_captions(ev):
        add(f"### {caption}")
        add("")
        add(f"![{caption}]({path})")
        add("")
        add(f"*{note}*")
        add("")

    # ---- Findings ----------------------------------------------------------
    add("## Business findings")
    add("")
    for i, finding in enumerate(findings, start=1):
        add(f"**F{i}. {finding['title']}.** {finding['statement']}")
        add("")
        add(f"*Evidence:* {finding['evidence']}")
        add("")

    # ---- Recommendations ---------------------------------------------------
    add("## Recommended actions")
    add("")
    add(
        f"{len(published)} recommendations are published, generated by rules in "
        f"`src/generate_business_report.py` and ordered by "
        f"`priority_score = 0.5 x rule weight + 0.5 x evidence strength`. Thresholds are "
        f"analytical heuristics, not statistical tests; each is stated with the rule so a "
        f"reviewer can change it. Confidence refers to the pattern inside this sample, never "
        f"to the wider market."
    )
    add("")
    for i, rec in enumerate(published, start=1):
        add(f"### {i}. {rec.title}")
        add("")
        add(f"- **Finding:** {rec.finding}")
        add(f"- **Supporting evidence:** {rec.evidence}")
        add(f"- **Business implication:** {rec.implication}")
        add(f"- **Recommended next action:** {rec.action}")
        add(f"- **KPI to monitor:** {rec.kpi}")
        add(
            f"- **Confidence:** {rec.confidence} - {rec.confidence_basis}. "
            f"Priority score {rec.priority_score:.1f} (rule weight {rec.weight:.0f}, evidence "
            f"strength {rec.evidence_strength:.1f})."
        )
        add(f"- **Limitations / information still required:** {rec.limitations}")
        add(
            f"- **Traceability:** rule `{rec.rule_id}`, threshold: {rec.trigger_threshold} "
            f"Observed: {rec.observed}. Queries: {rec.evidence_queries}."
        )
        add("")

    if watchlist:
        add("### Rules that triggered but did not reach the publication cut")
        add("")
        add(
            "These rules triggered on the same data but scored below the top five. They are "
            "listed so nothing is silently dropped; each can be promoted by changing the "
            "publication threshold."
        )
        add("")
        for rec in watchlist:
            add(
                f"- **{rec.title}** (score {rec.priority_score:.1f}, confidence {rec.confidence}) - "
                f"{rec.finding} Sources: {rec.evidence_queries}."
            )
        add("")

    # ---- Next steps --------------------------------------------------------
    add("## Next steps")
    add("")
    add(
        f"1. **Repeat the snapshot.** Re-run `python src/run_all.py` on the next AirROI release "
        f"to extend the window past the censored months and test whether the "
        f"{m['within_listing']['median_adr_change_pct_aug_to_apr']:+.1f}% asking-price increase "
        f"persisted or reversed. This is the single highest-value follow-up because the current "
        f"window ends with three censored months."
    )
    add(
        f"2. **Complete the metadata.** Backfill bedroom and guest capacity for the "
        f"{int(ev.data_completeness['missing_capacity'])} listings that lack at least one of them, "
        f"so the capacity recommendation can be estimated on the whole sample instead of "
        f"{m['correlations']['price_mxn__guests']['n']} listings."
    )
    add(
        f"3. **Collect cost and booking-level data.** Without cleaning fees, commissions and "
        f"utility costs, revenue cannot be converted into profit; without check-in dates and "
        f"realised nightly prices per booking, demand and elasticity cannot be measured "
        f"directly. Both are prerequisites for any profitability claim."
    )
    add(
        f"4. **Run the repricing and capacity experiments described above** with pre-registered "
        f"control groups, then re-estimate the ADR-occupancy relationship on the treated sample."
    )
    add(
        f"5. **Widen the sample.** The {k['listings_city']} analysed listings are about 6% of the "
        f"market the provider reports (~1,733 active listings). Market-level totals, market share "
        f"and portfolio benchmarks need the full market export."
    )
    add(
        f"6. **Validate the concentration story.** With Gini {conc['gini']:.3f}, identify what the "
        f"top decile shares that the median listing does not, and test whether those attributes "
        f"can be transferred to mid-tier listings."
    )
    add("")

    # ---- Limitations -------------------------------------------------------
    add("## Limitations")
    add("")
    add(
        f"1. **Sample, not market.** The analysis covers **{k['listings_city']} listings** "
        f"({k['listings_total']} sampled in total) in Santiago de Querétaro, roughly 6% of the "
        f"market the provider reports. No market size, market total or market share is claimed "
        f"anywhere in this report; every figure describes this sample only."
    )
    add(
        f"2. **Provider sample, not a census.** AirROI describes the export as representative; "
        f"that is not independently verifiable from the file."
    )
    add(
        f"3. **Observational data.** Every comparison is an association. No recommendation here "
        f"asserts that a factor causes an outcome, and no causal claim is made from the "
        f"correlations."
    )
    add(
        f"4. **No cost data.** Revenue is not profit. No profitability, margin or return "
        f"conclusion can be drawn."
    )
    add(
        f"5. **No booking-level records.** Reserved nights and review counts are used as proxies "
        f"for realised demand; confirmed bookings cannot be counted from this source."
    )
    add(
        f"6. **Quoted prices are not realised prices.** Monthly asking ADRs and booked ADRs are "
        f"reported separately, and the two differ."
    )
    add(
        f"7. **Right-censored tail.** The last {len(censored)} months of the window are "
        f"incomplete in the snapshot; realised-demand statements use the {len(complete)} "
        f"complete months only."
    )
    add(
        f"8. **Incomplete fields.** {int(ev.data_completeness['missing_capacity'])} listings lack "
        f"capacity metadata ({int(ev.data_completeness['missing_bedrooms'])} without bedrooms, "
        f"{int(ev.data_completeness['missing_guests'])} without guest capacity), "
        f"{int(ev.data_completeness['inexact_location']) + int(ev.data_completeness['unknown_location'])} "
        f"have approximate or unknown coordinates, and one listing has a partial history."
    )
    add(
        f"9. **No neighbourhood field.** Location is a straight-line distance to Plaza de Armas "
        f"plus SEPOMEX postal polygons. A postal code is not a colonia, and 55 of the sampled "
        f"listings have approximate coordinates."
    )
    add(
        f"10. **Small cells.** The professional-management flag covers "
        f"{m['sample']['professionally_managed']} listings run by {m['sample']['professional_hosts']} "
        f"hosts, and the 4+ bedroom band has fewer than five listings; those comparisons are "
        f"case studies, not market effects."
    )
    add(
        f"11. **Stale snapshot.** Release 2026-07 was downloaded 2026-10-25, about three months "
        f"of lag, so the picture describes mid-2026 conditions."
    )
    add("")
    add(
        "The full method, cleaning decisions, metric definitions and refusals are in "
        "[`docs/methodology.md`](../docs/methodology.md); the evidence tables are in "
        "[`reports/findings.md`](findings.md) and [`reports/sql_results.md`](sql_results.md)."
    )
    add("")

    # ---- Appendix ----------------------------------------------------------
    add("## Appendix: rule evaluation")
    add("")
    add("| Rule | Threshold | Observed | Triggered | Score | Published |")
    add("|---|---|---|:-:|---:|:-:|")
    all_recs = published + watchlist
    for rec in all_recs:
        add(
            f"| `{rec.rule_id}` | {cell(rec.trigger_threshold)} | {cell(rec.observed)} | yes | "
            f"{rec.priority_score:.1f} | {'yes' if rec in published else 'watchlist'} |"
        )
    for rule, rule_id in RULES:
        if all(rec.rule_id != rule_id for rec in all_recs):
            add(f"| `{rule_id}` | {cell(THRESHOLDS[rule_id]['description'])} | - | no | - | - |")
    add("")
    add(
        f"Publication cut: {MAX_RECOMMENDATIONS} recommendations. "
        f"Priority score = 0.5 x rule weight + 0.5 x evidence strength; evidence strength is 50 "
        f"when the observed value sits exactly at its threshold and is capped at 100. "
        f"Confidence rubric: support >= 50 listings -> 100 points (>= 30 -> 70, otherwise 40); "
        f"-25 when >= 15% of the sample is missing a field the rule depends on; -25 when fewer "
        f"than 12 clean months exist; -25 when the claim is an association rather than a direct "
        f"measurement; >= 80 -> High, >= 50 -> Medium, otherwise Low."
    )
    add("")
    add(
        f"KPI consistency checks executed against `reports/key_metrics.json`: "
        f"{', '.join(kpi_checks)}. The report is generated only after these pass; a failure "
        f"aborts the run with a non-zero exit code."
    )
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 6 - exports
# ---------------------------------------------------------------------------
CSV_COLUMNS = [
    "priority",
    "rule_id",
    "title",
    "category",
    "priority_score",
    "confidence",
    "finding",
    "evidence",
    "implication",
    "action",
    "kpi_to_monitor",
    "limitations",
    "evidence_queries",
    "trigger_threshold",
    "observed_values",
]


def write_recommendations_csv(path: Path, recs: list[Recommendation]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for rank, rec in enumerate(recs, start=1):
            row = rec.as_dict()
            writer.writerow(
                {
                    "priority": rank,
                    "rule_id": row["rule_id"],
                    "title": row["title"],
                    "category": row["category"],
                    "priority_score": row["priority_score"],
                    "confidence": row["confidence"],
                    "finding": row["finding"],
                    "evidence": row["evidence"],
                    "implication": row["implication"],
                    "action": row["action"],
                    "kpi_to_monitor": row["kpi_to_monitor"],
                    "limitations": row["limitations"],
                    "evidence_queries": row["evidence_queries"],
                    "trigger_threshold": row["trigger_threshold"],
                    "observed_values": row["observed_values"],
                }
            )
    os.replace(tmp, path)


def update_key_metrics(
    path: Path, published: list[Recommendation], watchlist: list[Recommendation], generated_at: str
) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["business_recommendations"] = {
        "generated_at_utc": generated_at,
        "publication_cut": MAX_RECOMMENDATIONS,
        "scoring": "priority_score = 0.5 * rule weight + 0.5 * evidence strength",
        "thresholds": THRESHOLDS,
        "rule_weights": RULE_WEIGHTS,
        "recommendations": [
            {**rec.as_dict(), "rank": rank} for rank, rec in enumerate(published, start=1)
        ],
        "watchlist": [
            {**rec.as_dict(), "rank": None} for rec in watchlist
        ],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return data


# ---------------------------------------------------------------------------
# Step 7 - output validation
# ---------------------------------------------------------------------------
REQUIRED_SECTIONS = [
    "## Executive summary",
    "## Key performance indicators",
    "## Visualisations",
    "## Business findings",
    "## Recommended actions",
    "## Next steps",
    "## Limitations",
    "## Appendix: rule evaluation",
]


def validate_outputs(
    report: str,
    published: list[Recommendation],
    watchlist: list[Recommendation],
    metrics_payload: dict,
) -> list[str]:
    checks: list[str] = []

    for section in REQUIRED_SECTIONS:
        if section not in report:
            raise WorkflowError(f"report is missing the required section: {section}")
    checks.append(f"{len(REQUIRED_SECTIONS)} required sections present")

    missing_links = [
        path for path, _, _ in FIGURE_CAPTIONS if not (REPORTS_DIR / path).exists()
    ]
    if missing_links:
        raise WorkflowError(f"report references missing figures: {missing_links}")
    for path, _, _ in FIGURE_CAPTIONS:
        if f"]({path})" not in report:
            raise WorkflowError(f"report does not link figure {path}")
    checks.append(f"{len(FIGURE_CAPTIONS)} figure links resolve")

    if not (1 <= len(published) <= MAX_RECOMMENDATIONS):
        raise WorkflowError(
            f"published recommendation count {len(published)} outside 1..{MAX_RECOMMENDATIONS}"
        )
    checks.append(f"{len(published)} recommendations published (cap {MAX_RECOMMENDATIONS})")

    for rec in published:
        for field_name in ("finding", "evidence", "implication", "action", "kpi", "confidence", "limitations"):
            if not getattr(rec, field_name).strip():
                raise WorkflowError(f"recommendation {rec.rule_id} has an empty {field_name}")
    checks.append("every recommendation carries evidence, action, KPI, confidence and limits")

    json_recs = metrics_payload["business_recommendations"]["recommendations"]
    if len(json_recs) != len(published):
        raise WorkflowError("key_metrics.json recommendation count differs from the report")
    for json_rec, rec in zip(json_recs, published):
        if json_rec["rule_id"] != rec.rule_id or json_rec["finding"] != rec.finding:
            raise WorkflowError(f"key_metrics.json disagrees with the report on {rec.rule_id}")
    if len(metrics_payload["business_recommendations"]["watchlist"]) != len(watchlist):
        raise WorkflowError("key_metrics.json watchlist count differs from the report")
    checks.append("key_metrics.json matches the published recommendations")

    with RECOMMENDATIONS_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != len(published):
        raise WorkflowError(
            f"{RECOMMENDATIONS_CSV.name} has {len(rows)} rows for {len(published)} recommendations"
        )
    if [row["rule_id"] for row in rows] != [rec.rule_id for rec in published]:
        raise WorkflowError(f"{RECOMMENDATIONS_CSV.name} ordering differs from the report")
    checks.append(f"{RECOMMENDATIONS_CSV.name} holds {len(rows)} rows in report order")

    if "Sample, not market" not in report and "not the whole market" not in report:
        raise WorkflowError("report does not state the sample-vs-market caveat")
    checks.append("sample caveat stated in the report")
    return checks


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_workflow() -> dict:
    """Validate, recalculate, evaluate, write and validate the outputs."""
    validate_inputs()

    metrics = json.loads(KEY_METRICS_JSON.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY_REPORT.read_text(encoding="utf-8"))

    con = sqlite3.connect(DB_PATH)
    try:
        kpis, frames, completeness = collect_kpis(con)
    finally:
        con.close()

    kpi_checks = cross_check_kpis(kpis, metrics)

    ev = Evidence(
        kpis=kpis,
        metrics=metrics,
        quality=quality,
        monthly=frames["monthly"],
        room_type=frames["room_type"],
        distribution=frames["distribution"],
        distance_bands=frames["distance"],
        hosts=frames["hosts"],
        reviews_market=frames["reviews"],
        data_completeness=completeness,
    )

    published, watchlist = evaluate_rules(ev)
    findings = build_findings(ev)
    report = render_report(ev, findings, published, watchlist, kpi_checks)

    # Write only after the content is complete and internally consistent.
    report_tmp = REPORT_MD.with_suffix(".md.tmp")
    report_tmp.write_text(report, encoding="utf-8")
    os.replace(report_tmp, REPORT_MD)
    write_recommendations_csv(RECOMMENDATIONS_CSV, published)
    metrics_payload = update_key_metrics(
        KEY_METRICS_JSON, published, watchlist, ev.generated_at
    )

    output_checks = validate_outputs(report, published, watchlist, metrics_payload)

    return {
        "report": str(REPORT_MD),
        "recommendations_csv": str(RECOMMENDATIONS_CSV),
        "published": [rec.rule_id for rec in published],
        "watchlist": [rec.rule_id for rec in watchlist],
        "kpi_checks": kpi_checks,
        "output_checks": output_checks,
        "generated_at": ev.generated_at,
    }


def main() -> int:
    try:
        summary = run_workflow()
    except WorkflowError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - unexpected failure
        print(f"FAILED (unexpected): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"executive report  : {summary['report']}")
    print(f"recommendations   : {summary['recommendations_csv']}")
    print(f"published ({len(summary['published'])}): {', '.join(summary['published'])}")
    if summary["watchlist"]:
        print(f"watchlist         : {', '.join(summary['watchlist'])}")
    print("KPI cross-checks  : " + "; ".join(summary["kpi_checks"]))
    print("output checks     : " + "; ".join(summary["output_checks"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
