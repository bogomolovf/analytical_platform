-- Доля удержания обязана лежать в диапазоне [0, 1].
select *
from {{ ref('cohort_retention') }}
where retention_rate < 0
   or retention_rate > 1
