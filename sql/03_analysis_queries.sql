-- ===========================================================================
-- Analysis queries
-- ===========================================================================
-- Every query is self-contained, runs on SQLite 3.25+, and states its scope.
-- Marker format:  -- name: <id>   -- description: <text>
-- The runner (src/run_queries.py) splits on the `-- name:` markers and writes
-- the results to reports/sql_results.md.
--
-- Scope: v_city_listings excludes the single rural farm stay 47 km from the
-- centro. Unless stated otherwise, "occupancy" is calendar occupancy
-- (reserved nights / all nights), not occupancy net of host blocks.
-- ===========================================================================


-- name: q01_portfolio_overview
-- description: Headline size, price, occupancy and revenue of the 99-listing city sample.
WITH ranked_price AS (
    SELECT price_mxn, ROW_NUMBER() OVER (ORDER BY price_mxn) AS rn, COUNT(*) OVER () AS n
    FROM v_city_listings
),
ranked_occ AS (
    SELECT occupancy, ROW_NUMBER() OVER (ORDER BY occupancy) AS rn, COUNT(*) OVER () AS n
    FROM v_city_listings
),
ranked_rev AS (
    SELECT revenue_mxn, ROW_NUMBER() OVER (ORDER BY revenue_mxn) AS rn, COUNT(*) OVER () AS n
    FROM v_city_listings
)
SELECT
    (SELECT COUNT(*) FROM v_city_listings)                                  AS listings,
    (SELECT COUNT(DISTINCT host_id) FROM v_city_listings)                    AS hosts,
    (SELECT SUM(superhost) FROM v_city_listings)                             AS superhosts,
    (SELECT SUM(professional_management) FROM v_city_listings)               AS professionally_managed,
    ROUND((SELECT AVG(price_mxn) FROM ranked_price
           WHERE rn IN ((n + 1) / 2, (n + 2) / 2)), 1)                       AS median_adr_mxn,
    ROUND((SELECT AVG(occupancy) FROM ranked_occ
           WHERE rn IN ((n + 1) / 2, (n + 2) / 2)), 3)                       AS median_calendar_occupancy,
    ROUND((SELECT AVG(revenue_mxn) FROM ranked_rev
           WHERE rn IN ((n + 1) / 2, (n + 2) / 2)), 0)                       AS median_ttm_revenue_mxn,
    ROUND((SELECT SUM(revenue_mxn) FROM v_city_listings), 0)                 AS total_ttm_revenue_mxn,
    ROUND((SELECT SUM(ttm_reserved_days) * 1.0 / SUM(ttm_total_days)
           FROM v_city_listings), 3)                                         AS sample_weighted_occupancy,
    ROUND(AVG(distance_centro_km), 2)                                        AS mean_distance_to_centro_km,
    ROUND(100.0 * SUM(CASE WHEN distance_centro_km <= 1 THEN 1 ELSE 0 END) / COUNT(*), 1)
                                                                             AS pct_within_1km
FROM v_city_listings;


-- name: q02_room_type_performance
-- description: Entire homes vs private rooms - price, occupancy, revenue and revenue share.
WITH base AS (
    SELECT room_type, price_mxn, occupancy, revenue_mxn
    FROM v_city_listings
),
med_price AS (
    SELECT room_type, AVG(price_mxn) AS median_adr_mxn
    FROM (SELECT room_type, price_mxn,
                 ROW_NUMBER() OVER (PARTITION BY room_type ORDER BY price_mxn) AS rn,
                 COUNT(*) OVER (PARTITION BY room_type) AS n
          FROM base)
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY room_type
),
med_occ AS (
    SELECT room_type, AVG(occupancy) AS median_occupancy
    FROM (SELECT room_type, occupancy,
                 ROW_NUMBER() OVER (PARTITION BY room_type ORDER BY occupancy) AS rn,
                 COUNT(*) OVER (PARTITION BY room_type) AS n
          FROM base)
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY room_type
),
med_rev AS (
    SELECT room_type, AVG(revenue_mxn) AS median_revenue_mxn
    FROM (SELECT room_type, revenue_mxn,
                 ROW_NUMBER() OVER (PARTITION BY room_type ORDER BY revenue_mxn) AS rn,
                 COUNT(*) OVER (PARTITION BY room_type) AS n
          FROM base)
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY room_type
),
by_type AS (
    SELECT
        room_type,
        COUNT(*)         AS listings,
        AVG(price_mxn)   AS mean_adr_mxn,
        AVG(occupancy)   AS mean_occupancy,
        SUM(revenue_mxn) AS total_revenue_mxn
    FROM base
    GROUP BY room_type
)
SELECT
    b.room_type,
    b.listings,
    ROUND(100.0 * b.listings / (SELECT COUNT(*) FROM v_city_listings), 1) AS pct_of_sample,
    ROUND(p.median_adr_mxn, 1)                  AS median_adr_mxn,
    ROUND(b.mean_adr_mxn, 1)                    AS mean_adr_mxn,
    ROUND(o.median_occupancy, 3)                AS median_occupancy,
    ROUND(b.mean_occupancy, 3)                  AS mean_occupancy,
    ROUND(r.median_revenue_mxn, 0)              AS median_ttm_revenue_mxn,
    ROUND(100.0 * b.total_revenue_mxn /
          (SELECT SUM(revenue_mxn) FROM v_city_listings), 1) AS pct_of_sample_revenue
