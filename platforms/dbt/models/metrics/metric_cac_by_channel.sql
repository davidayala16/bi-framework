select
    channel,
    round(spend / nullif(acquired_customers, 0), 2) as cac
from {{ ref('channel_acquisition') }}
order by channel
