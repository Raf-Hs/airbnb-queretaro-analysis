# Power BI dashboard specification

**Status: specification, DAX, and theme only. No `.pbix` file is included in this
repository.**

Power BI Desktop could not be installed or driven in the environment where this
project was built (no administrator rights, no interactive desktop). Rather than
claim a dashboard that does not exist, this folder contains everything needed to
build the report in about an hour:

| File | Purpose |
|---|---|
| `dashboard_spec.md` | This document — model, pages, visuals, interactions, build steps, QA |
| `measures.dax` | Every measure and the calculated date table, copy-paste ready |
| `theme.json` | Custom Power BI theme (colours, fonts, card and page defaults) |

The static equivalents of the main views are the PNGs in `reports/figures/`, and
the SQL that feeds them is in `reports/sql_results.md`. Nothing in the dashboard
should introduce a number that is not already reproducible from those files.

---

## 1. Design brief

**Audience:** a hiring manager or analyst who will spend 60–90 seconds on the
report before deciding whether to read the code.

**One sentence the dashboard must communicate:** *in this 99-listing sample,
what a listing is (entire home vs private room, and how many guests it sleeps)
matters far more to revenue than where it sits or what it charges — and asking
prices rose 25% into flat demand.*

**Tone:** editorial, restrained, analytical. No gradients, no 3D, no pie charts,
no gauge visuals. Money in MXN with a thousands separator. Every page carries the
sample-size caveat.

**Canvas:** 1280 × 720 (16:9), 12-column grid with 16 px gutters, 24 px page
margins. Background `#F7F5F2`, visuals on white with a 1 px `#E6E2DC` border and
2 px radius.

**Typography:** Segoe UI Semibold for titles, Segoe UI for labels, Segoe UI Light
for callout numbers. Base label 10 pt, visual title 12 pt, page title 20 pt,
KPI number 26–34 pt.

**Palette** (in `theme.json`):

| Role | Hex |
|---|---|
| Primary / entire homes | `#1F3B57` |
| Positive / private rooms | `#2A9D8F` |
| Highlight / December | `#E9C46A` |
| Warning / censored | `#F4A261` |
| Negative / risk | `#E76F51` |
| Neutral / secondary | `#8D99AE` |
| Canvas | `#F7F5F2` |
| Text | `#2B2D42` |

---

## 2. Data model

Import the three processed CSVs, not the raw JSONL. They are already typed and
audited.

| Table | Source | Grain | Rows |
|---|---|---|---:|
| `Listings` | `data/processed/listings.csv` | listing | 100 |
| `MonthlyRates` | `data/processed/monthly_rates.csv` | listing × month | 1,195 |
| `ReviewsMonthly` | `data/processed/reviews_monthly.csv` | listing × month | 532 |
| `Date` | DAX calculated table (bottom of `measures.dax`) | day | 365 |
| `Measures` | `ROW("x", 0)` calculated table | — | 1 |

### Relationships

```
Date[Date]            1 ──< MonthlyRates[date]
Date[Date]            1 ──< ReviewsMonthly[date]
Listings[listing_id]  1 ──< MonthlyRates[listing_id]
Listings[listing_id]  1 ──< ReviewsMonthly[listing_id]
```

All single-direction. Cross-filter direction left-to-right only.

### Column setup

- `Listings[listing_id]`, `MonthlyRates[listing_id]`, `ReviewsMonthly[listing_id]`
  → **text** in Power Query. They are identifiers, not quantities. Joining on
  numeric IDs works but breaks the moment a leading zero appears.
- `Listings[postal_code]` → text, same reason.
- `MonthlyRates[date]`, `MonthlyRates[month_start]`, `ReviewsMonthly[date]` → date.
- Booleans → True/False (Power BI will import the CSV `True`/`False` as text; set
  type explicitly).
- Hide every raw ID, `listing_url`, and all `l90d_*` columns from report view —
  the 90-day fields overlap the censored window and are deliberately unused.
- Do **not** create a relationship between `Listings` and `ReviewsMonthly` via
  `num_reviews`; that field is a lifetime count, not a key.

