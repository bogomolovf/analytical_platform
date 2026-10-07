-- ============================================================================
-- stg_users — очистка и типизация таблицы пользователей.
--   * дедупликация по user_id (оставляем самую раннюю регистрацию);
--   * приведение типов (signup_ts -> TIMESTAMP);
--   * нормализация пропусков в гео/устройстве -> 'unknown';
--   * производные поля: дата регистрации и когорты (неделя/месяц).
-- ============================================================================
with source as (
    select
        cast(user_id as varchar)              as user_id,
        cast(signup_ts as timestamp)          as signup_ts,
        lower(trim(acquisition_channel))      as acquisition_channel,
        nullif(trim(country), '')             as country,
        nullif(trim(device), '')              as device,
        lower(trim(behavior_segment))         as behavior_segment,
        lower(trim(initial_plan))             as initial_plan
    from {{ source('raw', 'users') }}
),

-- Дедупликация: при дубликатах user_id берём строку с самой ранней регистрацией.
deduped as (
    select *
    from (
        select
            *,
            row_number() over (
                partition by user_id
                order by signup_ts asc
            ) as rn
        from source
    )
    where rn = 1
)

select
    user_id,
    signup_ts,
    cast(signup_ts as date)                                   as signup_date,
    date_trunc('week', signup_ts)::date                       as cohort_week,
    date_trunc('month', signup_ts)::date                      as cohort_month,
    coalesce(acquisition_channel, 'unknown')                  as acquisition_channel,
    coalesce(country, 'unknown')                              as country,
    coalesce(device, 'unknown')                               as device,
    behavior_segment,
    coalesce(initial_plan, 'free')                            as initial_plan
from deduped
