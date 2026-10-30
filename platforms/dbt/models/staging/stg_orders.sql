select
    order_id,
    customer_id,
    cast(order_date as date) as order_date,
    channel
from {{ source('raw', 'orders') }}