### Grain warning (put this in the model notes)

`Listings` performance fields are trailing-twelve-month summaries. They are not
additive over months. A card showing `Median ADR (Quoted)` filtered to July 2026
would still show the annual figure — misleading. Keep listing-grain measures off
Date axes. Month-grain visuals use `MonthlyRates` measures only.

### Calculated columns to add

```dax
-- Listings
Revenue Rank =
RANKX ( ALL ( Listings ), Listings[revenue_mxn], , DESC, DENSE )

Revenue Decile =
ROUNDUP ( DIVIDE ( [Revenue Rank], COUNTROWS ( ALL ( Listings ) ) ) * 10, 0 )

Price Band =
VAR P = Listings[price_mxn]
RETURN
    SWITCH (
        TRUE (),
        P < 500,  "Under 500",
        P < 750,  "500–749",
        P < 1000, "750–999",
        P < 1500, "1,000–1,499",
        P < 2500, "1,500–2,499",
        "2,500+"
    )

Price Band Sort =
SWITCH ( Listings[Price Band],
    "Under 500", 1, "500–749", 2, "750–999", 3,
    "1,000–1,499", 4, "1,500–2,499", 5, "2,500+", 6 )
-- then Sort [Price Band] by [Price Band Sort]
```

`Revenue Decile` is used for the concentration bar chart, which is a native
substitute for a Lorenz curve (see page 4).

---

## 3. Page 1 — Market overview

**Purpose:** answer "what does this market look like and how big is the sample?"
in one screen.

**Header:** title *Querétaro short-term rentals*; subtitle *AirROI snapshot
2026-07 · 100-listing sample · Aug 2025 – Jul 2026*.

### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Title + subtitle                                     [Slicer: Room type]│
├───────────┬───────────┬───────────┬───────────┬──────────────────────────┤
│ 99        │ MX$1,029  │ 24.1%     │ MX$87,335 │ MX$12.0M                 │
│ listings  │ median ADR│ occupancy │ median rev│ sample revenue (99)      │
├───────────┴───────────┴───────────┴───────────┴──────────────────────────┤
│ ADR distribution (column)              │ Listings by distance band (bar)  │
│                                        │                                  │
├────────────────────────────────────────┴──────────────────────────────────┤
│ Map: listing locations coloured by room type, sized by TTM revenue        │
├──────────────────────────────────────────────────────────────────────────┤
│ Footnote: sample ≠ market · source/licence · 51.5% within 1 km            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Visuals

| # | Visual | Fields | Measures | Notes |
|---|---|---|---|---|
| 1 | Card ×5 | — | `City Listing Count`, `Median ADR (Quoted)`, `Median Calendar Occupancy`, `Median TTM Revenue`, `Total TTM Revenue` | City filter: use `City Listing Count`; for the other four, add a page-level filter `is_city_core = True` |
| 2 | Clustered column | `Listings[Price Band]` | `Listing Count` | Sort by `Price Band Sort`; title "Asking rates are right-skewed" |
| 3 | Clustered bar | `Listings[distance_band]` | `Listing Count` | Sort by distance; title "Half the sample sits within 1 km of the centro" |
| 4 | Map | Latitude / Longitude, legend `room_type`, size `revenue_mxn`, tooltip listing name + ADR + occupancy | — | Use Azure Maps if the tenant allows it; otherwise drop the map and place `reports/figures/03_listing_map.png` as an image. Do not fake a map with a scatter. |
| 5 | Text box | — | — | Footnote, 8 pt, grey |

### Slicers

- `room_type` (tile, 2 options, multi-select)
- `superhost` (tile)
- `distance_band` (dropdown)
- `Price Band` (between slider) — optional; place in a collapsible bookmark panel if space is tight.

### Interactions

- Slicers filter all visuals on the page.
- Map → other visuals: **off** (a spatial selection would produce confusing cross-highlights on a bar chart).
- Price distribution column → cross-highlight the distance bar: **on**.

### Footnote text (verbatim)

