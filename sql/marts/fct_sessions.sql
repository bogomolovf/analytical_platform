-- ============================================================================
-- fct_sessions - витрина сессий (grain: одна сессия).
-- Сборка сырых событий в сессии по session_id: время начала/конца,
-- длительность, число и состав событий, наличие покупки.
-- Служебные потоки (purchase/churn) в сессии не входят.
-- ============================================================================
with session_events as (
    select *
    from {{ ref('fct_events') }}
    where session_id is not null
      and event_name not in ('purchase', 'churn')
)

select
    session_id,
    user_id,
    any_value(acquisition_channel)                       as acquisition_channel,
    any_value(country)                                   as country,
    any_value(device)                                    as device,
    any_value(behavior_segment)                          as behavior_segment,
    min(event_timestamp)                                 as session_start,
    max(event_timestamp)                                 as session_end,
    cast(min(event_timestamp) as date)                   as session_date,
    date_diff('second', min(event_timestamp), max(event_timestamp)) as duration_seconds,
    count(*)                                             as event_count,
    count(distinct event_name)                           as distinct_event_types,
    max(case when event_name = 'signup' then 1 else 0 end) as is_first_session
from session_events
group by session_id, user_id
