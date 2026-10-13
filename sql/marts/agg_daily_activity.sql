-- ============================================================================
-- agg_daily_activity - дневные агрегаты активности и монетизации.
-- Одна строка на календарный день: DAU, новые пользователи, сессии, события,
-- покупки и выручка. Основа для графиков роста и для расчёта DAU/WAU/MAU.
-- ============================================================================
with dates as (
    select date_day from {{ ref('dim_dates') }}
),

-- Активные пользователи и объёмы событий по дням (без служебных событий).
daily_activity as (
    select
        event_date,
        count(distinct user_id)                              as dau,
        count(distinct session_id)                           as sessions,
        count(*)                                             as events
    from {{ ref('fct_events') }}
    where event_name not in ('purchase', 'churn')
    group by event_date
),

-- Новые пользователи по дате регистрации.
new_users as (
    select signup_date as event_date, count(*) as new_users
    from {{ ref('dim_users') }}
    group by signup_date
),

-- Монетизация по дням: число покупок и выручка (только положительные суммы).
revenue as (
    select
        event_date,
        count(*)                                             as purchases,
        sum(case when event_value > 0 then event_value else 0 end) as revenue
    from {{ ref('fct_events') }}
    where event_name = 'purchase'
    group by event_date
),

-- Новые платящие: пользователи, чья дата конверсии = этот день.
new_paid as (
    select conversion_date as event_date, count(*) as new_paying_users
    from {{ ref('dim_users') }}
    where conversion_date is not null
    group by conversion_date
)

select
    d.date_day                                              as activity_date,
    coalesce(a.dau, 0)                                      as dau,
    coalesce(n.new_users, 0)                                as new_users,
    coalesce(a.sessions, 0)                                 as sessions,
    coalesce(a.events, 0)                                   as events,
    coalesce(r.purchases, 0)                                as purchases,
    coalesce(r.revenue, 0.0)                                as revenue,
    coalesce(p.new_paying_users, 0)                         as new_paying_users
from dates d
left join daily_activity a on d.date_day = a.event_date
left join new_users n       on d.date_day = n.event_date
left join revenue r         on d.date_day = r.event_date
left join new_paid p        on d.date_day = p.event_date
order by d.date_day