> 100 listings sampled by AirROI; 99 inside the 15 km city core. This is not the
> full market (~1,733 active listings). Money in MXN, trailing twelve months.
> Realised-demand claims exclude May–Jul 2026 (right-censored). Source: AirROI
> Data Portal 2026-07, CC BY-NC 4.0.

---

## 4. Page 2 — What separates the earners

**Purpose:** the analytical core. Show that room type and capacity dominate, and
that location and price level do not.

### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Title: What a listing is matters more than where it is                    │
├──────────────────────────────────┬───────────────────────────────────────┤
│ Scatter: ADR vs occupancy        │ Matrix: segment scorecard             │
│ size = revenue, colour = room    │ room_type × measures                  │
├──────────────────────────────────┼───────────────────────────────────────┤
│ Bar: median revenue by room type │ Bar: median ADR by bedroom band       │
├──────────────────────────────────┴───────────────────────────────────────┤
│ Callout strip: capacity coverage 80% · distance ρ −0.01 · price ρ +0.14  │
└──────────────────────────────────────────────────────────────────────────┘
```

### Visuals

| # | Visual | Fields | Measures | Notes |
|---|---|---|---|---|
| 1 | Scatter | X `price_mxn`, Y `occupancy`, size `revenue_mxn`, legend `room_type`, detail `listing_name` | — | Set X axis to log scale? No — a linear axis with the 6 high-price listings visible is more honest. Add a reference line at median ADR and median occupancy. Title: "Higher asking prices do not visibly depress occupancy (ρ = +0.14)" |
| 2 | Matrix | Rows `room_type`; Values: `Listing Count`, `Median ADR (Quoted)`, `Median Calendar Occupancy`, `Median TTM Revenue`, `Entire Home Revenue Share` | as listed | Conditional formatting: data bars on ADR and revenue, colour scale on occupancy. Totals off (a "total" row would mix segments). |
| 3 | Clustered bar | `room_type` | `Median TTM Revenue` | Title "Entire homes earn 4.2× a private room"; data labels on |
| 4 | Clustered column | `bedroom_band` | `Median ADR (Quoted)` | Exclude `Unknown` with a visual-level filter; subtitle "n = 80 listings with bedroom metadata" |
| 5 | Card row / text | — | `Capacity Metadata Coverage` | Show as text: "19 listings (17 private rooms) omit bedrooms — excluded from this chart, not imputed" |

### Callout strip

Use a shape with three text boxes, or a single multi-row card:

- **Capacity**: guests ρ = +0.57 (p < 0.001), n = 80
- **Location**: distance ρ = −0.01 (p = 0.90), n = 99
- **Price**: price ↔ occupancy ρ = +0.14 (p = 0.17), n = 99

### Interactions

- Matrix row click filters the two bar charts: **on**.
- Scatter selection filters the matrix: **off** (brushing a cloud of points into a segment table invites over-reading).
- Add a tooltip page (see §8) so hovering a scatter point shows listing name, room type, ADR, occupancy, revenue, and "55 of 100 listings have approximate coordinates".

### What must not appear on this page

- A "best neighbourhood" ranking. There is no neighbourhood field.
- A regression line or R² implying a model was fitted.
- A combined "score" or index across segments.

---

## 5. Page 3 — Seasonality and pricing

**Purpose:** show a shallow seasonal curve, a December peak, and a coordinated
rise in asking prices — while making the censored months impossible to
misread.

### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Title: Shallow seasonality, rising asking prices                          │
│ Toggle: [Complete months] / [All months incl. censored]                   │
├──────────────────────────────────────────────────────────────────────────┤
│ Line: calendar occupancy by month  ┃ shaded May–Jul 2026                  │
├──────────────────────────────────────────────────────────────────────────┤
│ Line: quoted ADR vs realised ADR   ┃ shaded May–Jul 2026                  │
├──────────────────────────────────────────────────────────────────────────┤
│ Column: monthly revenue            │ Cards: ADR index Apr · occ Δ pts     │
├──────────────────────────────────────────────────────────────────────────┤
│ Table: month, occupancy, quoted ADR, realised ADR, revenue, reviews       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Visuals

| # | Visual | Fields | Measures | Notes |
|---|---|---|---|---|
| 1 | Line | X `Date[Month Start]` | `Calendar Occupancy (Monthly)` | Y axis 0–40%, not auto — auto-scaling exaggerates the dip. Add a constant line at the 9-month average (26.5%). |
| 2 | Line (two series) | X `Date[Month Start]`; legend via field parameter or two measures | `Quoted ADR (Monthly, Median)`, `Realised ADR` | Quoted = solid navy, realised = dashed teal. Title "Asking prices rose 25% within the same listings" |
| 3 | Column | X `Date[Month Start]` | `Monthly Revenue` | Colour December `#E9C46A`, censored months `#F4A261` at 40% transparency. Data labels off; tooltip on. |
| 4 | Card ×2 | — | `ADR Index vs Aug 2025` (filter Apr 2026), `Occupancy Change vs Aug 2025 (pts)` (filter Apr 2026) | Format index as 124.5, change as −3.1 pts |
| 5 | Table | `month_label`, `occupancy`, `adr_quoted_mxn`, `adr_booked_mxn`, `revenue_mxn`, `num_reviews` | — | 12 rows; conditional formatting on `num_reviews` to make the collapse visible |

