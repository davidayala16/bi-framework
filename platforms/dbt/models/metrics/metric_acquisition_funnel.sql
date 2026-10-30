select
    acquisition_channel as channel,
    purchase_outcome as outcome,
    count(*) as customer_count
from {{ ref('dim_customers') }}
group by acquisition_channel, purchase_outcome
order by acquisition_channel, purchase_outcome
