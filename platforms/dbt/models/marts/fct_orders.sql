-- Order grain: one row per order with its total, plus where it falls in
-- the customer's order sequence (first order = acquisition order).
with order_totals as (
    select
        order_id,
        sum(line_revenue) as order_revenue,
        count(*) as line_item_count
    from {{ ref('stg_order_items') }}
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    o.order_date,
    o.channel,
    c.region,
    t.order_revenue,
    t.line_item_count,
    row_number() over (
        partition by o.customer_id order by o.order_date, o.order_id
    ) as customer_order_number
from {{ ref('stg_orders') }} o
join order_totals t on t.order_id = o.order_id
join {{ ref('stg_customers') }} c on c.customer_id = o.customer_id
