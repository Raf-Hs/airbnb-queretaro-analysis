-- ===========================================================================
-- Querétaro Airbnb market analysis - relational schema (SQLite 3)
-- ===========================================================================
-- Design notes
--   * Grain: `listings` is one row per Airbnb listing; `monthly_rates` is one
--     row per listing-month; `reviews_monthly` is one row per listing-month.
--   * All money columns are Mexican pesos (MXN) unless suffixed `_usd`.
--   * Booleans are stored as 0/1 because SQLite has no native boolean type.
--   * Dates are ISO-8601 TEXT (YYYY-MM-DD) so they sort correctly.
--   * The schema is portable to SQL Server/PostgreSQL with type changes:
--     TEXT -> VARCHAR, INTEGER -> INT/BIT, REAL -> DECIMAL/FLOAT.
-- ===========================================================================

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS reviews_monthly;
DROP TABLE IF EXISTS monthly_rates;
DROP TABLE IF EXISTS listings;

-- ---------------------------------------------------------------------------
-- Listing-level table (trailing twelve months ending 2026-07)
-- ---------------------------------------------------------------------------
CREATE TABLE listings (
    listing_id                      TEXT    PRIMARY KEY,
    listing_name                    TEXT    NOT NULL,
    listing_url                     TEXT    NOT NULL,
    host_id                         INTEGER,
    host_name                       TEXT,
    superhost                       INTEGER NOT NULL CHECK (superhost IN (0, 1)),
    professional_management         INTEGER NOT NULL CHECK (professional_management IN (0, 1)),
    registration                    INTEGER,
    listing_type                    TEXT    NOT NULL,
    room_type                       TEXT    NOT NULL CHECK (room_type IN ('entire_home', 'private_room')),
    guests                          INTEGER,
    bedrooms                        INTEGER,
    beds                            INTEGER,
    baths                           REAL,
    bedroom_band                    TEXT    NOT NULL,
    guest_band                      TEXT    NOT NULL,
    min_nights                      INTEGER,
    cancellation_policy             TEXT,
    cleaning_fee                    REAL,
    extra_guest_fee                 REAL,
    photos_count                    INTEGER,
    has_description                 INTEGER,
    latitude                        REAL    NOT NULL,
    longitude                       REAL    NOT NULL,
    postal_code                     TEXT,
    postal_match_method             TEXT,
    postal_offset_km                REAL,
    distance_centro_km              REAL    NOT NULL,
    distance_band                   TEXT    NOT NULL,
    is_city_core                    INTEGER NOT NULL CHECK (is_city_core IN (0, 1)),
    is_rural_outlier                INTEGER NOT NULL CHECK (is_rural_outlier IN (0, 1)),
    location_is_exact               INTEGER,
    num_reviews                     INTEGER,
    rating_overall                  REAL,
    rating_accuracy                 REAL,
    rating_checkin                  REAL,
    rating_cleanliness              REAL,
    rating_communication            REAL,
    rating_location                 REAL,
    rating_value                    REAL,
    has_rating                      INTEGER,
    guest_favorite                  INTEGER,
    price_mxn                       REAL    NOT NULL CHECK (price_mxn > 0),
    price_usd                       REAL    NOT NULL CHECK (price_usd > 0),
    occupancy                       REAL    NOT NULL CHECK (occupancy BETWEEN 0 AND 1),
    adjusted_occupancy              REAL    NOT NULL CHECK (adjusted_occupancy BETWEEN 0 AND 1),
    revenue_mxn                     REAL    NOT NULL CHECK (revenue_mxn >= 0),
    revpar_mxn                      REAL    NOT NULL CHECK (revpar_mxn >= 0),
    ttm_reserved_days               INTEGER NOT NULL,
    ttm_blocked_days                INTEGER NOT NULL,
    ttm_available_days              INTEGER NOT NULL,
    ttm_total_days                  INTEGER NOT NULL,
    ttm_avg_length_of_stay          REAL,
    ttm_avg_min_nights              REAL,
    price_per_guest_mxn             REAL,
    revenue_per_reserved_night_mxn  REAL,
    is_high_price_outlier           INTEGER NOT NULL,
    l90d_occupancy                  REAL,
    l90d_avg_rate_native            REAL,
    l90d_revenue_native             REAL
);

CREATE INDEX idx_listings_room_type ON listings (room_type);
CREATE INDEX idx_listings_band ON listings (distance_band);
CREATE INDEX idx_listings_postal ON listings (postal_code);
CREATE INDEX idx_listings_host ON listings (host_id);

-- ---------------------------------------------------------------------------
-- Monthly calendar table (2025-08 to 2026-07)
-- ---------------------------------------------------------------------------
CREATE TABLE monthly_rates (
    listing_id              TEXT    NOT NULL,
    date                    TEXT    NOT NULL,
    month_start             TEXT    NOT NULL,
    year                    INTEGER NOT NULL,
    month                   INTEGER NOT NULL,
    month_label             TEXT    NOT NULL,
    quarter                 INTEGER NOT NULL,
    vacant_days             INTEGER NOT NULL,
    reserved_days           INTEGER NOT NULL,
    nights_available        INTEGER NOT NULL,
    occupancy               REAL    NOT NULL CHECK (occupancy BETWEEN 0 AND 1),
    has_bookings            INTEGER NOT NULL CHECK (has_bookings IN (0, 1)),
    revenue_mxn             REAL    NOT NULL,
    adr_quoted_mxn          REAL    NOT NULL,
    adr_booked_mxn          REAL,
    booking_lead_time_avg   INTEGER,
    length_of_stay_avg      INTEGER,
    min_nights_avg          INTEGER,
    is_partial_history      INTEGER NOT NULL,
    PRIMARY KEY (listing_id, month_start),
    FOREIGN KEY (listing_id) REFERENCES listings (listing_id) ON DELETE CASCADE
);

CREATE INDEX idx_rates_month ON monthly_rates (month_start);
CREATE INDEX idx_rates_listing ON monthly_rates (listing_id);

-- ---------------------------------------------------------------------------
-- Monthly review counts (same window; used as a demand sanity check)
-- ---------------------------------------------------------------------------
CREATE TABLE reviews_monthly (
    listing_id   TEXT    NOT NULL,
    date         TEXT    NOT NULL,
    month_start  TEXT    NOT NULL,
    month_label  TEXT    NOT NULL,
    num_reviews  INTEGER NOT NULL,
    PRIMARY KEY (listing_id, month_start),
    FOREIGN KEY (listing_id) REFERENCES listings (listing_id) ON DELETE CASCADE
);