### The censored region — implementation

Power BI has no native "shaded time range" on a line chart. Use this recipe:

1. Create a bookmark group with a rectangle shape (`#F4A261`, 15% transparency,
   no border) positioned over May–Jul 2026 on the plot area.
2. Group the shape with the visual so it moves together when resized.
3. Add a text label inside the shape: *"Right-censored: bookings and reviews
   incomplete"* (8 pt, `#8A5A2B`).
4. Because shapes do not scale with axis ranges, lock the visual's X axis to the
   full `2025-08-01 … 2026-07-01` window and disable "Auto-scale".
5. Add a second bookmark, "Complete months only", that applies a page filter
   `Date[Is Complete] = True` and hides the shape. A single toggle button switches
   bookmarks.

**Do not** simply cut the axis at April. The censored months are evidence and
should be visible; they must be visibly excluded from claims, not hidden.

### Interactions

- Hovering a month cross-highlights the table row: **on**.
- Table → line charts: **off** (a 12-row table as a filter source adds no value).
- Toggle button switches bookmarks; do not use a slicer for `Is Complete`, because
  a slicer would sit in the filter card and be easy to overlook.

---

## 6. Page 4 — Concentration and hosts

**Purpose:** show that revenue is concentrated and that the largest host is a
sampling artefact as much as a market fact.

### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Title: Half the revenue sits with a fifth of the listings                 │
├────────────┬────────────┬────────────┬───────────────────────────────────┤
│ 31.6%      │ 50.5%      │ 18.9%      │ 0.488                             │
│ top 10%    │ top 20%    │ top host   │ Gini (Python-computed)            │
├────────────┴────────────┴────────────┴───────────────────────────────────┤
│ Bar: revenue share by decile        │ Table: top hosts                  │
├─────────────────────────────────────┴────────────────────────────────────┤
│ Image: Lorenz curve (reports/figures/08_revenue_concentration.png)       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Visuals

| # | Visual | Fields | Measures | Notes |
|---|---|---|---|---|
| 1 | Card ×4 | — | `Top 10% Revenue Share`, `Top 20% Revenue Share`, `Top Host Revenue Share`, static text "0.488" | The Gini card is a text box, not a measure — see the note at the end of `measures.dax` |
| 2 | Clustered column | `Revenue Decile` | `Total TTM Revenue` | Title "Revenue by decile"; decile 10 is ~31.6% of revenue. This is the native stand-in for a Lorenz curve. |
| 3 | Table | `host_name`, `host_id`; values `Listing Count`, `Total TTM Revenue`, `Top Host Revenue Share` | as listed | Top 8 hosts by revenue. Add a data-bar column. |
| 4 | Image | `reports/figures/08_revenue_concentration.png` | — | Lorenz curve and top-host annotation; generated in Python |
| 5 | Text box | — | — | "Largest host: 11 listings, all flagged professional_management. In a 100-listing sample this is a sampling artefact, not a market share." |

