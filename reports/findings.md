# Findings

Airbnb short-term rentals in Santiago de Querétaro · AirROI snapshot `2026-07` ·
100-listing sample (99 in city statistics) · 12 months to July 2026, with
realised-demand claims restricted to **Aug 2025 – Apr 2026** because the last
three months are right-censored.

Every number below is reproducible from `reports/key_metrics.json` and the SQL in
`reports/sql_results.md`. Percentages are rounded; money is MXN.

---

## Headline

| Metric (99-listing city sample) | Median | 95% bootstrap CI |
|---|---:|---|
| Quoted ADR, MXN/night | **1,029** | 832 – 1,160 |
| Calendar occupancy | **24.1%** | 18.1% – 31.5% |
| Trailing-12-month revenue, MXN | **87,335** | 54,273 – 116,516 |
| RevPAR, MXN per available night | **233** | 149 – 290 |

Total revenue across the 99 city listings: **MX$11,995,861**. Mean ADR is
MX$1,303, well above the median — the distribution is right-skewed by a handful
of large homes.

**The one-sentence version:** in this sample, *what* a listing is (entire home vs
private room, and how many people it sleeps) explains far more about revenue than
*where* it is or *what it charges*; the market's real constraint is filling
nights, not setting a high price.

---

## Finding 1 — Room type is the dominant revenue split

![Price distribution by room type](figures/01_price_distribution.png)

| | Entire home | Private room | Ratio |
|---|---:|---:|---:|
| Listings | 75 (75.8%) | 24 (24.2%) | — |
| Median ADR | MX$1,173 | MX$658 | **1.78×** |
| Median occupancy | 30.7% | 12.5% | **2.46×** |
| Median TTM revenue | MX$128,135 | MX$30,492 | **4.20×** |
| Share of sample revenue | **92.2%** | 7.8% | — |

Mann–Whitney p-values are 2.7 × 10⁻⁷ (ADR), 0.0016 (occupancy), and
5.5 × 10⁻⁷ (revenue). Cliff's delta is 0.70 for ADR and 0.68 for revenue —
large effects, not marginal ones.

The revenue gap (4.2×) is much bigger than the price gap (1.8×) because entire
homes win on **both** price and occupancy. A private room at MX$658 that sells
12.5% of nights would need a fundamentally different product — not a different
price — to approach an entire home's revenue. This is a structural gap, not a
pricing tip.

**Caveat:** 17 of the 24 private rooms also lack bedroom metadata, so this
segment is thinner on detail than entire homes. The comparison is still valid
because it uses price, occupancy and revenue — none of which are missing.

**Operator implication:** if the goal is revenue rather than occupancy, the
room-type decision dominates the pricing decision. This is a descriptive
statement about a sample, not a causal claim that converting a room to an entire
unit would yield 4.2×.

---

## Finding 2 — Capacity is the clearest visible price driver

![Capacity and price](figures/02_capacity_and_price.png)

| Relation | Spearman ρ | p | n |
|---|---:|---:|---:|
| ADR ↔ guests | **+0.57** | 4.4 × 10⁻⁸ | 80 |
| ADR ↔ bedrooms | **+0.47** | 8.9 × 10⁻⁶ | 80 |
| ADR ↔ baths | +0.53 | 1.9 × 10⁻⁸ | 99 |

By bedroom band (listings with metadata only):

| Band | n | Mean ADR | Mean occupancy | Mean TTM revenue | ADR per guest |
|---|---:|---:|---:|---:|---:|
| Studio / 1 BR | 39 | MX$972 | 29.9% | MX$109,559 | **MX$458** |
| 2 BR | 25 | MX$1,175 | 31.4% | MX$148,919 | MX$292 |
| 3 BR | 12 | MX$1,818 | 24.8% | MX$137,384 | MX$314 |
| 4+ BR | 4 | MX$6,998 | 17.9% | MX$420,174 | MX$504 |

Two things stand out:

