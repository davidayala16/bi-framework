select round(
    100.0 * sum(case when order_count >= 2 then 1 else 0 end) / count(*),
    1
) as repeat_purchase_rate_pct
from {{ ref('dim_customers') }}
where order_count > 0
