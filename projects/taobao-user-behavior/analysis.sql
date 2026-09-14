-- Downstream analysis of existing sample_events; execute with run_analysis.py.
-- DuckDB 1.5.5. Input IDs and timestamp are VARCHAR.
-- Window: [2017-11-25 00:00, 2017-12-04 00:00), Asia/Shanghai.
-- Exact duplicate records are retained. buy rows are events, not orders.
-- All derived tables are TEMP; the source database stays unchanged.

CREATE OR REPLACE TEMP TABLE final_sample_summary AS
SELECT
    COUNT(*) AS event_records,
    COUNT(DISTINCT user_id) AS users,
    COUNT(DISTINCT item_id) AS items
FROM sample_events;

CREATE OR REPLACE TEMP TABLE final_quality_check AS
SELECT
    COUNT(*) AS total_records,

    COUNT(*) FILTER (
        WHERE user_id IS NULL OR TRIM(user_id) = ''
    ) AS missing_user_id,

    COUNT(*) FILTER (
        WHERE item_id IS NULL OR TRIM(item_id) = ''
    ) AS missing_item_id,

    COUNT(*) FILTER (
        WHERE category_id IS NULL OR TRIM(category_id) = ''
    ) AS missing_category_id,

    COUNT(*) FILTER (
        WHERE behavior_type IS NULL
           OR TRIM(behavior_type) NOT IN ('pv', 'fav', 'cart', 'buy')
    ) AS invalid_behavior,

    COUNT(*) FILTER (
        WHERE TRY_CAST(timestamp AS BIGINT) IS NULL
    ) AS invalid_timestamp

FROM sample_events;

CREATE OR REPLACE TEMP TABLE final_duplicate_base AS
SELECT
    COUNT(*) AS total_records,

    COUNT(DISTINCT (
        user_id,
        item_id,
        category_id,
        behavior_type,
        timestamp
    )) AS distinct_combinations

FROM sample_events;

CREATE OR REPLACE TEMP TABLE final_range_check AS
WITH parsed AS (
    SELECT
        TRY_CAST(timestamp AS BIGINT) AS epoch_seconds
    FROM sample_events
)
SELECT
    COUNT(*) AS total_records,

    COUNT(*) FILTER (
        WHERE epoch_seconds IS NULL
    ) AS invalid_timestamp,

    COUNT(*) FILTER (
        WHERE epoch_seconds < epoch(TIMESTAMPTZ '2017-11-25 00:00:00+08:00')
    ) AS before_window,

    COUNT(*) FILTER (
        WHERE epoch_seconds >= epoch(TIMESTAMPTZ '2017-11-25 00:00:00+08:00')
          AND epoch_seconds < epoch(TIMESTAMPTZ '2017-12-04 00:00:00+08:00')
    ) AS in_window,

    COUNT(*) FILTER (
        WHERE epoch_seconds >= epoch(TIMESTAMPTZ '2017-12-04 00:00:00+08:00')
    ) AS after_window

FROM parsed;

CREATE OR REPLACE TEMP TABLE final_duplicate_check AS
SELECT *, total_records - distinct_combinations AS extra_identical_records
FROM final_duplicate_base;

CREATE OR REPLACE TEMP TABLE final_events AS

WITH parsed AS (
    SELECT
        *,
        TRY_CAST(timestamp AS BIGINT) AS epoch_seconds
    FROM sample_events
),

localized AS (
    SELECT
        user_id,
        item_id,
        category_id,
        behavior_type,
        timestamp,

        to_timestamp(epoch_seconds)
            AT TIME ZONE 'Asia/Shanghai' AS event_time

    FROM parsed
    WHERE epoch_seconds >= epoch(TIMESTAMPTZ '2017-11-25 00:00:00+08:00')
      AND epoch_seconds < epoch(TIMESTAMPTZ '2017-12-04 00:00:00+08:00')
)

SELECT
    *,
    CAST(event_time AS DATE) AS event_date,
    EXTRACT(HOUR FROM event_time) AS event_hour
FROM localized;

CREATE OR REPLACE TEMP TABLE final_analysis_summary AS
SELECT COUNT(*) AS event_records, COUNT(DISTINCT user_id) AS users,
       MIN(event_time) AS earliest_time, MAX(event_time) AS latest_time
FROM final_events;

CREATE OR REPLACE TEMP TABLE final_daily_metrics AS
WITH daily AS (
    SELECT
        event_date,

        COUNT(*) AS event_records,

        COUNT(DISTINCT event_hour) AS observed_hours,

        COUNT(DISTINCT user_id) AS active_users,

        COUNT(DISTINCT user_id) FILTER (
            WHERE behavior_type = 'buy'
        ) AS buyers,

        COUNT(*) FILTER (
            WHERE behavior_type = 'buy'
        ) AS buy_events

    FROM final_events
    GROUP BY event_date
)

SELECT
    *,
    buyers * 1.0 / NULLIF(active_users, 0) AS buyer_rate

FROM daily
ORDER BY event_date;

CREATE OR REPLACE TEMP TABLE final_user_two_day AS

SELECT
    user_id,

    MAX(CASE
        WHEN event_date = DATE '2017-12-01'
        THEN 1 ELSE 0
    END) AS active_before,

    MAX(CASE
        WHEN event_date = DATE '2017-12-02'
        THEN 1 ELSE 0
    END) AS active_after,

    MAX(CASE
        WHEN event_date = DATE '2017-12-01'
         AND behavior_type = 'buy'
        THEN 1 ELSE 0
    END) AS buyer_before,

    MAX(CASE
        WHEN event_date = DATE '2017-12-02'
         AND behavior_type = 'buy'
        THEN 1 ELSE 0
    END) AS buyer_after

FROM final_events

WHERE event_date IN (
    DATE '2017-12-01',
    DATE '2017-12-02'
)

GROUP BY user_id;

CREATE OR REPLACE TEMP TABLE final_cohort_summary AS
WITH labeled AS (
    SELECT
        *,
        CASE
            WHEN active_before = 1 AND active_after = 1
                THEN 'both_days'
            WHEN active_before = 1
                THEN 'before_only'
            ELSE 'after_only'
        END AS cohort
    FROM final_user_two_day
),

summary AS (
    SELECT
        cohort,
        COUNT(*) AS users,

        SUM(active_before) AS active_before,
        SUM(active_after) AS active_after,

        SUM(buyer_before) AS buyers_before,
        SUM(buyer_after) AS buyers_after

    FROM labeled
    GROUP BY cohort
)

SELECT
    *,

    buyers_before * 1.0
        / NULLIF(active_before, 0) AS rate_before,

    buyers_after * 1.0
        / NULLIF(active_after, 0) AS rate_after,

    buyers_after - buyers_before AS buyer_change

FROM summary
ORDER BY buyer_change DESC;

CREATE OR REPLACE TEMP TABLE final_category_change AS
WITH category_counts AS (
    SELECT
        category_id,

        COUNT(*) FILTER (
            WHERE event_date = DATE '2017-12-01'
        ) AS buy_events_before,

        COUNT(*) FILTER (
            WHERE event_date = DATE '2017-12-02'
        ) AS buy_events_after

    FROM final_events

    WHERE behavior_type = 'buy'
      AND event_date IN (
          DATE '2017-12-01',
          DATE '2017-12-02'
      )

    GROUP BY category_id
)

SELECT
    *,
    buy_events_after - buy_events_before AS buy_event_change

FROM category_counts
ORDER BY buy_event_change DESC, category_id;