1. **Price per guest is U-shaped.** Studios and 1-bedrooms extract the most per
   guest (MX$458); 2-bedrooms the least (MX$292). A 2BR does not simply double a
   1BR's price — it splits the same wallet across more beds.
2. **The 4+ BR band is four listings.** Its MX$6,998 mean ADR is driven by two
   large homes and the rural estate. It is a real segment but far too small to
   generalise from.

**Caveat:** 19 listings (17 private rooms) have no bedroom count and are excluded
from this table. They are not missing at random, so the bands describe
metadata-complete listings. Guest counts are missing for the same 19, which is
why the correlations use n = 80.

---

## Finding 3 — There is no detectable distance–price gradient

![Listings and distance to centro](figures/03_listing_map.png)

![Distance and price](figures/04_distance_and_price.png)

| Relation | Spearman ρ | p | n |
|---|---:|---:|---:|
| ADR ↔ distance to Plaza de Armas | **−0.013** | 0.900 | 99 |
| ADR ↔ distance, entire homes only | +0.058 | 0.621 | 71 |

That is a null result, and a fairly clean one. 51.5% of city listings sit within
1 km of the centro, yet proximity does not predict asking price:

| Distance band | n | Median ADR | Mean occupancy | Median TTM revenue |
|---|---:|---:|---:|---:|
| Centro (0–1 km) | 51 | MX$970 | 27.6% | MX$93,860 |
| Centro extendido (1–2 km) | 18 | MX$1,315 | 17.9% | MX$46,119 |
| Corona urbana (2–4 km) | 15 | MX$1,219 | 36.8% | MX$155,279 |
| Periferia (4–8 km) | 6 | MX$1,046 | 26.6% | MX$99,729 |
| Zona metropolitana (8–15 km) | 9 | MX$779 | 20.6% | MX$49,242 |

The centro has the **lowest** median ADR of the inner bands. That is mostly
composition: the centre carries a large share of small units and private rooms,
while the 2–4 km ring is dominated by larger entire homes.

**Important anomaly:** the 1–2 km band's low occupancy (17.9% mean) is not a
neighbourhood effect. Seven of the 15 entire homes there each recorded fewer than
30 reserved nights in twelve months, four of them with **zero blocked days** —
listings that look dormant or delisted-off-platform rather than genuinely
unbookable. With n = 18 in the band, those seven drag the mean. This is exactly
the kind of artefact a single-number "best area" ranking would hide.

**Why this is reported as "no gradient" and not "location does not matter":**
55 listings have approximate coordinates (6 more unknown), the distance is
straight-line rather than travel time, and the data has no colonia field. All
three attenuate any real effect. The honest conclusion is that **this dataset
cannot identify a location premium**, not that one does not exist.

---

## Finding 4 — Price level is not what limits occupancy

![Price vs occupancy](figures/06_price_vs_occupancy.png)

![Correlation matrix](figures/09_correlation_matrix.png)

| Relation | Spearman ρ | p |
|---|---:|---:|
| ADR ↔ occupancy | +0.14 | 0.165 |
| Revenue ↔ occupancy | **+0.83** | 5.4 × 10⁻²⁶ |
| Revenue ↔ ADR | +0.60 | 3.3 × 10⁻¹¹ |
| Occupancy ↔ lifetime reviews | +0.39 | 6.7 × 10⁻⁵ |
| Rating ↔ occupancy | +0.14 | 0.179 |
| Rating ↔ ADR | +0.07 | 0.510 |

Higher-priced listings in this sample are **not** less occupied. If anything the
sign is positive, though it is not statistically distinguishable from zero at
n = 99. Revenue, by contrast, tracks occupancy extremely closely — and tracks
price less closely.

Read together: two listings with the same price can differ by 20+ occupancy
points, and the empty one is not empty because it is expensive. The variance is
elsewhere: room type, capacity, management, listing age, and factors this
dataset does not capture.

**Caveat:** this is not evidence that a given host could raise prices without
losing bookings. It is a cross-sectional association across listings with
different products. A within-listing price experiment would be needed to answer
the causal question, and the seasonal confound in §6 shows why that is hard here.