FROM by_type b
JOIN med_price p ON p.room_type = b.room_type
JOIN med_occ   o ON o.room_type = b.room_type
JOIN med_rev   r ON r.room_type = b.room_type
ORDER BY b.total_revenue_mxn DESC;


-- name: q03_listing_level_distribution
-- description: Distribution of ADR, calendar occupancy and trailing-twelve-month revenue (city sample).
WITH ranked AS (
    SELECT
        price_mxn, occupancy, revenue_mxn,
        ROW_NUMBER() OVER (ORDER BY price_mxn)   AS rp,
        ROW_NUMBER() OVER (ORDER BY occupancy)   AS ro,
        ROW_NUMBER() OVER (ORDER BY revenue_mxn) AS rr,
        COUNT(*) OVER () AS n
    FROM v_city_listings
)
SELECT 'ADR (MXN/night)' AS metric,
       ROUND(MIN(price_mxn), 1) AS min,
       ROUND(MIN(CASE WHEN rp >= 0.10 * n THEN price_mxn END), 1) AS p10,
       ROUND(MIN(CASE WHEN rp >= 0.25 * n THEN price_mxn END), 1) AS p25,
       ROUND(AVG(CASE WHEN rp IN ((n + 1) / 2, (n + 2) / 2) THEN price_mxn END), 1) AS median,
       ROUND(MIN(CASE WHEN rp >= 0.75 * n THEN price_mxn END), 1) AS p75,
       ROUND(MIN(CASE WHEN rp >= 0.90 * n THEN price_mxn END), 1) AS p90,
       ROUND(MAX(price_mxn), 1) AS max
FROM ranked
UNION ALL
SELECT 'Calendar occupancy',
       ROUND(MIN(occupancy), 3),
       ROUND(MIN(CASE WHEN ro >= 0.10 * n THEN occupancy END), 3),
       ROUND(MIN(CASE WHEN ro >= 0.25 * n THEN occupancy END), 3),
       ROUND(AVG(CASE WHEN ro IN ((n + 1) / 2, (n + 2) / 2) THEN occupancy END), 3),
       ROUND(MIN(CASE WHEN ro >= 0.75 * n THEN occupancy END), 3),
       ROUND(MIN(CASE WHEN ro >= 0.90 * n THEN occupancy END), 3),
       ROUND(MAX(occupancy), 3)
FROM ranked
UNION ALL
SELECT 'TTM revenue (MXN)',
       ROUND(MIN(revenue_mxn), 0),
       ROUND(MIN(CASE WHEN rr >= 0.10 * n THEN revenue_mxn END), 0),
       ROUND(MIN(CASE WHEN rr >= 0.25 * n THEN revenue_mxn END), 0),
       ROUND(AVG(CASE WHEN rr IN ((n + 1) / 2, (n + 2) / 2) THEN revenue_mxn END), 0),
       ROUND(MIN(CASE WHEN rr >= 0.75 * n THEN revenue_mxn END), 0),
       ROUND(MIN(CASE WHEN rr >= 0.90 * n THEN revenue_mxn END), 0),
       ROUND(MAX(revenue_mxn), 0)
FROM ranked;


-- name: q04_monthly_seasonality
-- description: Month-by-month market benchmark (all 12 months). Realised demand after Apr-2026 is right-censored by the data cutoff.
SELECT
    month_label,
    listings,
    booked_listings,
    reserved_nights,
    calendar_nights,
    occupancy,
    median_adr_quoted_mxn,
    median_adr_booked_mxn,
    revenue_mxn,
    revenue_per_listing_mxn
