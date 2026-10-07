-- «События из будущего» должны быть отфильтрованы на слое staging.
select e.*
from {{ ref('fct_events') }} e
cross join (
    select max(signup_date) + interval 60 day as max_valid_date
    from {{ ref('dim_users') }}
) b
where e.event_date > b.max_valid_date
