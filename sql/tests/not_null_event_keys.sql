-- NOT NULL для ключевых полей факта событий.
select *
from {{ ref('fct_events') }}
where user_id is null
   or event_id is null
   or event_timestamp is null
   or event_name is null
