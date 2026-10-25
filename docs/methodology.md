# Methodology

This document records *how* the analysis was built and *why* each decision was
made, including the ones that constrain the conclusions. If you only read one
section, read §11 (what this analysis cannot say).

---

## 1. Question and analytical frame

**Business question:** for a short-term-rental operator or investor looking at
Santiago de Querétaro, what actually separates high-earning listings from the
rest — price, location, capacity, room type, host behaviour, or timing?

**Unit of analysis:** the individual Airbnb listing. Not the booking, not the
host, not the postal code.

**Outcome variables**, in order of importance:

| Variable | Definition | Why it is (or is not) the headline |
|---|---|---|
| `revenue_mxn` | Trailing-twelve-month revenue per listing | Closest available proxy for "does this property make money" |
| `occupancy` | Reserved nights ÷ all calendar nights | Demand realised by the listing |
| `price_mxn` | Quoted ADR, MXN per night | A *pricing decision*, not an outcome. Easy to raise, hard to monetise. |

Price is treated as a **lever**, occupancy as the **constraint**, revenue as the
**result**. Much of the analysis is about how weakly those three connect.

**Deliberate refusals:**

- No occupancy or revenue **estimate** from review counts. Review-based
  occupancy models need a reviews-per-stay calibration this dataset cannot
  supply.
- No claim about **booked revenue** using quoted prices. The dataset separates
  them and so does this project.
- No market-size or market-share claims from a 100-listing sample.

---

## 2. Source selection

Inside Airbnb publishes no Querétaro data (Mexico coverage is Mexico City only as
of 2026-10-25). Rather than silently swap in another city, the project switched
to the **AirROI Data Portal** free snapshot for `city=Querétaro`, release
`2026-07`.

That choice costs something and the cost is carried forward:

| Gain | Cost |
|---|---|
| Listing-level attributes + 12 months of calendar history | 100-listing sample (~6% of the ~1,733 active market) |
| Documented field schema, consistent currency, provider-computed TTM metrics | No public methodology note comparable to Inside Airbnb's |
| Real reserved-night counts | Provider sample may over-represent professionally managed stock |

Full provenance, URLs, and checksums are in `data/README.md`.

### Why not scrape

Scraping Airbnb would breach its terms of service and produce a snapshot no
reviewer could reproduce. It was ruled out before any code was written.

---

## 3. Data model

Three tables, one grain each:

```
listings (100 rows, PK listing_id)
   │  1:1 annual performance (TTM aggregates)
   │
   ├──< monthly_rates (1,195 rows, PK listing_id + month_start)
   │       12 months per listing; 7 for one partial-history listing
   │
   └──< reviews_monthly (532 rows, PK listing_id + month_start)
           only months with ≥ 1 review; 95 of 100 listings present
```

`monthly_rates` is the only source of time variation. `listings` holds
provider-computed trailing-twelve-month aggregates, which is why the two do not
aggregate to identical totals (see §5.5).

The database is **SQLite** (`airbnb_queretaro.db`), chosen because SQL Server
Express requires administrator rights that were not available on the analysis
machine. The SQL is written portably (no SQLite-only syntax beyond
`STRFTIME`-free date handling) and the schema, constraints, indexes, and views
are in `sql/`.

---

## 4. Location: what the data lets us say

**The dataset has no neighbourhood field.** No `neighbourhood`, no `colonia`, no
`city_area`. Any "best neighbourhood" claim would have to be invented.

Two reproducible location proxies were built instead:

### 4.1 Straight-line distance to Plaza de Armas

Haversine distance from each listing to `20.5931, −100.3899` (Centro Histórico),
binned into six ordered bands:

| Band | Range | n (city sample) |
|---|---|---:|
| Centro (0-1 km) | 0–1 km | 51 |
| Centro extendido (1-2 km) | 1–2 km | 18 |
| Corona urbana (2-4 km) | 2–4 km | 15 |
| Periferia (4-8 km) | 4–8 km | 6 |
| Zona metropolitana (8-15 km) | 8–15 km | 9 |
| Exterior (>15 km) | >15 km | 1 (excluded from city stats) |

This proxy is crude: it ignores road distance, barriers, and micro-location. It
is nonetheless **defensible, explainable, and reproducible**, which a fabricated
neighbourhood label is not.

### 4.2 SEPOMEX postal-code polygons

Each listing was spatially joined to the 518 SEPOMEX polygons for state 22.
100/100 points fell inside a polygon (0 required nearest-polygon fallback).

