-- Уникальность session_id в витрине сессий.
select session_id, count(*) as n
from {{ ref('fct_sessions') }}
group by session_id
having count(*) > 1
