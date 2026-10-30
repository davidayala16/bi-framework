select round(
    100.0 * sum(case when is_churned_90d then 1 else 0 end) / count(*),
    1
) as churn_rate_90d_pct
from {{ ref('dim_customers') }}
where is_churned_90d is not null