**Postal code is not a colonia.** CP 76000 and CP 76020 both cover large parts of
the centre; CP 76100 covers a peripheral area. Postal-code tables in
`reports/findings.md` are therefore labelled *postal-code areas*, with an explicit
warning, and are used only to show within-area heterogeneity — never to rank
neighbourhoods.

### 4.3 Precision caveat

55 listings have `exact_location = false` (and 6 more are null), meaning the
provider publishes approximate coordinates. Distance is accurate to roughly the
block or colonia, not the building. This blurs fine-grained distance effects —
which is one reason the near-zero distance–price correlation is reported as "no
detectable gradient", not "location does not matter".

---

## 5. Metric definitions

### 5.1 ADR (average daily rate)

- `price_mxn` = `ttm_avg_rate_native` — the provider's **quoted** average nightly
  rate over 12 months.
- `adr_booked_mxn` (monthly table) = **realised** average rate on nights that
  actually sold; null when nothing sold.

Quoted and realised ADR are never mixed in the same comparison without saying
which is which.

### 5.2 Calendar occupancy — the headline occupancy

```
calendar_occupancy = reserved_nights / (reserved_nights + vacant_nights)
```

where `vacant = total − reserved` and therefore includes host-blocked nights. This
is the conservative, comparable definition: a night the host blocked to friends
or for maintenance still counts as a night the property did not earn on.

Monthly `occupancy` in `monthly_rates` uses exactly this formula
(`reserved_days / (reserved_days + vacant_days)`), so it also counts host-blocked
nights as unearned. Monthly and annual figures share the definition; they differ
in level because the monthly figure is a night-weighted aggregate across
listings (sum of reserved ÷ sum of calendar nights), while the headline is the
median of per-listing annual occupancy.

### 5.3 Adjusted occupancy — reported separately, never as the headline

```
adjusted_occupancy = reserved_nights / (total_nights − host_blocked_nights)
```

This answers "when the host made the calendar available, how often did it book?"
It is always ≥ calendar occupancy and is inflated for listings with heavy
personal-use blocking. Headline numbers use calendar occupancy; adjusted
occupancy appears as a secondary column with a label. In this sample the median
rises from 24.1% to 27.8%, and the mean by 5.3 percentage points; 48 of 100
listings blocked at least one night, so for the other half the two definitions
are identical.

### 5.4 RevPAR

`revpar_mxn` = revenue per available night = revenue ÷ all calendar nights.
Consistent with calendar occupancy by construction.

### 5.5 Revenue, and the fee gap

`revenue_mxn` (listings) is provider TTM revenue. `revenue_mxn`
(monthly_rates) is nightly-rate revenue per month.

Reconciliation:

| Check | Value |
|---|---|
| Monthly revenue summed over 12 months | MX$11,505,194 |
| TTM revenue summed over listings | MX$11,995,861 |
| Difference | +4.3% (TTM higher) |
| Reserved nights, monthly sum | 9,588 |
| Reserved nights, TTM sum | 9,588 (exact match) |

Reserved nights agree exactly, so this is not a counting error. The revenue gap
is consistent with fees (cleaning, extra guest) collected on top of the nightly
rate. **Therefore `revenue_mxn` is not gross booking value**, and this project
does not call it that.

### 5.6 `blocked_days` semantics

A non-obvious provider quirk, verified in `clean_data.py`:

```
reserved_days + available_days = total_days        (100/100 listings)
blocked_days ⊆ available_days
```

`blocked_days` is **not** an additional category alongside reserved and
available. Treating it as extra would double-count supply. This is why
`adjusted_occupancy` divides by `total − blocked`, not by `total`.

---

## 6. Cleaning decisions log

Every transformation is in `src/clean_data.py`; this is the rationale, not the
code.