---

## Finding 5 — Seasonality is real but shallow; December is the only clear peak

![Seasonality](figures/05_seasonality.png)

Complete window (Aug 2025 – Apr 2026):

| Month | Occupancy | Median quoted ADR | Median booked ADR | Revenue |
|---|---:|---:|---:|---:|
| Aug 2025 | 33.6% | MX$842 | MX$949 | MX$1,104,260 |
| Sep 2025 | 29.9% | MX$916 | MX$970 | MX$1,077,486 |
| Oct 2025 | 32.3% | MX$904 | MX$904 | MX$1,067,247 |
| Nov 2025 | 31.0% | MX$935 | MX$916 | MX$1,089,135 |
| **Dec 2025** | **33.9%** | MX$933 | MX$1,001 | **MX$1,342,015** |
| Jan 2026 | 27.0% | MX$984 | MX$958 | MX$905,670 |
| Feb 2026 | 31.9% | MX$1,017 | MX$1,023 | MX$1,006,751 |
| Mar 2026 | 32.8% | MX$1,060 | MX$1,059 | MX$1,209,558 |
| Apr 2026 | 25.1% | MX$1,150 | MX$1,198 | MX$1,037,661 |

- Occupancy stays inside a **25.1%–33.9%** band for nine months — an 8.8
  percentage-point range. There is no dramatic high season in this sample.
- December is the only month that is clearly first on both occupancy and revenue:
  MX$1.34M, **11.7%** of 12-month calendar revenue (MX$11.51M; one month in twelve
  would be 8.3%).
- January is the weakest month by revenue (MX$906k), consistent with post-holiday
  demand; April is the weakest by occupancy.
- Peak-to-trough monthly revenue is only **1.48×** (Dec vs Jan).

**Caveat:** May–July 2026 are shaded and excluded — their apparent collapse
(19.8% → 14.1% → 8.3%) is an observation artefact, not demand. See
`reports/data_quality.md` §5.

**Operator implication:** Querétaro is not a market where a host can rely on a
short, violent high season. Revenue planning should assume roughly flat demand
with a December bump, not a summer cliff.

---

## Finding 6 — Hosts raised asking prices 25% into flat demand

![Within-listing repricing](figures/10_within_listing_repricing.png)

This is the one analysis that controls for composition. For each of the **98
listings present in both Aug 2025 and Apr 2026**, the price index is that
listing's own ADR relative to its own August ADR.

| Measure | Value |
|---|---:|
| Paired listings | 98 |
| Share that raised asking ADR | **93.9%** |
| Median ADR change, Aug → Apr | **+24.5%** |
| Mean ADR change | +26.0% |
| Median occupancy change | **−3.1 percentage points** |
| Median price index by Apr 2026 | 124.5 |
| Median price index by Jul 2026 | 126.4 |

The same properties, not a different mix of properties, became ~25% more
expensive in asking terms over nine months while their occupancy drifted slightly
down. (The market-wide median quoted ADR rose from MX$842 in August to MX$1,150 in
April, +36.6%, but that is a median across a changing set of listings and is not
directly comparable to a within-listing change. The 24.5% paired figure is the
valid one.)

**What this does and does not show:**

- It **does** show a broad, coordinated upward repricing in asking rates.
- It **does not** show that hosts succeeded — realised ADR rose too, but only
  because the same nights sold; occupancy is the outcome that matters, and it
  did not rise.
- It **cannot** separate a deliberate repricing strategy from seasonality or from
  a general market-wide rate increase, because the window is only nine months and
  there is no pre-period baseline.

**Operator implication:** in a market where nearly every host raises rates and
occupancy does not follow, pricing discipline is a differentiator. The data
supports *watching* this, not a prescription to cut prices.

---

## Finding 7 — Revenue is concentrated, and the concentration is not just size

![Revenue concentration](figures/08_revenue_concentration.png)