FROM v_monthly_market
ORDER BY month_start;


-- name: q05_seasonality_by_room_type
-- description: Occupancy seasonality split by room type (all 12 months, censoring caveat applies).
SELECT
    month_label,
    ROUND(AVG(CASE WHEN room_type = 'entire_home'  THEN occupancy END), 3) AS entire_home_occupancy,
    ROUND(AVG(CASE WHEN room_type = 'private_room' THEN occupancy END), 3) AS private_room_occupancy,
    ROUND(AVG(CASE WHEN room_type = 'entire_home'  THEN adr_quoted_mxn END), 0) AS entire_home_avg_quoted_adr,
    ROUND(AVG(CASE WHEN room_type = 'private_room' THEN adr_quoted_mxn END), 0) AS private_room_avg_quoted_adr,
    SUM(CASE WHEN room_type = 'entire_home' THEN revenue_mxn ELSE 0 END)  AS entire_home_revenue_mxn,
    SUM(CASE WHEN room_type = 'private_room' THEN revenue_mxn ELSE 0 END) AS private_room_revenue_mxn
FROM v_monthly_city
GROUP BY month_start, month_label
ORDER BY month_start;


-- name: q06_distance_band_performance
-- description: Location proxy (straight-line distance to Plaza de Armas) vs price, occupancy and revenue.
WITH base AS (
    SELECT distance_band, price_mxn, occupancy, revenue_mxn, distance_centro_km
    FROM v_city_listings
),
med_price AS (
    SELECT distance_band, AVG(price_mxn) AS median_adr
    FROM (SELECT distance_band, price_mxn,
                 ROW_NUMBER() OVER (PARTITION BY distance_band ORDER BY price_mxn) AS rn,
                 COUNT(*) OVER (PARTITION BY distance_band) AS n
          FROM base)
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY distance_band
),
med_rev AS (
    SELECT distance_band, AVG(revenue_mxn) AS median_revenue
    FROM (SELECT distance_band, revenue_mxn,
                 ROW_NUMBER() OVER (PARTITION BY distance_band ORDER BY revenue_mxn) AS rn,
                 COUNT(*) OVER (PARTITION BY distance_band) AS n
          FROM base)
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY distance_band
),
bands AS (
    SELECT
        distance_band,
        COUNT(*)              AS listings,
        AVG(occupancy)        AS mean_occupancy,
        AVG(revenue_mxn)      AS mean_revenue,
        AVG(distance_centro_km) AS mean_km
    FROM base
    GROUP BY distance_band
)
SELECT
    b.distance_band,
    b.listings,
    ROUND(b.mean_km, 2)             AS mean_distance_km,
    ROUND(p.median_adr, 1)          AS median_adr_mxn,
    ROUND(b.mean_occupancy, 3)      AS mean_occupancy,
    ROUND(r.median_revenue, 0)      AS median_ttm_revenue_mxn,
    ROUND(b.mean_revenue, 0)        AS mean_ttm_revenue_mxn
FROM bands b
JOIN med_price p ON p.distance_band = b.distance_band
JOIN med_rev   r ON r.distance_band = b.distance_band
ORDER BY b.mean_km;


-- name: q07_superhost_association
-- description: Superhost badge vs price, occupancy and revenue (descriptive association only).
WITH ranked AS (
    SELECT superhost, price_mxn, occupancy, revenue_mxn, rating_overall,
           ROW_NUMBER() OVER (PARTITION BY superhost ORDER BY price_mxn)   AS rp,
           ROW_NUMBER() OVER (PARTITION BY superhost ORDER BY occupancy)   AS ro,
           ROW_NUMBER() OVER (PARTITION BY superhost ORDER BY revenue_mxn) AS rr,
           COUNT(*) OVER (PARTITION BY superhost) AS n
    FROM v_city_listings
)
SELECT
    CASE WHEN superhost = 1 THEN 'Superhost' ELSE 'Not superhost' END AS segment,
    COUNT(*) AS listings,
    ROUND(AVG(price_mxn), 1)   AS mean_adr_mxn,
    ROUND(AVG(CASE WHEN rp IN ((n + 1) / 2, (n + 2) / 2) THEN price_mxn END), 1) AS median_adr_mxn,
    ROUND(AVG(occupancy), 3)   AS mean_occupancy,
    ROUND(AVG(CASE WHEN ro IN ((n + 1) / 2, (n + 2) / 2) THEN occupancy END), 3) AS median_occupancy,
    ROUND(AVG(revenue_mxn), 0) AS mean_ttm_revenue_mxn,
    ROUND(AVG(CASE WHEN rr IN ((n + 1) / 2, (n + 2) / 2) THEN revenue_mxn END), 0) AS median_ttm_revenue_mxn,
    ROUND(AVG(rating_overall), 2) AS mean_rating
