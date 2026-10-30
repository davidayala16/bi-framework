select round(sum(order_revenue) / count(*), 2) as aov
from {{ ref('fct_orders') }}
