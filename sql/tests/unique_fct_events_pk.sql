-- Уникальность event_id в fct_events (в сыром слое event_id уникален,
-- дубликаты снимаются по бизнес-ключу — здесь проверяем итоговый ключ).
select event_id, count(*) as n
from {{ ref('fct_events') }}
group by event_id
having count(*) > 1