FROM ranked
GROUP BY superhost
ORDER BY superhost DESC;


-- name: q08_professional_management
-- description: Professional-management flag vs outcomes, including how many hosts sit behind the flag.
SELECT
    CASE WHEN professional_management = 1 THEN 'Professionally managed' ELSE 'Independent' END AS segment,
    COUNT(*)                          AS listings,
    COUNT(DISTINCT host_id)           AS distinct_hosts,
    ROUND(AVG(price_mxn), 1)          AS mean_adr_mxn,
    ROUND(AVG(occupancy), 3)          AS mean_occupancy,
    ROUND(AVG(revenue_mxn), 0)        AS mean_ttm_revenue_mxn,
    ROUND(AVG(rating_overall), 2)     AS mean_rating,
    ROUND(AVG(ttm_avg_length_of_stay), 1) AS mean_length_of_stay_nights
FROM v_city_listings
GROUP BY professional_management
ORDER BY professional_management DESC;


-- name: q09_bedroom_band_performance
-- description: Price and revenue scale with capacity; 19 listings without bedroom metadata are excluded.
SELECT
    bedroom_band,
    COUNT(*)                       AS listings,
    ROUND(AVG(price_mxn), 0)       AS mean_adr_mxn,
    ROUND(AVG(occupancy), 3)       AS mean_occupancy,
    ROUND(AVG(revenue_mxn), 0)     AS mean_ttm_revenue_mxn,
    ROUND(AVG(price_per_guest_mxn), 0) AS mean_adr_per_guest_mxn
FROM v_city_listings
WHERE bedroom_band <> 'Unknown'
GROUP BY bedroom_band
ORDER BY
    CASE bedroom_band
        WHEN 'Studio / 1 BR' THEN 1
        WHEN '2 BR' THEN 2
        WHEN '3 BR' THEN 3
        ELSE 4
    END;


-- name: q10_revenue_concentration
-- description: Share of sample revenue captured by the top 10% and top 20% of listings.
WITH ranked AS (
    SELECT
        revenue_mxn,
        ROW_NUMBER() OVER (ORDER BY revenue_mxn DESC) AS rn,
        COUNT(*) OVER () AS n,
        SUM(revenue_mxn) OVER () AS total_revenue
    FROM v_city_listings
)
SELECT
    COUNT(*) AS listings,
    ROUND(MAX(total_revenue), 0) AS total_revenue_mxn,
    ROUND(100.0 * SUM(CASE WHEN rn <= (n + 9) / 10 THEN revenue_mxn ELSE 0 END) / MAX(total_revenue), 1) AS top10_pct_revenue,
    ROUND(100.0 * SUM(CASE WHEN rn <= (n * 2 + 9) / 10 THEN revenue_mxn ELSE 0 END) / MAX(total_revenue), 1) AS top20_pct_revenue,
    ROUND(100.0 * SUM(CASE WHEN rn <= (n + 1) / 2 THEN revenue_mxn ELSE 0 END) / MAX(total_revenue), 1) AS top50_pct_revenue
FROM ranked;


-- name: q11_host_concentration
-- description: Multi-listing hosts and their share of sample revenue.
SELECT
    l.host_id,
    MAX(l.host_name)                       AS host_label,
    COUNT(*)                               AS listings,
    ROUND(SUM(l.revenue_mxn), 0)           AS ttm_revenue_mxn,
    ROUND(100.0 * SUM(l.revenue_mxn) /
          (SELECT SUM(revenue_mxn) FROM v_city_listings), 1) AS pct_of_sample_revenue,
    ROUND(AVG(l.price_mxn), 0)             AS mean_adr_mxn,
    ROUND(AVG(l.occupancy), 3)             AS mean_occupancy,
    SUM(l.professional_management)         AS pro_managed_listings
FROM v_city_listings l
GROUP BY l.host_id
ORDER BY listings DESC, ttm_revenue_mxn DESC
LIMIT 12;