| Decision | Rationale | Consequence |
|---|---|---|
| Parse JSONL, not the provider's CSV | CSV exports have broken quoting/column shifts | Avoids silently corrupted prices and names |
| Strip Unicode directional isolates from names | Airbnb wraps names in `U+202A`–`U+202E`; invisible in editors, breaks CSV/Power BI matching | Clean display names |
| Cast performance fields to nullable numeric types | Missing values must stay missing, not become 0 | No silent zero-filling |
| **No imputation of bedrooms/guests** | 19 listings omit them (17 private rooms). Imputing would manufacture the strongest correlation in the study | Capacity analyses report `n = 80` and show `Unknown` |
| `bedroom_band` / `guest_band` retain `Unknown` | Keeps missingness visible in every chart | Reviewer can see what was excluded |
| Distance computed from coordinates | Only defensible location signal available | See §4 |
| Postal code joined spatially, not text-matched | Text matching fails silently on formatting | 100/100 matched, method recorded |
| `is_city_core` at 15 km | One farm stay 47 km east skews city statistics | 99-listings city sample; rural listing retained and flagged |
| `is_high_price_outlier = Q3 + 3×IQR` | Robust fence; the 6 flagged listings are genuinely large homes | Flag is a **segment label**, never deleted; robustness check re-runs medians without them |
| One partial-history listing flagged | `13845232` has 7 months, not 12 | `is_partial_history`; excluded from paired within-listing comparisons |
| L90D fields carried but unused | They overlap the censored window | Prevents accidental comparison of 90-day and 12-month metrics |
| Revenue kept as provider-computed | Recomputing from ADR × nights would drop fees and diverge | Fee gap documented instead of "fixed" |

### The outlier question

No listing was deleted for being expensive. The most expensive listings
(MX$5,184–11,176/night) are 3–9 bedroom homes, one of them a rural estate — real market
segments. Deleting them would make the portfolio look tidier and the analysis
less true.

Robustness instead: `q15_robustness_scope` re-computes means with and without the
6 high-price flags and with/without the rural listing. Mean ADR moves from
MX$1,303 (n=99) to MX$1,016 (n=94); the medians used in the headline findings
barely move.

---

## 7. Censoring: how the observation window was found

A snapshot taken in July 2026 cannot know about stays that had not been booked or
reviewed yet. Left unchecked, this produces a fake "demand collapse" in the last
months.

**Evidence used:** monthly review counts, which are written *after* a stay and
therefore lag bookings.

| Month | Reviews | Listings with reviews | Listings with bookings |
|---|---:|---:|---:|
| Aug 2025 | 101 | 56 | 75 |
| Sep 2025 | 98 | 47 | 72 |
| Oct 2025 | 124 | 57 | 75 |
| Nov 2025 | 132 | 61 | 77 |
| Dec 2025 | 132 | 57 | 79 |
| Jan 2026 | 104 | 51 | 68 |
| Feb 2026 | 101 | 51 | 72 |
| Mar 2026 | 88 | 40 | 73 |
| Apr 2026 | 104 | 55 | 70 |
| May 2026 | 73 | 37 | 58 |
| Jun 2026 | 25 | 14 | 55 |
| Jul 2026 | 6 | 4 | 44 |

The break is unambiguous between April and July. May is partially observed, June
and July are largely empty.

**Decision:** realised-demand analysis uses **August 2025 – April 2026** (9
months). May–July 2026 appear in descriptive charts with a shaded censored region
and are never used for claims like "occupancy fell to 8%".

The one place the censored months still carry information is *asking price*:
hosts set future prices before bookings arrive, so quoted ADR for May–July is
observable. Even there, the price rise is reported as "asking prices rose", not
"hosts achieved higher rates".

---

## 8. Statistical approach

The sample is small (n = 99) and skewed, so the analysis avoids tests that assume
normality.

| Technique | Use | Why |
|---|---|---|
| Median + IQR | All headline central tendency | ADR and revenue are right-skewed |
| **Bootstrap 95% CI** (10,000 resamples, seed 20261025) | Every headline median | Communicates sampling uncertainty honestly; no normal approximation |
| **Mann–Whitney U** (two-sided) | Entire home vs private room, superhost, pro-managed | Rank-based, no normality assumption |
| **Cliff's delta** | Effect size alongside each U test | p-values alone are uninformative at n ≈ 100; delta shows practical magnitude |
| **Spearman ρ** | Price–occupancy, price–distance, capacity–price | Monotonic, outlier-resistant |
| **Lorenz curve + Gini** | Revenue concentration | Standard, interpretable inequality measure |
| **Within-listing differencing** | Price change Aug 2025 → Apr 2026 | Removes between-listing composition effects |

Multiple comparisons were not formally corrected. With ~10 correlation tests,
one would expect roughly one p < 0.05 by chance, so only results surviving at
p < 0.001 (capacity, room type, revenue–occupancy) are treated as robust.
Results between 0.001 and 0.05 are reported with their p-values and described as
suggestive — they inform the narrative but not the recommendations.

