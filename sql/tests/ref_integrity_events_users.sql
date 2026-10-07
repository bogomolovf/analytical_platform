-- Ссылочная целостность: каждый user_id в fct_events есть в dim_users.
select e.user_id
from {{ ref('fct_events') }} e
left join {{ ref('dim_users') }} u using (user_id)
where u.user_id is null
group by e.user_id
