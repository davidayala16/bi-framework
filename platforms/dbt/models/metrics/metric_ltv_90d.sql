select round(avg(revenue_first_90d), 2) as ltv_90d
from {{ ref('dim_customers') }}
where revenue_first_90d is not null
