-- Downstream analysis of existing sample_events; execute with run_analysis.py.
-- DuckDB 1.5.5. Input IDs and timestamp are VARCHAR.
-- Window: [2017-11-25 00:00, 2017-12-04 00:00), Asia/Shanghai.
-- Exact duplicate records are retained. buy rows are events, not orders.
-- All derived tables are TEMP; the source database stays unchanged.

CREATE OR REPLACE TEMP VIEW normalized_sample_events AS
SELECT *, TRIM(behavior_type) AS behavior_type_clean
FROM sample_events;

CREATE OR REPLACE TEMP TABLE final_sample_summary AS
SELECT
    COUNT(*) AS event_records,
    COUNT(DISTINCT user_id) AS users,
    COUNT(DISTINCT item_id) AS items
FROM sample_events;

CREATE OR REPLACE TEMP TABLE final_quality_check AS
SELECT
    COUNT(*) AS total_records,
    COUNT(*) FILTER (WHERE behavior_type <> behavior_type_clean)
        AS normalized_behavior_records,

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
        WHERE behavior_type_clean IS NULL
           OR behavior_type_clean NOT IN ('pv', 'fav', 'cart', 'buy')
    ) AS invalid_behavior,

    COUNT(*) FILTER (
        WHERE TRY(to_timestamp(TRY_CAST(timestamp AS BIGINT))
                  AT TIME ZONE 'Asia/Shanghai') IS NULL
    ) AS invalid_timestamp

FROM normalized_sample_events;

-- Fail before creating any formal metric tables.
SELECT CASE
    WHEN total_records = 0 OR missing_user_id > 0 OR missing_item_id > 0
      OR missing_category_id > 0 OR invalid_behavior > 0 OR invalid_timestamp > 0
    THEN error(printf(
        'Data quality failed: total_records=%d, normalized_behavior_records=%d, missing_user_id=%d, missing_item_id=%d, missing_category_id=%d, invalid_behavior=%d, invalid_timestamp=%d',
        total_records, normalized_behavior_records, missing_user_id, missing_item_id,
        missing_category_id, invalid_behavior, invalid_timestamp
    ))
    ELSE 'Data quality passed'
END AS quality_status
FROM final_quality_check;

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
    FROM normalized_sample_events
),

localized AS (
    SELECT
        user_id,
        item_id,
        category_id,
        behavior_type,
        behavior_type_clean,
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
            WHERE behavior_type_clean = 'buy'
        ) AS buyers,

        COUNT(*) FILTER (
            WHERE behavior_type_clean = 'buy'
        ) AS buy_events

    FROM final_events
    GROUP BY event_date
)