### Note on Gini

The Gini coefficient is computed once in `src/analyze.py` and stored in
`reports/key_metrics.json` (`0.4876`). Recomputing it in DAX is possible but
fragile; a wrong Lorenz implementation is worse than an honest static annotation.
If you must have it dynamic, compute it in Power Query against the selected
listings, not in a visual-level measure.

---

## 7. Page 5 — Method and data quality

**Purpose:** let a sceptical reviewer check the project's claims without leaving
the report.

### Content blocks (text boxes, 10–11 pt)

1. **Source** — AirROI Data Portal, Querétaro, release 2026-07, downloaded
   2026-10-25, CC BY-NC 4.0. Inside Airbnb has no Querétaro dataset.
2. **Sample** — 100 listings, 51 hosts (50 in the city core), 99 in the 15 km city core. ~6% of the
   ~1,733 active market. No market-size or market-share claims.
3. **Definitions** — quoted ADR vs realised ADR; calendar occupancy vs adjusted
   occupancy; `blocked_days` is a subset of available days; revenue excludes some
   fees (+4.3% vs TTM revenue).
4. **Censoring** — May–Jul 2026 excluded from realised-demand claims; review
   volume 101 → 73 → 25 → 6.
5. **Scope decisions** — one rural listing (47 km) excluded from city statistics
   but retained; one listing with 7 of 12 months flagged; 19 listings without
   bedroom metadata not imputed; 55 listings with approximate coordinates.
6. **Licence** — CC BY-NC 4.0, attribution required, no commercial use.

### Data-quality table

Optional but recommended: import `data/processed/data_quality.json` as a table
`DataQuality` (Power Query ▸ JSON ▸ expand `checks`). Visual: table with
`check`, `status`, `detail`; filter `status = "pass"`; card `COUNTROWS` = 24.

### Definition table (enter manually)

| Term | Definition |
|---|---|
| Quoted ADR | Asking nightly rate over TTM; a pricing decision |
| Realised ADR | Nightly-rate revenue ÷ reserved nights |
| Calendar occupancy | Reserved nights ÷ all calendar nights |
| Adjusted occupancy | Reserved nights ÷ (all nights − host-blocked nights) |
| RevPAR | Revenue ÷ all calendar nights |
| Censored month | Month after 2026-04 where bookings/reviews are incomplete |

---

## 8. Drillthrough page — listing detail

Create a hidden page, `Listing detail`, with a drillthrough field
`Listings[listing_id]`. Add:

- Card row: listing name, host name, room type, bedroom band, postal code, distance to centro
- Cards: ADR, occupancy, adjusted occupancy, TTM revenue, RevPAR
- Line: monthly `adr_quoted_mxn` and `adr_booked_mxn`
- Column: monthly `reserved_days`
- Text: "Coordinates are approximate for this listing" when `location_is_exact = FALSE`
- Field `listing_url` as a web URL button (set data category to Web URL)

This is the one place where a reviewer can see an individual listing without
leaving the report. It also demonstrates drillthrough, which is a common
interview talking point.

---

## 9. Tooltip page

Create a 320 × 240 tooltip page, `Listing tooltip`, with
`Listings[listing_id]` as the tooltip field:

- Listing name (bold), room type, bedroom band
- ADR, occupancy, revenue
- "Distance: X.X km · approximate location" where applicable

Attach it to the scatter on page 2 and the map on page 1.

---

## 10. Build steps

1. **Install** Power BI Desktop (Microsoft Store version works without admin
   rights on most managed Windows machines).
2. **Get data** ▸ Text/CSV ▸ `data/processed/listings.csv` → Transform Data.
   - Set `listing_id`, `postal_code` to Text.
   - Set booleans to True/False.
   - Remove `l90d_*` columns.
   - Rename query to `Listings`.
3. Repeat for `monthly_rates.csv` → `MonthlyRates` (IDs to Text; `date`,
   `month_start` to Date) and `reviews_monthly.csv` → `ReviewsMonthly`.
