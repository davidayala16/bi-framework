select
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price,
    quantity * unit_price as line_revenue
from {{ source('raw', 'order_items') }}