| Measure | Value |
|---|---:|
| Gini of TTM revenue | **0.488** |
| Top 10% of listings' share of sample revenue | **31.6%** |
| Top 20% share | **50.5%** |
| Top 50% share | 85.1% |
| Largest host: listings / revenue share | 11 listings / **18.9%** |
| Largest host revenue | MX$2,263,523 |

A Gini of 0.49 in a sample this small is high. Half the money sits with 20 of 99
listings. The largest host operates 11 listings — all flagged
`professional_management` — and alone accounts for nearly a fifth of sample
revenue.

**Caveat:** 11 listings from one host in a 100-listing sample is a sampling
artefact as much as a market fact. The provider's sample may over-represent
professional stock, which would inflate concentration. Do not read 18.9% as this
host's market share.

---

## Finding 8 — Superhosts sell more nights, not higher prices

![Segment scorecard](figures/07_segment_scorecard.png)

| | Superhost | Not superhost | p (Mann–Whitney) |
|---|---:|---:|---:|
| Listings | 55 | 44 | — |
| Median ADR | MX$970 | MX$1,177 | 0.326 |
| Median occupancy | **31.5%** | 18.0% | **0.014** |
| Median TTM revenue | MX$102,070 | MX$61,630 | 0.214 |
| Mean rating | 4.84 | 4.72 | — |

