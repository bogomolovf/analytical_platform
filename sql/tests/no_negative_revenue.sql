-- Аномальные покупки с отрицательной суммой должны быть очищены.
select *
from {{ ref('fct_events') }}
where event_name = 'purchase'
  and event_value < 0
