"""Tests for the business reporting workflow.

These tests run against the real project artefacts (the SQLite database and the
cleaned CSVs). If the pipeline has not been run yet, the suite skips with a
clear message instead of inventing data.

    python src/run_all.py      # build the artefacts first
    python -m pytest tests -q   # then run the tests
"""

from __future__ import annotations

import copy
import csv
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import generate_business_report as gbr  # noqa: E402
from config import DB_PATH, QUALITY_REPORT, REPORTS_DIR  # noqa: E402


def _artefacts_ready() -> bool:
    return (
        DB_PATH.exists()
        and gbr.KEY_METRICS_JSON.exists()
        and gbr.SQL_RESULTS_MD.exists()
        and QUALITY_REPORT.exists()
    )


requires_artefacts = pytest.mark.skipif(
    not _artefacts_ready(),
    reason="pipeline artefacts missing - run `python src/run_all.py` first",
)


@pytest.fixture(scope="module")
def evidence() -> gbr.Evidence:
    """The evidence bundle the rules and the report are built from."""
    metrics = json.loads(gbr.KEY_METRICS_JSON.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY_REPORT.read_text(encoding="utf-8"))
    con = sqlite3.connect(DB_PATH)
    try:
        kpis, frames, completeness = gbr.collect_kpis(con)
    finally:
        con.close()
    return gbr.Evidence(
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


# ---------------------------------------------------------------------------
# KPI correctness
# ---------------------------------------------------------------------------
@requires_artefacts
def test_kpis_are_recalculated_from_the_database(evidence: gbr.Evidence) -> None:
    """The report's KPIs must be the database's numbers, not the JSON's."""
    con = sqlite3.connect(DB_PATH)
    try:
        median_adr = con.execute(
            """
            SELECT AVG(price_mxn) FROM (
                SELECT price_mxn, ROW_NUMBER() OVER (ORDER BY price_mxn) AS rn,
                       COUNT(*) OVER () AS n FROM v_city_listings
            ) WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
            """
        ).fetchone()[0]
        listings = con.execute("SELECT COUNT(*) FROM v_city_listings").fetchone()[0]
    finally:
        con.close()

    assert evidence.kpis["listings_city"] == listings == 99
    assert evidence.kpis["median_adr_mxn"] == pytest.approx(median_adr, abs=0.05)
    assert evidence.kpis["median_adr_mxn"] == pytest.approx(
        evidence.metrics["headline"]["price_mxn"]["median"], abs=1.0
    )
    assert evidence.kpis["total_ttm_revenue_mxn"] == pytest.approx(
        evidence.metrics["concentration"]["total_revenue_mxn"], abs=1.0
    )


@requires_artefacts
def test_cross_check_rejects_a_mismatched_kpi(evidence: gbr.Evidence) -> None:
    """A KPI that disagrees with the analysis must abort the report."""
    broken = copy.deepcopy(evidence.kpis)
    broken["median_adr_mxn"] = broken["median_adr_mxn"] + 500
    with pytest.raises(gbr.WorkflowError, match="KPI mismatch"):
        gbr.cross_check_kpis(broken, evidence.metrics)


@requires_artefacts
def test_sql_analysis_queries_still_execute() -> None:
    """Every query in sql/03_analysis_queries.sql runs against the database."""
    queries = gbr.load_query_map()
    assert len(queries) == 16
    con = sqlite3.connect(DB_PATH)
    try:
        for name, sql in queries.items():
            df = pd.read_sql_query(sql, con)
            assert not df.empty, f"{name} returned no rows"
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Recommendation rules
# ---------------------------------------------------------------------------
@requires_artefacts
def test_rules_fire_on_the_real_data(evidence: gbr.Evidence) -> None:
    published, watchlist = gbr.evaluate_rules(evidence)
    assert 1 <= len(published) <= gbr.MAX_RECOMMENDATIONS
    assert published, "no recommendation was generated from the real data"
    rule_ids = {rec.rule_id for rec in published}
    assert "pricing_repricing_divergence" in rule_ids
    assert "revenue_concentration" in rule_ids
    for rec in published + watchlist:
        assert rec.evidence.strip()
        assert rec.observed.strip()
        assert 0 <= rec.priority_score <= 100


@requires_artefacts
def test_pricing_rule_does_not_fire_without_a_price_increase(evidence: gbr.Evidence) -> None:
    """The rule is a rule: without the pattern it produces nothing."""
    ev = copy.deepcopy(evidence)
    ev.metrics["within_listing"]["median_adr_change_pct_aug_to_apr"] = 2.0
    ev.metrics["within_listing"]["occupancy_change_pp_vs_aug"]["2026-04-01"]["median"] = 0.0
    assert gbr.rule_pricing_repricing_divergence(ev) is None


@requires_artefacts
def test_concentration_rule_does_not_fire_on_an_even_portfolio(evidence: gbr.Evidence) -> None:
    ev = copy.deepcopy(evidence)
    ev.metrics["concentration"]["gini"] = 0.05
    ev.metrics["concentration"]["top10_pct_share"] = 11.0
    assert gbr.rule_revenue_concentration(ev) is None


@requires_artefacts
def test_capacity_rule_does_not_fire_without_a_correlation(evidence: gbr.Evidence) -> None:
    ev = copy.deepcopy(evidence)
    ev.metrics["correlations"]["price_mxn__guests"]["spearman_rho"] = 0.05
    ev.metrics["correlations"]["price_mxn__bedrooms"]["spearman_rho"] = 0.04
    assert gbr.rule_capacity_price_signal(ev) is None


@requires_artefacts
def test_seasonal_rule_does_not_fire_on_a_flat_year(evidence: gbr.Evidence) -> None:
    ev = copy.deepcopy(evidence)
    monthly = ev.monthly.copy()
    monthly["occupancy"] = 0.30
    monthly["revenue_mxn"] = 1_000_000
    ev.monthly = monthly
    assert gbr.rule_seasonal_amplitude(ev) is None


@requires_artefacts
def test_data_quality_rule_does_not_fire_on_complete_data(evidence: gbr.Evidence) -> None:
    ev = copy.deepcopy(evidence)
    ev.data_completeness["missing_capacity"] = 0
    ev.data_completeness["inexact_location"] = 0
    ev.data_completeness["unknown_location"] = 0
    ev.data_completeness["partial_history_listings"] = 0
    assert gbr.rule_data_completeness_prerequisite(ev) is None


@requires_artefacts
def test_recommendations_are_reproducible(evidence: gbr.Evidence) -> None:
    """Same input data -> same conclusions, in the same order."""
    first = [rec.rule_id for rec in gbr.evaluate_rules(evidence)[0]]
    second = [rec.rule_id for rec in gbr.evaluate_rules(copy.deepcopy(evidence))[0]]
    assert first == second


# ---------------------------------------------------------------------------
# Report generation and consistency
# ---------------------------------------------------------------------------
@requires_artefacts
def test_report_contains_every_required_section(evidence: gbr.Evidence) -> None:
    published, watchlist = gbr.evaluate_rules(evidence)
    findings = gbr.build_findings(evidence)
    report = gbr.render_report(evidence, findings, published, watchlist, ["unit test"])

    for section in gbr.REQUIRED_SECTIONS:
        assert section in report

    # headline KPIs appear with their units
    assert "MX$1,029" in report
    assert "24.1%" in report
    assert "MX$87,335" in report
    assert "99" in report

    # every figure is embedded with a relative path that resolves
    for path, _, _ in gbr.figure_captions(evidence):
        assert f"]({path})" in report
        assert (REPORTS_DIR / path).exists()

    # the sample caveat is stated, not implied
    assert "Sample, not market" in report
    assert "99 listings" in report

    # recommendations carry every field the brief asks for
    assert report.count("**Recommended next action:**") == len(published)
    assert report.count("**KPI to monitor:**") == len(published)
    assert report.count("**Confidence:**") == len(published)
    assert report.count("**Limitations / information still required:**") == len(published)


@requires_artefacts
def test_workflow_writes_consistent_outputs(evidence: gbr.Evidence) -> None:
    """The report, the CSV and the JSON must agree with each other."""
    summary = gbr.run_workflow()

    assert Path(summary["report"]).exists()
    assert Path(summary["recommendations_csv"]).exists()

    with gbr.RECOMMENDATIONS_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert 1 <= len(rows) <= gbr.MAX_RECOMMENDATIONS
    assert list(rows[0].keys()) == gbr.CSV_COLUMNS
    for row in rows:
        assert row["evidence"].strip()
        assert row["action"].strip()
        assert row["kpi_to_monitor"].strip()
        assert row["confidence"].strip()
        assert row["limitations"].strip()

    payload = json.loads(gbr.KEY_METRICS_JSON.read_text(encoding="utf-8"))
    block = payload["business_recommendations"]
    assert len(block["recommendations"]) == len(rows)
    assert [r["rule_id"] for r in block["recommendations"]] == [row["rule_id"] for row in rows]
    assert block["thresholds"] == gbr.THRESHOLDS


@requires_artefacts
def test_report_is_not_published_when_a_kpi_check_fails(monkeypatch, tmp_path) -> None:
    """A broken pipeline must not leave a report that looks successful."""
    before = gbr.REPORT_MD.read_text(encoding="utf-8") if gbr.REPORT_MD.exists() else None

    def boom(*_args, **_kwargs):
        raise gbr.WorkflowError("KPI mismatch on median ADR: simulated")

    monkeypatch.setattr(gbr, "cross_check_kpis", boom)
    with pytest.raises(gbr.WorkflowError):
        gbr.run_workflow()

    after = gbr.REPORT_MD.read_text(encoding="utf-8") if gbr.REPORT_MD.exists() else None
    assert after == before


@requires_artefacts
def test_generation_is_deterministic(evidence: gbr.Evidence) -> None:
    """Two runs on the same data produce the same analytical conclusions."""
    published, watchlist = gbr.evaluate_rules(evidence)
    findings = gbr.build_findings(evidence)
    first = gbr.render_report(evidence, findings, published, watchlist, ["unit test"])
    second = gbr.render_report(
        copy.deepcopy(evidence),
        gbr.build_findings(copy.deepcopy(evidence)),
        *gbr.evaluate_rules(copy.deepcopy(evidence)),
        ["unit test"],
    )

    def strip_timestamp(text: str) -> str:
        return "\n".join(
            line for line in text.splitlines() if "Generated by" not in line
        )

    assert strip_timestamp(first) == strip_timestamp(second)


@requires_artefacts
def test_missing_upstream_artefact_is_a_critical_failure(monkeypatch, tmp_path) -> None:
    """No database means no report."""
    monkeypatch.setattr(gbr, "DB_PATH", tmp_path / "missing.db")
    with pytest.raises(gbr.WorkflowError, match="database missing"):
        gbr.validate_inputs()