Superhosts charge **less** and fill **more** nights. The occupancy difference is
statistically significant with a moderate effect size (Cliff's delta 0.29); the
revenue difference is not significant (p = 0.21), largely because occupancy gains
are offset by lower rates.

**Caveat:** superhost status is not randomly assigned. Airbnb awards it on
response rate, cancellation rate, and rating history, and it may also be
correlated with listing type, age, and location. This is an association, not a
badge effect.

---

## Finding 9 — "Professional management" is a two-host case study

| | Pro-managed | Independent | Ratio |
|---|---:|---:|---:|
| Listings | 17 | 82 | — |
| Distinct hosts | **2** | 49 | — |
| Median ADR | MX$1,445 | MX$846 | 1.71× |
| Median occupancy | 35.3% | 19.5% | 1.81× |
| Median TTM revenue | **MX$212,004** | MX$60,345 | **3.51×** |
| Mean length of stay | 8.9 nights | 5.6 nights | — |

The 3.5× revenue gap is the largest segment difference in the study, and it is
**not usable as a market finding**. Seventeen listings operated by two hosts is a
case study of two businesses. Those businesses do not simply run bigger units —
their median listing is *smaller* (1 bedroom, 2 guests) than the independent
median (2 bedrooms, 4 guests), yet they charge more and hold guests longer
(median 6.3 vs 4.2 nights). Premium pricing on compact units is a plausible
strategy, but with two operators it is equally plausible that the flag captures
two well-run businesses rather than a management effect. Presenting this as
"professional management triples revenue" would be the single easiest way to
mislead a reader of this project, so it is labelled everywhere as a two-host
comparison.

---

## What did not explain anything

| Candidate | Result | Verdict |
|---|---|---|
| Guest rating (overall) | ρ = +0.14 with occupancy (p = 0.18); ρ = +0.07 with ADR (p = 0.51) | No signal |
| Distance to centro | ρ = −0.013 (p = 0.90) | No detectable gradient |
| Price level | ρ = +0.14 with occupancy (p = 0.17) | No evidence that higher prices suppress demand |
| Review count | ρ = +0.39 with occupancy (p < 0.001) | Signal, but confounded with listing age |

Ratings are heavily compressed: median 4.83, with an interquartile range of
roughly 4.74–4.89. In a market where nearly everyone scores above 4.7, rating
variance carries almost no information. A null result here means **the metric is
uninformative**, not that quality does not matter to guests.

---

## Secondary observations

**Postal-code areas are internally heterogeneous.** CP 76000 (n = 18) has the
highest mean ADR (MX$2,198) but mean occupancy of only 22.3%; CP 76020 (n = 29)
has lower ADR (MX$1,069) and higher occupancy (30.5%). CP 76165 (n = 7) is the
weakest pocket: mean ADR MX$588, occupancy 19.8%, one entire home and six private
rooms. These are postal polygons, not neighbourhoods — use them to see
heterogeneity, not to rank areas.

**Length of stay is not monotonic with performance.** 5–6 night stays show the
highest calendar occupancy (32.2%) and 7+ night stays the highest adjusted
occupancy (39.6%). Sub-3-night stays have the lowest occupancy (21.0%); the
3–4-night band carries the highest mean ADR (MX$1,605). Minimum-stay policy is a
lever worth testing, but this cross-section cannot separate policy from property
type.

**The 90-day fields were not used.** They overlap the censored window, so mixing
them with 12-month metrics would compare incompatible periods.

---

## Recommendations for an operator (conditional, not causal)

These follow from the descriptive patterns above. None is a validated
intervention.

1. **Underwrite on occupancy, not ADR.** Revenue correlates with occupancy at
   ρ = 0.83 and with price at ρ = 0.60. The arithmetic is unforgiving: at a 24.1%
   occupancy base, a 10% higher rate adds 10% revenue, while 10 more occupied
   points adds about 41%. Rate matters, but nights sold dominate.
2. **Treat room type and capacity as the primary revenue decision.** The
   entire-home/private-room gap (4.2× revenue) dwarfs anything pricing can do
   inside a segment.
3. **Do not pay a premium for centro proximity on distance alone.** The sample
   shows no gradient, and the centro's low median ADR is driven by unit mix.
   Verify with actual travel time and colonia-level data before committing.
4. **Plan for a shallow seasonal curve with a December bump.** Peak-to-trough
   revenue is 1.48×; a business plan that assumes a strong summer high season is
   not supported.
5. **Watch repricing behaviour.** With 94% of hosts raising asking rates into
   flat occupancy, rate discipline (and not just rate level) is where a new
   entrant can differentiate.
6. **Model portfolio risk, not single-unit risk.** With a Gini of 0.49, the top
   quintile earns half the revenue. A single unit is a high-variance bet.

---

## Limitations

Carried forward from `docs/methodology.md` §10 and `reports/data_quality.md`:

1. **100-listing sample, not the market.** ~6% of ~1,733 active listings.
   No market-size, market-share, or total-revenue claims.
2. **No neighbourhood field.** Distance bands and postal polygons are proxies.
3. **55 listings have approximate coordinates.**
4. **Right-censored tail.** May–Jul 2026 excluded from demand claims.
5. **Quoted vs realised prices are distinct.** Revenue excludes some fees
   (+4.3% gap vs TTM revenue).
6. **One partial-history listing, one rural outlier.**
7. **Observational data.** No causal identification; segment comparisons are
   confounded.
8. **Snapshot is ~3 months stale** relative to the download date.
9. **Provider methodology is opaque.** Schema is documented; sampling is not.
10. **Small cells.** The 4+ BR band has n = 4; pro-management has 2 hosts.

---

## Figure index

| Figure | File | Shows |
|---|---|---|
| 1 | `figures/01_price_distribution.png` | ADR distribution and room-type split |
| 2 | `figures/02_capacity_and_price.png` | Capacity vs price, with missing-bedroom flag |
| 3 | `figures/03_listing_map.png` | Listing locations and centro rings |
| 4 | `figures/04_distance_and_price.png` | Distance vs price and band medians |
| 5 | `figures/05_seasonality.png` | Occupancy, ADR and revenue by month |
| 6 | `figures/06_price_vs_occupancy.png` | Price–occupancy scatter |
| 7 | `figures/07_segment_scorecard.png` | Room type, superhost, management |
| 8 | `figures/08_revenue_concentration.png` | Lorenz curve and top-host share |
| 9 | `figures/09_correlation_matrix.png` | Correlation matrix |
| 10 | `figures/10_within_listing_repricing.png` | Within-listing price and occupancy change |
