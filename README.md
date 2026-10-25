# Querétaro short-term rentals: what actually drives revenue?

An end-to-end data analyst case study on Airbnb pricing, occupancy and
seasonality in **Santiago de Querétaro, Mexico**.

Python + pandas · SQLite (portable SQL) · Power BI specification + DAX ·
10 figures · 16 SQL queries · 24 automated data-quality checks · 39-cell
executed notebook.

**Snapshot:** AirROI Data Portal, release `2026-07`, downloaded 2026-10-25.
**Sample:** 100 listings, 99 inside the city core. This is **not** the whole
market — see [the sample caveat](#the-sample-caveat-read-this-first).

[Findings](reports/findings.md) · [Methodology](docs/methodology.md) ·
[Data quality](reports/data_quality.md) · [SQL results](reports/sql_results.md) ·
[Dashboard spec](powerbi/dashboard_spec.md) · [Notebook](notebooks/01_eda.ipynb)

![Nightly price distribution](reports/figures/01_price_distribution.png)

---

## The sample caveat (read this first)

Inside Airbnb has **no Querétaro dataset** — its Mexico coverage is Mexico City
only. Rather than silently swap in another city, this project uses the free
**AirROI Data Portal** snapshot for Querétaro.

That snapshot is a **100-listing representative sample** of a market the provider
reports at ~1,733 active listings. So:

- Every number here describes **this sample**.
- No market-size, market-total, or market-share claim is made anywhere.
- The provider calls the sample representative; that claim is not independently
  verifiable from the file.

Everything else — the cleaning, the SQL, the statistics, the caveats — is built
to survive that limitation rather than hide it.

---

## Executive summary

In this 99-listing city sample, **what a listing is** tracks revenue far more
closely than **where it is** or **what it charges**.

| Metric | Median | 95% bootstrap CI |
|---|---:|---|
| Quoted ADR, MXN/night | **MX$1,029** | 832 – 1,160 |
| Calendar occupancy | **24.1%** | 18.1% – 31.5% |
| Trailing-12-month revenue | **MX$87,335** | 54,273 – 116,516 |
| RevPAR, MXN/available night | **MX$233** | 149 – 290 |

Total revenue across the 99 city listings: **MX$11,995,861**. Mean ADR (MX$1,303)
sits well above the median, so medians and bootstrap intervals — not means —
carry the argument.

### Five findings

1. **Room type is the dominant revenue split.** Entire homes are 75.8% of
   listings but **92.2% of sample revenue**. Median ADR is 1.78× a private room;
   median revenue is **4.20×**, because entire homes win on both price and
   occupancy. (Mann–Whitney p = 5.5 × 10⁻⁷, Cliff's δ = 0.68.)

2. **Capacity is the clearest visible price driver.** ADR correlates with guest
   count at ρ = **+0.57** and bedrooms at ρ = **+0.47** (n = 80). Price per guest
   is U-shaped: studios extract MX$458/guest, 2-bedrooms only MX$292.

3. **There is no detectable distance–price gradient.** Distance to Plaza de Armas
   correlates with ADR at ρ = **−0.013** (p = 0.90, n = 99); within entire homes
   alone, ρ = +0.058 (p = 0.62). Reported as "this dataset cannot identify a
   location premium", not "location does not matter".

4. **Price level is not what limits occupancy.** ADR ↔ occupancy is ρ = **+0.14**
   (p = 0.17), while revenue ↔ occupancy is **+0.83**. Occupancy spans roughly
   10% to 42% between the 25th and 75th percentile, and price barely moves with
   it — empty listings are not empty because they are expensive.

5. **Hosts raised asking prices 25% into flat demand.** Across the 98 listings
   present in both months, **93.9%** raised their asking ADR between Aug 2025 and
   Apr 2026 — median **+24.5%** — while median occupancy fell **3.1 points**.

![Correlation matrix](reports/figures/09_correlation_matrix.png)

Full detail, caveats and recommendations: **[reports/findings.md](reports/findings.md)**.

---

## What this project does differently

Most portfolio analyses stop at a clean chart. This one spends its effort on the
decisions that change whether the chart is true.

| Trap | What happened here |
|---|---|
| **Provider CSV exports were malformed** (broken quoting, shifted columns) | Detected before analysis; switched to the JSONL exports and documented why. The CSVs would have silently corrupted prices. |
| **`blocked_days` looks like a third calendar category** | It is a *subset* of available days (`reserved + available = 365`, 100/100). Treating it as extra double-counts supply. Two occupancy definitions were built and labelled. |
| **The last three months look like a demand crash** | Review volume collapses 101 → 73 → 25 → 6 from April to July. That is right-censoring, not demand. All realised-demand claims are restricted to **Aug 2025 – Apr 2026**. |
| **There is no neighbourhood field** | No colonia is invented. Location is a reproducible distance-to-centro band plus SEPOMEX postal polygons, with an explicit warning that a postal code is not a neighbourhood. |
| **19 listings omit bedrooms/guests** | Nothing imputed. Capacity cuts show `n = 80` and an `Unknown` band. Imputing would have manufactured the strongest correlation in the study. |
| **"Professional management triples revenue"** | The flag covers **17 listings run by 2 hosts**. It is labelled a two-host case study on every page, not a market effect. |
| **Quoted vs realised price** | Kept separate everywhere. April 2026: quoted median MX$1,150 vs booked MX$1,198. Revenue is never called gross booking value. |
| **Revenue does not equal ADR × nights** | Nights reconcile exactly (9,588); revenue differs by +4.3%, consistent with fees. Documented rather than "fixed". |
| **A `.pbix` that does not exist** | Not claimed. The Power BI folder contains a full spec, DAX and theme, and says so in the first line. |

Also built in: bootstrap confidence intervals (10,000 resamples, seeded), effect
sizes alongside p-values, within-listing differencing to remove composition
effects, and a robustness re-run with/without high-price and rural listings.

---

## Repository map

```
airbnb-queretaro-analysis/
├── README.md                     ← you are here
├── LICENSE                       ← MIT (code only; data is CC BY-NC 4.0)
├── requirements.txt
├── airbnb_queretaro.db           ← SQLite, rebuilt by build_db.py
│
├── data/
│   ├── README.md                 ← provenance, exact URLs, checksums, dictionary
│   ├── raw/                      ← 4 source files (3 AirROI + SEPOMEX polygons)
│   └── processed/                ← cleaned CSVs + data_quality.json
│
├── src/
│   ├── config.py                 ← paths, palette, centro coordinates, bands
│   ├── clean_data.py             ← cleaning + 24 automated checks
│   ├── build_db.py               ← schema, views, CSV → SQLite
│   ├── run_queries.py            ← executes 16 queries → markdown report
│   ├── analyze.py                ← bootstrap, Mann–Whitney, Cliff's δ, within-listing
│   ├── make_figures.py           ← 10 publication-style PNGs
│   └── run_all.py                ← one-command pipeline
│
├── sql/
│   ├── 01_schema.sql             ← tables, CHECK constraints, indexes
│   ├── 02_views.sql              ← v_city_listings, v_monthly_market, …
│   └── 03_analysis_queries.sql   ← 16 documented analysis queries
│
├── notebooks/
│   └── 01_eda.ipynb              ← executed, 39 cells, 0 errors
│
├── reports/
│   ├── findings.md               ← the analysis, with caveats
│   ├── data_quality.md           ← what passed, what it does not prove
│   ├── sql_results.md            ← generated query output
│   ├── key_metrics.json          ← machine-readable source of truth
│   └── figures/                  ← 10 PNGs
│
├── powerbi/
│   ├── dashboard_spec.md         ← 5 pages + drillthrough + tooltip, build steps
│   ├── measures.dax              ← 55 measures and the date table
│   └── theme.json                ← custom theme
│
└── docs/
    └── methodology.md            ← decisions log, metric definitions, limits
```

---

## Run it

Requires Python 3.12+ (tested on 3.12.10, Windows 11).

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt

python src/run_all.py
```

That runs, in order:

| Step | Output |
|---|---|
| `clean_data.py` | `data/processed/*.csv`, `data_quality.json` (24 checks) |
| `build_db.py` | `airbnb_queretaro.db` from schema + views + CSVs |
| `run_queries.py` | `reports/sql_results.md` (16 queries) |
| `analyze.py` | `reports/key_metrics.json` (bootstrap CIs, tests) |
| `make_figures.py` | `reports/figures/*.png` (10 figures) |

Each script also runs standalone. `clean_data.py` fails loudly if a raw file is
missing or a schema assumption breaks. Expected result: **24 checks, 0 failed**.

Open the notebook:

```bash
jupyter lab notebooks/01_eda.ipynb
```

---

## SQL layer

SQLite is used instead of SQL Server Express because administrator rights were
not available on the analysis machine. The SQL avoids SQLite-only syntax, so the
schema ports to SQL Server or Postgres with type changes only.

**Schema:** 3 tables, PKs, FKs with `ON DELETE CASCADE`, `CHECK` constraints on
every bounded field (occupancy 0–1, price > 0, booleans 0/1), and 6 indexes.

**Views:**

- `v_city_listings` — 99 listings inside the 15 km city core
- `v_monthly_city` — listing-month rows joined to listing attributes
- `v_monthly_market` — month-level aggregates
- `v_complete_months` — the 9 uncensored months
- `v_reviews_market` — review counts by month

**Queries** (`sql/03_analysis_queries.sql`): portfolio overview, room-type
performance, distribution percentiles, monthly seasonality, seasonality by room
type, distance bands, superhost, professional management, bedroom bands, revenue
concentration, host concentration, rating bands, length of stay, postal-code
hotspots, robustness scope, and censoring evidence.

Every query has a `-- name:` and `-- description:` header; `run_queries.py` turns
them into `reports/sql_results.md` automatically.

> Note: `sql/03_analysis_queries.sql` is almost entirely ANSI SQL. The single
> `LIMIT 12` would become `TOP 12` (or `OFFSET … FETCH`) on SQL Server.

---

## Power BI

**No `.pbix` is included.** Power BI Desktop could not be installed or driven in
this environment (no admin rights, no interactive desktop), so claiming a
dashboard file would be dishonest.

Instead, `powerbi/` contains everything needed to build the report:

- **`dashboard_spec.md`** — five pages with layouts, field-to-visual mappings,
  slicers, interactions, a drillthrough page, a tooltip page, bookmark recipes
  for the censored region, 14 build steps, and a 23-point QA checklist.
- **`measures.dax`** — 55 measures (median ADR, calendar vs adjusted occupancy,
  realised ADR, revenue concentration, ADR index, censoring labels), plus the
  calculated `Date` table and relationships.
- **`theme.json`** — colour palette, typography, card and page defaults.

The spec is deliberately opinionated: no pie charts, no gauges, no "best
neighbourhood" ranking, and no forecast. Those choices are explained in
§12 of the spec.

---

## Data and licence

| | |
|---|---|
| Source | [AirROI Data Portal — Querétaro](https://www.airroi.com/data-portal/markets/queretaro-mexico) |
| Release | `2026-07` (published 2026-07-30) |
| Downloaded | 2026-10-25 |
| Coverage | 100 listings, 51 hosts, 1,195 listing-months, Aug 2025 – Jul 2026 |
| Currency | MXN (USD also supplied at ~19.44) |
| Licence | **CC BY-NC 4.0** — attribution required, no commercial use |

Raw file checksums, exact S3 URLs, the full data dictionary, missingness and every
known quirk are in **[data/README.md](data/README.md)**.

Inside Airbnb was the preferred source and was checked first; it has no
Querétaro data. The decision process and rejected alternatives are documented in
`docs/methodology.md` §2.

**Attribution:**

> AirROI Data Portal, Querétaro, Mexico, release 2026-07, accessed 2026-10-25,
> CC BY-NC 4.0.

Code is MIT-licensed. The licence does not extend to the data.

---

## Limitations

1. **100-listing sample**, ~6% of the market. No market totals.
2. **No neighbourhood field.** Distance bands and postal polygons are proxies.
3. **55 listings have approximate coordinates** (6 more are unknown); distance
   is block-level at best.
4. **Right-censored tail.** May–Jul 2026 excluded from demand claims.
5. **Quoted ≠ realised.** Revenue excludes some fees (+4.3% gap).
6. **One rural listing** (47 km) excluded from city statistics, retained and flagged.
7. **One partial-history listing** (7 of 12 months).
8. **Observational data.** No causal identification; segment comparisons are
   confounded. Every recommendation is conditional.
9. **Snapshot is ~3 months stale** relative to download.
10. **Small cells.** The 4+ bedroom band has n = 4; professional management has
    2 hosts.

The full "what this analysis cannot say" table is in
[`docs/methodology.md` §10](docs/methodology.md#10-what-this-analysis-cannot-say).

---

## Documentation index

| Document | Read it for |
|---|---|
| [`reports/findings.md`](reports/findings.md) | The analysis, nine findings, caveats, recommendations |
| [`docs/methodology.md`](docs/methodology.md) | Source selection, cleaning log, metric definitions, statistics, refusals |
| [`reports/data_quality.md`](reports/data_quality.md) | 24 checks, the `blocked_days` trap, censoring evidence, what checks do not prove |
| [`data/README.md`](data/README.md) | Provenance, URLs, checksums, column dictionary, missingness, licence |
| [`reports/sql_results.md`](reports/sql_results.md) | Raw output of all 16 queries |
| [`powerbi/dashboard_spec.md`](powerbi/dashboard_spec.md) | How to build the report without a `.pbix` |
| [`notebooks/01_eda.ipynb`](notebooks/01_eda.ipynb) | Executed narrative analysis |

---

## Tools

Python 3.12 · pandas · NumPy · SciPy · Matplotlib · seaborn · GeoPandas ·
Shapely · SQLAlchemy · SQLite · Jupyter · Power BI (specification only) · Git.

No Docker, no web app, no scraping, no paid APIs.
