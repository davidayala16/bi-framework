select round(sum(revenue), 2) as net_revenue
from {{ ref('fct_order_items') }}