### Why the within-listing test matters

A naive comparison of "January prices" vs "August prices" mixes two things: hosts
raising prices, and a different mix of listings being active. Restricting to the
**98 listings present in both months** and computing each listing's own ratio
isolates repricing.

Result: **94% of listings raised their asking ADR**, median **+24.5%**, while
median occupancy fell **3.1 percentage points**. That is a pricing pattern, not
a demand story — and it still cannot be separated from seasonality over a 9-month
window. The caveat is stated in the finding itself.

---

## 9. Validation

### Automated checks

`src/clean_data.py` runs 24 checks and writes `data/processed/data_quality.json`.
Current state: **24 passed, 0 failed, 0 warnings**. Checks cover parsing, ID
uniqueness, currency, bounding box, sign/range constraints, the
`reserved + available = total` identity, the adjusted-occupancy formula, the
implied FX rate, missingness inventory, postal join coverage, month-key
uniqueness, referential integrity, ADR × nights ≈ revenue, and per-listing month
coverage.

### Cross-table reconciliation

- Reserved nights: monthly sum = TTM sum = **9,588** (exact)
- Revenue: MX$11.51M vs MX$12.00M, **+4.3%**, explained by fees (§5.5)
- DB integrity: `PRAGMA integrity_check` = ok, foreign keys = ok

### Independent recomputation

`src/analyze.py` recomputes headline medians directly from
`data/processed/listings.csv`, separately from the SQL layer. SQL and pandas
results agree. This is a genuine cross-check, not the same code path twice.

### Manual spot checks

- Listing `13845232` confirmed to have 7 monthly rows.
- 5 listings confirmed to have zero reviews (absent from `reviews_monthly`).
- Sum of `reserved_days` reconciled against `ttm_reserved_days`.
- One rural listing confirmed at 47 km and excluded from `v_city_listings`.

---

## 10. From findings to recommendations: the rule engine

`src/generate_business_report.py` converts the analysis into business output.
It is deliberately not a template with hard-written conclusions: each
recommendation is produced by a rule that reads the calculated metrics, so the
same data always yields the same conclusions and a rule that stops matching
stops firing.

### Pipeline of the reporting step

1. **Validate** — the database, `key_metrics.json`, `sql_results.md`, the 24
   quality checks and the 10 figures must exist, and the analysis artefacts
   must not be older than the database (a stale SQL layer is rejected).
2. **Recalculate** — the headline KPIs are re-derived from `v_city_listings`
   and `v_monthly_market` in SQL.
3. **Cross-check** — those KPIs are compared with `reports/key_metrics.json`
   (listing count, median ADR, median occupancy, median and total revenue).
   A mismatch aborts the run.
4. **Recommend** — the rules below are evaluated and scored.
5. **Report and export** — `reports/executive_report.md`,
   `reports/decision_recommendations.csv`, and a `business_recommendations`
   block inside `reports/key_metrics.json`.
6. **Verify** — the written files are re-read and compared with each other
   (section counts, figure links, recommendation order and content). Any
   failure exits non-zero; the report is written only after its content passes
   validation, so a failed pipeline cannot publish a report that looks
   successful.

### Rules and thresholds

The thresholds are **analytical heuristics**, not statistical tests: they
exist so that a recommendation is traceable to a number, and a reviewer who
disagrees with a threshold can change it and re-run.

| Rule | Fires when | Business action it drives |
|---|---|---|
| `pricing_repricing_divergence` | Median within-listing ADR change ≥ +15% **and** median occupancy change ≤ −1.0 pp (Aug 2025 → Apr 2026) | Run a controlled repricing test rather than asserting that price caused the decline |
| `revenue_concentration` | Gini ≥ 0.40 **or** top-10% revenue share ≥ 30% | Profile the top decile and test whether its attributes can be replicated |
| `capacity_price_signal` | \|ρ(ADR, guests)\| ≥ 0.40 and \|ρ(ADR, bedrooms)\| ≥ 0.30 on ≥ 30 listings | Introduce capacity-based rate bands and test them |
| `seasonal_amplitude` | Peak-to-trough monthly occupancy ≥ 6 pp **or** peak-month revenue ≥ 15% above the median month (uncensored window only) | Test a seasonal rate plan against an availability plan |
| `data_completeness_prerequisite` | ≥ 15% of listings missing capacity fields, ≥ 50% with inexact coordinates, or any partial-history listing | Backfill metadata before scaling capacity- or location-based pricing |
| `inventory_mix_room_type` | One room type ≥ 80% of sample revenue **or** ≥ 2.0× median revenue ratio | Review portfolio allocation between room types |

