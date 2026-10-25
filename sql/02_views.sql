-- ===========================================================================
-- Reusable views
-- ===========================================================================

-- City-core scope. The AirROI sample contains one rural farm stay 47 km east
-- of the centro; it is retained in `listings` but excluded from market views.
DROP VIEW IF EXISTS v_city_listings;
CREATE VIEW v_city_listings AS
SELECT *
FROM listings
WHERE is_city_core = 1;

-- Listing-month fact joined to listing attributes.
DROP VIEW IF EXISTS v_monthly_city;
CREATE VIEW v_monthly_city AS
SELECT
    r.listing_id,
    r.month_start,
    r.month_label,
    r.year,
    r.month,
    r.quarter,
    r.reserved_days,
    r.vacant_days,
    r.nights_available,
    r.occupancy,
    r.has_bookings,
    r.revenue_mxn,
    r.adr_quoted_mxn,
    r.adr_booked_mxn,
    r.length_of_stay_avg,
    r.booking_lead_time_avg,
    l.room_type,
    l.listing_type,
    l.bedroom_band,
    l.guest_band,
    l.distance_band,
    l.postal_code,
    l.superhost,
    l.professional_management,
    l.price_mxn,
    l.occupancy AS ttm_occupancy,
    l.revenue_mxn AS ttm_revenue_mxn
FROM monthly_rates r
JOIN listings l ON l.listing_id = r.listing_id
WHERE l.is_city_core = 1;

-- Market benchmark by month: revenue-weighted occupancy, median ADRs.
-- `booked_listings` counts listings with at least one reserved night.
-- Median booked ADR is computed only over rows that actually have bookings;
-- mixing NULLs into the row numbering would bias the median downward.
DROP VIEW IF EXISTS v_monthly_market;
CREATE VIEW v_monthly_market AS
WITH quoted AS (
    SELECT month_start, adr_quoted_mxn,
           ROW_NUMBER() OVER (PARTITION BY month_start ORDER BY adr_quoted_mxn) AS rn,
           COUNT(*) OVER (PARTITION BY month_start) AS n
    FROM v_monthly_city
),
quoted_median AS (
    SELECT month_start, AVG(adr_quoted_mxn) AS median_adr_quoted
    FROM quoted
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY month_start
),
booked AS (
    SELECT month_start, adr_booked_mxn,
           ROW_NUMBER() OVER (PARTITION BY month_start ORDER BY adr_booked_mxn) AS rn,
           COUNT(*) OVER (PARTITION BY month_start) AS n
    FROM v_monthly_city
    WHERE adr_booked_mxn IS NOT NULL
),
booked_median AS (
    SELECT month_start, AVG(adr_booked_mxn) AS median_adr_booked
    FROM booked
    WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
    GROUP BY month_start
),
monthly AS (
    SELECT
        month_start,
        month_label,
        COUNT(DISTINCT listing_id) AS listings,
        SUM(has_bookings)          AS booked_listings,
        SUM(reserved_days)         AS reserved_nights,
        -- reserved + vacant = all calendar days; vacant includes host-blocked nights
        SUM(nights_available)      AS calendar_nights,
        SUM(revenue_mxn)           AS revenue_mxn
    FROM v_monthly_city
    GROUP BY month_start, month_label
)
SELECT
    m.month_start,
    m.month_label,
    m.listings,
    m.booked_listings,
    m.reserved_nights,
    m.calendar_nights,
    ROUND(1.0 * m.reserved_nights / m.calendar_nights, 3) AS occupancy,
    q.median_adr_quoted                                    AS median_adr_quoted_mxn,
    b.median_adr_booked                                    AS median_adr_booked_mxn,
    ROUND(m.revenue_mxn, 2)                                AS revenue_mxn,
    ROUND(m.revenue_mxn / m.listings, 2)                   AS revenue_per_listing_mxn
FROM monthly m
LEFT JOIN quoted_median q ON q.month_start = m.month_start
LEFT JOIN booked_median b ON b.month_start = m.month_start
ORDER BY m.month_start;

-- Months with complete booking observation. From May 2026 onward the number
-- of reviews per month collapses (73 -> 25 -> 6), which is a data-cutoff
-- artefact, not seasonality: future nights appear as unbooked. Realised
-- occupancy/revenue should be compared on Aug-2025..Apr-2026 only.
DROP VIEW IF EXISTS v_complete_months;
CREATE VIEW v_complete_months AS
SELECT *
FROM v_monthly_market
WHERE month_start <= '2026-04-01';

-- Monthly review volume, used to document the observation cutoff.
DROP VIEW IF EXISTS v_reviews_market;
CREATE VIEW v_reviews_market AS
SELECT
    r.month_start,
    r.month_label,
    COUNT(DISTINCT r.listing_id) AS listings_with_reviews,
    SUM(r.num_reviews)           AS reviews
FROM reviews_monthly r
JOIN v_city_listings l ON l.listing_id = r.listing_id
GROUP BY r.month_start, r.month_label
ORDER BY r.month_start;
