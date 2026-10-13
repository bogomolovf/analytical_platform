-- ============================================================================
-- dim_users - витрина пользователей (одна строка на пользователя).
-- Атрибуты привлечения + поведенческие агрегаты, выведенные из событий:
-- первая/последняя активность, конверсия в платящего, текущий план, отток.
-- ============================================================================
with users as (
    select * from {{ ref('stg_users') }}
),

events as (
    select * from {{ ref('stg_events') }}
),

-- Активность пользователя (без служебных purchase/churn).
activity as (
    select
        user_id,
        min(event_timestamp)                                    as first_seen_ts,
        max(event_timestamp)                                    as last_seen_ts,
        count(*)                                                as total_events,
        count(distinct event_date)                              as active_days
    from events
    where event_name not in ('purchase', 'churn')
    group by user_id
),

-- Монетизация: первая покупка, последний оплаченный план, факт оттока.
monetization as (
    select
        user_id,
        min(case when event_name = 'purchase' then event_date end)  as conversion_date,
        arg_max(plan, event_timestamp)
            filter (where event_name = 'purchase')                  as last_paid_plan,
        count(*) filter (where event_name = 'purchase')             as purchase_count,
        sum(event_value) filter (where event_name = 'purchase')     as total_revenue,
        max(case when event_name = 'churn' then 1 else 0 end)       as has_churn_event
    from events
    group by user_id
)

select
    u.user_id,
    u.signup_ts,
    u.signup_date,
    u.cohort_week,
    u.cohort_month,
    u.acquisition_channel,
    u.country,
    u.device,
    u.behavior_segment,
    a.first_seen_ts,
    a.last_seen_ts,
    coalesce(a.total_events, 0)                                  as total_events,
    coalesce(a.active_days, 0)                                   as active_days,
    m.conversion_date,
    (m.conversion_date is not null)                             as is_converted,
    case when m.conversion_date is not null
         then date_diff('day', u.signup_date, m.conversion_date) end as days_to_convert,
    coalesce(m.purchase_count, 0)                               as purchase_count,
    coalesce(m.total_revenue, 0.0)                              as lifetime_revenue,
    -- Текущий план: последний оплаченный, если пользователь ещё платит.
    case
        when m.conversion_date is not null and m.has_churn_event = 0
            then m.last_paid_plan
        else 'free'
    end                                                         as current_plan,
    -- Платящий = сконвертировался и не оттёк.
    (m.conversion_date is not null and m.has_churn_event = 0)   as is_paying,
    (m.has_churn_event = 1)                                     as is_churned_paid
from users u
left join activity a using (user_id)
left join monetization m using (user_id)
