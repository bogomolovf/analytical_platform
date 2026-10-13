-- ============================================================================
-- stg_events - очистка событийного лога.
--   * приведение типов (event_timestamp -> TIMESTAMP, event_value -> DOUBLE);
--   * удаление «событий из будущего» (таймстемп сильно позже окна данных);
--   * удаление аномальных покупок с отрицательной суммой;
--   * удаление ботов-выбросов (пользователи с >300 событий за один день);
--   * дедупликация по бизнес-ключу (user_id + event_name + ts + session_id).
-- ============================================================================
with source as (
    select
        cast(event_id as varchar)        as event_id,
        cast(user_id as varchar)         as user_id,
        nullif(cast(session_id as varchar), '') as session_id,
        lower(trim(event_name))          as event_name,
        cast(event_timestamp as timestamp) as event_timestamp,
        try_cast(event_value as double)  as event_value,
        nullif(lower(trim(plan)), '')    as plan
    from {{ source('raw', 'events') }}
),

-- Верхняя граница валидного окна: последняя регистрация + буфер 60 дней.
bounds as (
    select max(signup_ts) + interval 60 day as max_valid_ts
    from {{ ref('stg_users') }}
),

-- Боты: пользователи, у которых в какой-либо день более 300 событий.
bot_users as (
    select distinct user_id
    from source
    group by user_id, cast(event_timestamp as date)
    having count(*) > 300
),

cleaned as (
    select s.*
    from source s
    cross join bounds b
    where s.event_timestamp <= b.max_valid_ts          -- убираем будущие таймстемпы
      and s.user_id not in (select user_id from bot_users)  -- убираем ботов
      and not (s.event_name = 'purchase' and s.event_value < 0)  -- битые суммы
),

-- Дедупликация по бизнес-ключу: одинаковое событие пользователя в один момент.
deduped as (
    select *
    from (
        select
            *,
            row_number() over (
                partition by user_id, event_name, event_timestamp,
                             coalesce(session_id, '')
                order by event_id
            ) as rn
        from cleaned
    )
    where rn = 1
)

select
    event_id,
    user_id,
    session_id,
    event_name,
    event_timestamp,
    cast(event_timestamp as date) as event_date,
    event_value,
    plan
from deduped
