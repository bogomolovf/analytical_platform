-- Уникальность первичного ключа user_id в stg_users (дубликаты сняты в staging).
select user_id, count(*) as n
from {{ ref('stg_users') }}
group by user_id
having count(*) > 1
