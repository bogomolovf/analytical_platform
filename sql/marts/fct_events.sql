-- ============================================================================
-- fct_events — атомарная витрина событий (grain: одно событие).
-- Очищенный событийный лог, обогащённый атрибутами пользователя, чтобы можно
-- было резать метрики по каналу/гео/устройству/сегменту без лишних джойнов.
-- ============================================================================
select
    e.event_id,
    e.user_id,
    e.session_id,
    e.event_name,
    e.event_timestamp,
    e.event_date,
    date_trunc('week', e.event_timestamp)::date  as event_week,
    date_trunc('month', e.event_timestamp)::date as event_month,
    e.event_value,
    e.plan                                       as event_plan,
    -- Атрибуты пользователя (денормализация для скорости аналитики).
    u.acquisition_channel,
    u.country,
    u.device,
    u.behavior_segment,
    u.signup_date,
    u.cohort_week,
    u.cohort_month,
    -- Флаг: событие относится к монетизации.
    (e.event_name = 'purchase')                  as is_purchase
from {{ ref('stg_events') }} e
inner join {{ ref('stg_users') }} u using (user_id)
