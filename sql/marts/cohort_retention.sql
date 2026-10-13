-- ============================================================================
-- cohort_retention - витрина недельного удержания по когортам.
-- Когорта = неделя регистрации. Для каждой пары (когорта, N недель с момента
-- регистрации) считаем число активных пользователей и долю удержания.
-- Используется для когортной heatmap на дашборде.
-- ============================================================================
with users as (
    select user_id, cohort_week from {{ ref('dim_users') }}
),

-- Недели, в которые пользователь был активен (по реальной активности).
activity_weeks as (
    select distinct
        user_id,
        date_trunc('week', event_timestamp)::date as activity_week
    from {{ ref('fct_events') }}
    where event_name not in ('purchase', 'churn')
),

-- Смещение активности от когорты в неделях.
cohort_activity as (
    select
        u.cohort_week,
        date_diff('week', u.cohort_week, a.activity_week) as week_number,
        a.user_id
    from users u
    inner join activity_weeks a using (user_id)
    where a.activity_week >= u.cohort_week
),

cohort_size as (
    select cohort_week, count(*) as cohort_users
    from users
    group by cohort_week
),

retained as (
    select
        cohort_week,
        week_number,
        count(distinct user_id) as active_users
    from cohort_activity
    group by cohort_week, week_number
)

select
    r.cohort_week,
    r.week_number,
    s.cohort_users,
    r.active_users,
    round(r.active_users::double / nullif(s.cohort_users, 0), 4) as retention_rate
from retained r
inner join cohort_size s using (cohort_week)
order by r.cohort_week, r.week_number