### Scoring and publication cut

`priority_score = 0.5 × rule weight + 0.5 × evidence strength`, where the
weight is a documented analyst judgement (0–100) and the evidence strength is
50 when the observed value sits exactly at its threshold, capped at 100. The
top five scores are published; rules that trigger but rank lower are listed in
an appendix table of the report with their metrics, so nothing is dropped
silently.

### Confidence rubric

Confidence describes the pattern **inside this sample**, never the wider
market. It is computed, not typed: support ≥ 50 listings → 100 points (≥ 30 →
70, otherwise 40); −25 when ≥ 15% of the sample is missing a field the rule
depends on; −25 when fewer than 12 clean months exist; −25 when the claim is
an association rather than a direct measurement; ≥ 80 → High, ≥ 50 → Medium,
otherwise Low.

### What the rules are not allowed to do

No rule infers profitability (there is no cost data), counts confirmed
bookings (there are no booking records), or converts a correlation into a
cause. The pricing rule, for instance, fires on "prices rose while occupancy
did not" and produces an *experiment to run*, never the claim that higher
prices reduced demand.

---

## 11. What this analysis cannot say

This section exists because the most common failure mode in portfolio projects is
over-claiming.

| Tempting claim | Why it is wrong | What is said instead |
|---|---|---|
| "The Querétaro Airbnb market earns MX$X" | 100-listing sample, ~6% of the market | "In this 100-listing sample…" |
| "Location drives price in Querétaro" | ρ = −0.013, approximate coordinates, no colonia field | "No distance gradient is detectable in this sample" |
| "Higher prices cause lower occupancy" | ρ = +0.14 and observational | "There is no evidence that higher asking prices depress occupancy here" |
| "Professional management raises revenue 3.5×" | 17 listings, 2 hosts | "A two-host case study; not a market effect" |
| "Superhosts charge more" | They charge *less* (MX$970 vs MX$1,177) with higher occupancy | "Superhost status is associated with occupancy, not premium pricing" |
| "Revenue per listing is MX$87k" | That is the median of a biased sample | "Median sample listing earned MX$87,335 TTM (95% CI 54,273–116,516)" |
| "Occupancy is 24%" | Calendar occupancy; adjusted is 28% | Both reported, definitions stated |
| "Prices rose 25% because of seasonality" | One 9-month window cannot separate trend from season | "Asking prices rose 24.5%; trend vs season is not identifiable here" |
| "May–July occupancy collapsed" | Right-censored | Months shaded and excluded from demand claims |

### Correlation vs causation

Every segment comparison (superhost, pro-managed, room type, rating band) is
**observational and confounded**. Superhosts may be better operators *or* may
have been selected by Airbnb for high-performing listings. Entire homes earn more
partly because they are bigger and better located. Nothing here identifies a
causal effect, and no recommendation is phrased as "do X to get Y".

### Precision

Bootstrap CIs are wide relative to the effects being discussed. The price CI
(MX$832–1,160) spans 39% of the median. Any finding whose effect size sits inside
that band should be treated as noise — which is why effect sizes and CIs are
reported next to every headline number.

---

## 12. Reproducibility

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

python src/clean_data.py        # 24 checks
python src/build_db.py          # rebuild SQLite from processed CSVs
python src/run_queries.py       # 16 SQL queries → reports/sql_results.md
python src/analyze.py           # bootstrap / tests → reports/key_metrics.json
python src/make_figures.py      # 10 figures
python src/generate_business_report.py  # executive report + recommendations
```

`python src/run_all.py` runs the whole chain; `python -m pytest tests -q` runs
the 15 tests that cover KPI correctness, the recommendation rules, report
generation and the consistency between the report, the CSV and the JSON.

Randomness is seeded (`20261025`), so bootstrap intervals reproduce exactly.
Source hashes are pinned in `data/README.md`; if the provider re-issues the
2026-07 snapshot with different content, the checksums will fail and the numbers
in this repository will no longer be reproducible from the current download.

The executed notebook `notebooks/01_eda.ipynb` reads the processed CSVs and
reproduces the narrative analysis. `reports/key_metrics.json` is the
machine-readable single source of truth for every number quoted in
`reports/findings.md` and the README.
