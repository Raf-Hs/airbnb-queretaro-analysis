"""Create the SQLite database from cleaned CSVs and the SQL schema.

Run order: clean_data.py -> build_db.py -> run_queries.py -> make_figures.py
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd

from config import DB_PATH, LISTINGS_CLEAN, RATES_CLEAN, REVIEWS_CLEAN, SQL_DIR


def _load(path, date_cols=(), int_cols=()):
    df = pd.read_csv(path, dtype={"listing_id": str, "postal_code": str})
    for col in date_cols:
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d")
    for col in int_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def insert_frame(con: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    cols = list(df.columns)
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    payload = df.astype(object).where(pd.notna(df), None)
    con.executemany(sql, list(payload.itertuples(index=False, name=None)))


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    listings = _load(
        LISTINGS_CLEAN,
        int_cols=[
            "superhost", "professional_management", "registration", "has_description",
            "is_city_core", "is_rural_outlier", "location_is_exact", "has_rating",
            "guest_favorite", "is_high_price_outlier",
        ],
    )
    rates = _load(RATES_CLEAN, date_cols=["date", "month_start"], int_cols=["has_bookings", "is_partial_history"])
    reviews = _load(REVIEWS_CLEAN, date_cols=["date", "month_start"], int_cols=["num_reviews"])

    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript((SQL_DIR / "01_schema.sql").read_text(encoding="utf-8"))
        insert_frame(con, "listings", listings)
        insert_frame(con, "monthly_rates", rates)
        insert_frame(con, "reviews_monthly", reviews)
        con.commit()
        con.executescript((SQL_DIR / "02_views.sql").read_text(encoding="utf-8"))
        con.commit()

        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_issues = con.execute("PRAGMA foreign_key_check").fetchall()
        counts = {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("listings", "monthly_rates", "reviews_monthly")
        }
        views = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name"
            )
        ]
        city = con.execute("SELECT COUNT(*) FROM v_city_listings").fetchone()[0]
        monthly = con.execute("SELECT COUNT(*) FROM v_monthly_market").fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        if fk_issues:
            raise RuntimeError(f"foreign key issues: {fk_issues}")
        if counts["listings"] != len(listings):
            raise RuntimeError(f"listing row count mismatch: {counts['listings']} != {len(listings)}")
        if city != int(listings["is_city_core"].sum()):
            raise RuntimeError("v_city_listings row count mismatch")
        if monthly != rates["month_start"].nunique():
            raise RuntimeError("v_monthly_market month count mismatch")

        summary = {
            "database": str(DB_PATH.name),
            "tables": counts,
            "views": views,
            "city_core_listings": city,
            "months_in_market_view": monthly,
            "integrity_check": integrity,
            "foreign_key_check": "ok",
        }
        print(json.dumps(summary, indent=2))
    finally:
        con.close()


if __name__ == "__main__":
    main()
