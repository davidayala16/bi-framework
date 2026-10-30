-- Every customer lands in exactly one funnel outcome, so the funnel must
-- sum to the full customer count. Returns a row (and fails) if it doesn't.
with funnel as (
    select sum(customer_count) as funnel_total from {{ ref('metric_acquisition_funnel') }}
),
customers as (
    select count(*) as customer_total from {{ source('raw', 'customers') }}
)
select funnel_total, customer_total
from funnel, customers
where funnel_total != customer_total
