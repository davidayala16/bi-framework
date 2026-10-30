select
    month as spend_month,
    channel,
    spend
from {{ source('raw', 'marketing_spend') }}