SELECT
    *,
    buyers * 1.0 / NULLIF(active_users, 0) AS buyer_rate,
    (SELECT users FROM final_analysis_summary) AS window_sample_users,
    active_users * 1.0 / NULLIF((SELECT users FROM final_analysis_summary), 0)
        AS sample_active_share

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
         AND behavior_type_clean = 'buy'
        THEN 1 ELSE 0
    END) AS buyer_before,

    MAX(CASE
        WHEN event_date = DATE '2017-12-02'
         AND behavior_type_clean = 'buy'
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
ORDER BY buyer_change DESC, cohort;

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

    WHERE behavior_type_clean = 'buy'
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

-- Extended analysis: also executed by the Notebook after its independent core queries.
CREATE OR REPLACE TEMP TABLE final_observation_window AS
SELECT TIMESTAMP '2017-12-04 00:00:00' AS end_time;

CREATE OR REPLACE TEMP TABLE final_weekday_comparison AS
WITH comparisons(comparison, before_date, after_date) AS (
    VALUES
        ('adjacent_days', DATE '2017-12-01', DATE '2017-12-02'),
        ('saturday', DATE '2017-11-25', DATE '2017-12-02'),
        ('sunday', DATE '2017-11-26', DATE '2017-12-03')
)
SELECT
    c.*,
    b.active_users AS active_users_before, a.active_users AS active_users_after,
    a.active_users - b.active_users AS active_users_change,
    (a.active_users - b.active_users) * 1.0 / NULLIF(b.active_users, 0)
        AS active_users_relative_change,
    b.buyers AS buyers_before, a.buyers AS buyers_after,
    a.buyers - b.buyers AS buyers_change,
    (a.buyers - b.buyers) * 1.0 / NULLIF(b.buyers, 0) AS buyers_relative_change,
    b.buyer_rate AS buyer_rate_before, a.buyer_rate AS buyer_rate_after,
    (a.buyer_rate - b.buyer_rate) * 100 AS buyer_rate_change_pp,
    b.buy_events AS buy_events_before, a.buy_events AS buy_events_after,
    a.buy_events - b.buy_events AS buy_events_change
FROM comparisons c
LEFT JOIN final_daily_metrics b ON b.event_date = c.before_date
LEFT JOIN final_daily_metrics a ON a.event_date = c.after_date
ORDER BY c.before_date;

CREATE OR REPLACE TEMP TABLE final_after_only_history AS
WITH earlier_users AS (
    SELECT DISTINCT user_id FROM final_events
    WHERE event_date >= DATE '2017-11-25' AND event_date < DATE '2017-12-01'
),
user_features AS (
    SELECT
        u.user_id,
        CASE WHEN h.user_id IS NOT NULL THEN 'seen_earlier_in_window'
             ELSE 'not_seen_earlier_in_window' END AS history_group,
        u.buyer_after,
        COUNT(*) AS event_records,
        COUNT(*) FILTER (WHERE e.behavior_type_clean = 'pv') AS pv_events,
        COUNT(*) FILTER (WHERE e.behavior_type_clean = 'cart') AS cart_events,
        COUNT(*) FILTER (WHERE e.behavior_type_clean = 'buy') AS buy_events
    FROM final_user_two_day u
    LEFT JOIN earlier_users h ON h.user_id = u.user_id
    JOIN final_events e ON e.user_id = u.user_id AND e.event_date = DATE '2017-12-02'
    WHERE u.active_before = 0 AND u.active_after = 1
    GROUP BY u.user_id, history_group, u.buyer_after
),
groups(history_group) AS (
    VALUES ('seen_earlier_in_window'), ('not_seen_earlier_in_window')
)
SELECT
    g.history_group, COUNT(f.user_id) AS users,
    COALESCE(SUM(buyer_after), 0) AS buyers,
    SUM(buyer_after) * 1.0 / NULLIF(COUNT(f.user_id), 0) AS buyer_rate,
    COALESCE(SUM(event_records), 0) AS event_records,
    COALESCE(SUM(pv_events), 0) AS pv_events,
    COALESCE(SUM(cart_events), 0) AS cart_events,
    COALESCE(SUM(buy_events), 0) AS buy_events,
    COUNT(*) FILTER (WHERE cart_events > 0) AS cart_users,
    AVG(event_records) AS events_per_user
FROM groups g LEFT JOIN user_features f USING (history_group)
GROUP BY g.history_group
ORDER BY g.history_group;

-- The observation end is exclusive; success uses (first_cart, first_cart + 24h].
CREATE OR REPLACE TEMP TABLE final_cart_pair_outcomes AS
WITH first_carts AS (
    SELECT user_id, item_id, MIN(event_time) AS first_cart_time
    FROM final_events
    WHERE event_date = DATE '2017-12-02' AND behavior_type_clean = 'cart'
    GROUP BY user_id, item_id
),
classified AS (
    SELECT c.*,
        CASE WHEN u.active_before = 1 THEN 'both_days' ELSE 'after_only' END AS cohort,
        c.first_cart_time + INTERVAL '24 hours' < (SELECT end_time FROM final_observation_window)
            AS complete_24h_window
    FROM first_carts c
    JOIN final_user_two_day u USING (user_id)
)
SELECT c.*,
    EXISTS (
        SELECT 1 FROM final_events b
        WHERE b.user_id = c.user_id AND b.item_id = c.item_id
          AND b.behavior_type_clean = 'buy' AND b.event_time = c.first_cart_time
    ) AS same_second_buy,
    EXISTS (
        SELECT 1 FROM final_events b
        WHERE b.user_id = c.user_id AND b.item_id = c.item_id
          AND b.behavior_type_clean = 'buy'
          AND b.event_time > c.first_cart_time
          AND b.event_time <= c.first_cart_time + INTERVAL '24 hours'
    ) AS strict_later_buy
FROM classified c;

CREATE OR REPLACE TEMP TABLE final_cart_to_buy_24h AS
WITH groups(cohort) AS (VALUES ('all'), ('after_only'), ('both_days'))
SELECT
    g.cohort,
    COUNT(p.user_id) AS start_pairs,
    COUNT(*) FILTER (WHERE NOT p.complete_24h_window) AS excluded_incomplete_pairs,
    COUNT(*) FILTER (WHERE p.complete_24h_window) AS eligible_pairs,
    COUNT(DISTINCT p.user_id) FILTER (WHERE p.complete_24h_window) AS eligible_users,
    COUNT(*) FILTER (WHERE p.complete_24h_window AND p.strict_later_buy) AS success_pairs,
    COUNT(*) FILTER (WHERE p.complete_24h_window AND p.same_second_buy)
        AS same_second_buy_pairs,
    COUNT(*) FILTER (WHERE p.complete_24h_window AND p.same_second_buy AND NOT p.strict_later_buy)
        AS same_second_only_pairs,
    COUNT(*) FILTER (WHERE p.complete_24h_window AND p.strict_later_buy) * 1.0
        / NULLIF(COUNT(*) FILTER (WHERE p.complete_24h_window), 0)
        AS cart_item_pair_buy_rate_24h
FROM groups g
LEFT JOIN final_cart_pair_outcomes p ON g.cohort = 'all' OR g.cohort = p.cohort
GROUP BY g.cohort
ORDER BY g.cohort;