4. **Modeling** ▸ New table → paste the `Date` definition from `measures.dax`.
   Mark as date table. Sort `Month` by `Month Start`, `Month Short` by
   `Month Number`.
5. **New table** → `Measures = ROW ( "x", 0 )`. Hide the column.
6. **Relationships** ▸ create the four shown in §2. Verify cardinality is 1:* and
   cross-filter is single.
7. **Paste measures** from `measures.dax` into the `Measures` table. Set format
   strings per the header comment.
8. **Add calculated columns** from §2 to `Listings`.
9. **View** ▸ Themes ▸ Browse for themes ▸ `powerbi/theme.json`.
10. **Build pages** 1–5 in order, following the layouts. Set page size to
    1280 × 720, canvas background `#F7F5F2`.
11. **Bookmarks**: create "All months" and "Complete months only" on page 3.
12. **Drillthrough and tooltip pages** per §8–§9.
13. **Save as** `powerbi/queretaro_airbnb.pbix` — then decide whether to commit
    it. A `.pbix` is a binary; if it is not in the repo, say so in the README
    (this project does not ship one).
14. **QA** against §11 before publishing.

### Refresh

The CSVs are static. For a refreshable model, point Power Query at the SQLite
database instead (ODBC driver required) or at the raw JSONL files. Neither is
necessary for a portfolio piece; document whichever you choose.

---

## 11. QA checklist

Before sharing, verify every number against `reports/key_metrics.json`:

| Check | Expected |
|---|---|
| City listing count | 99 |
| Median ADR | MX$1,029.2 |
| Median calendar occupancy | 24.1% |
| Median TTM revenue | MX$87,335 |
| Total TTM revenue | MX$11,995,861 |
| Entire home share of listings | 75.8% |
| Entire home share of revenue | 92.2% |
| Room-type ADR ratio | 1.78× |
| Room-type revenue ratio | 4.20× |
| Superhost occupancy | 31.5% |
| Non-superhost occupancy | 18.0% |
| Pro-managed listings / hosts | 17 / 2 |
| Management revenue ratio | 3.51× |
| Top 10% revenue share | 31.6% |
| Top 20% revenue share | 50.5% |
| Largest host listings / share | 11 / 18.9% |
| Gini | 0.488 |
| Aug 2025 occupancy | 33.6% |
| Dec 2025 revenue | MX$1,342,015 |
| Apr 2026 occupancy | 25.1% |
| ADR index Apr 2026 | 124.5 |
| Occupancy change Aug→Apr | −3.1 pts |
| Reserved nights (TTM) | 9,588 |

Also confirm:

- [ ] Page 1 footnote is visible without scrolling at 100% zoom.
- [ ] Censored shading aligns exactly with May–Jul 2026 on both line charts.
- [ ] No visual uses `l90d_*` fields.
- [ ] No visual implies a neighbourhood field exists.
- [ ] The pro-management visual carries the "two-host case study" note.
- [ ] Every page states the sample size.
- [ ] Tab order follows reading order (View ▸ Selection ▸ Tab order).
- [ ] Alt text is set on the map, the Lorenz image, and every scatter.
- [ ] Colours are distinguishable in deuteranopia (navy/teal/sand is safe;
      avoid red/green pairings).

---

## 12. What this dashboard deliberately does not do

| Not included | Why |
|---|---|
| Market-size or market-share KPIs | 100-listing sample |
| A "best area" ranking | No neighbourhood field; postal codes are too coarse |
| Occupancy or revenue forecasts | 12 months, one snapshot, censored tail |
| A revenue simulator | Would imply causal price/occupancy elasticities the data cannot support |
| An R² or regression line | No model was fitted; correlations are rank-based and descriptive |
| A Gini measure in DAX | Computed once in Python; a fragile dynamic version would be worse |
| A `.pbix` in the repository | Not produced in this environment; documented instead of faked |

---

## 13. If you only have 10 minutes

Build page 2 only: the room-type matrix, the ADR/occupancy scatter, and the two
bar charts. That page carries the argument. Pages 1, 3, 4, and 5 are supporting
evidence and provenance.