-- name: q12_rating_bands
-- description: Guest rating vs price and demand. Ratings are high and compressed (median 4.83).
SELECT
    CASE
        WHEN rating_overall >= 4.9 THEN '4.90-5.00'
        WHEN rating_overall >= 4.8 THEN '4.80-4.89'
        WHEN rating_overall >= 4.7 THEN '4.70-4.79'
        WHEN rating_overall IS NULL THEN 'No rating'
        ELSE 'Below 4.70'
    END AS rating_band,
    COUNT(*)                        AS listings,
    ROUND(AVG(price_mxn), 0)        AS mean_adr_mxn,
    ROUND(AVG(occupancy), 3)        AS mean_occupancy,
    ROUND(AVG(revenue_mxn), 0)      AS mean_ttm_revenue_mxn,
    ROUND(AVG(num_reviews), 0)      AS mean_review_count
FROM v_city_listings
GROUP BY rating_band
ORDER BY CASE rating_band
    WHEN '4.90-5.00' THEN 1
    WHEN '4.80-4.89' THEN 2
    WHEN '4.70-4.79' THEN 3
    WHEN 'Below 4.70' THEN 4
    ELSE 5
END;


-- name: q13_length_of_stay
-- description: Booking length vs price and occupancy (TTM averages per listing).
SELECT
    CASE
        WHEN ttm_avg_length_of_stay < 3 THEN 'Under 3 nights'
        WHEN ttm_avg_length_of_stay < 5 THEN '3-4 nights'
        WHEN ttm_avg_length_of_stay < 7 THEN '5-6 nights'
        ELSE '7+ nights'
    END AS stay_band,
    COUNT(*)                        AS listings,
    ROUND(AVG(price_mxn), 0)        AS mean_adr_mxn,
    ROUND(AVG(occupancy), 3)        AS mean_calendar_occupancy,
    ROUND(AVG(adjusted_occupancy), 3) AS mean_adjusted_occupancy,
    ROUND(AVG(revenue_mxn), 0)      AS mean_ttm_revenue_mxn
FROM v_city_listings
GROUP BY stay_band
ORDER BY CASE stay_band
    WHEN 'Under 3 nights' THEN 1
    WHEN '3-4 nights' THEN 2
    WHEN '5-6 nights' THEN 3
    ELSE 4
END;


-- name: q14_postal_code_hotspots
-- description: Postal-code areas with at least 3 sampled listings (postal code is not a neighbourhood).
SELECT
    postal_code,
    COUNT(*)                          AS listings,
    ROUND(AVG(distance_centro_km), 2) AS mean_distance_km,
    ROUND(AVG(price_mxn), 0)          AS mean_adr_mxn,
    ROUND(AVG(occupancy), 3)          AS mean_occupancy,
    ROUND(AVG(revenue_mxn), 0)        AS mean_ttm_revenue_mxn,
    SUM(CASE WHEN room_type = 'entire_home' THEN 1 ELSE 0 END) AS entire_homes,
    SUM(CASE WHEN room_type = 'private_room' THEN 1 ELSE 0 END) AS private_rooms
FROM v_city_listings
GROUP BY postal_code
HAVING COUNT(*) >= 3
ORDER BY listings DESC, mean_ttm_revenue_mxn DESC;


-- name: q15_robustness_scope
-- description: Do headline medians change when high-price listings or the rural farm stay are removed?
SELECT
    'City sample (n=99)' AS scope,
    COUNT(*) AS listings,
    ROUND(AVG(price_mxn), 0)   AS mean_adr_mxn,
    ROUND(AVG(occupancy), 3)   AS mean_occupancy,
    ROUND(AVG(revenue_mxn), 0) AS mean_ttm_revenue_mxn
FROM v_city_listings
UNION ALL
SELECT
    'Excluding 6 high-price outliers',
    COUNT(*), ROUND(AVG(price_mxn), 0), ROUND(AVG(occupancy), 3), ROUND(AVG(revenue_mxn), 0)
FROM v_city_listings
WHERE is_high_price_outlier = 0
UNION ALL
SELECT
    'All 100 listings (incl. rural)',
    COUNT(*), ROUND(AVG(price_mxn), 0), ROUND(AVG(occupancy), 3), ROUND(AVG(revenue_mxn), 0)
FROM listings;


-- name: q16_censoring_evidence
-- description: Review volume by month documents the observation cutoff: May-Jul 2026 are incomplete.
SELECT
    m.month_label,
    m.occupancy,
    r.reviews,
    r.listings_with_reviews,
    m.booked_listings
FROM v_monthly_market m
JOIN v_reviews_market r ON r.month_start = m.month_start
ORDER BY m.month_start;
