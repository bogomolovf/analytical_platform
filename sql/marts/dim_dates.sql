-- ============================================================================
-- dim_dates - календарное измерение (date spine).
-- Непрерывный ряд дат от первого до последнего события с атрибутами календаря.
-- Нужен, чтобы корректно строить временные ряды без «дыр» в активности.
-- ============================================================================
with bounds as (
    select
        min(event_date) as start_date,
        max(event_date) as end_date
    from {{ ref('fct_events') }}
),

spine as (
    select unnest(generate_series(
        (select start_date from bounds),
        (select end_date from bounds),
        interval 1 day
    ))::date as date_day
)

select
    date_day,
    extract(year from date_day)                          as year,
    extract(quarter from date_day)                       as quarter,
    extract(month from date_day)                         as month,
    strftime(date_day, '%Y-%m')                          as year_month,
    extract(week from date_day)                          as iso_week,
    date_trunc('week', date_day)::date                   as week_start,
    date_trunc('month', date_day)::date                  as month_start,
    extract(dow from date_day)                           as day_of_week,
    (extract(dow from date_day) in (0, 6))               as is_weekend,
    strftime(date_day, '%A')                             as day_name
from spine
