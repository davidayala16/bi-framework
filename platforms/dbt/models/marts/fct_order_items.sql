-- Order-item grain fact table. The dbt equivalent of `base_fact_sql` in
-- metrics/registry.yaml: built once in the warehouse instead of re-derived
-- by every query. Every filterable metric (net_revenue, aov,
-- repeat_purchase_rate) and every LookML measure aggregates over this table.
select
    oi.order_item_id,
    o.order_id,
    o.order_date,
    o.customer_id,
    o.channel,
    c.region,
    p.category,
    p.product_id,
    oi.quantity,
    oi.unit_price,
    oi.line_revenue as revenue
from {{ ref('stg_order_items') }} oi
join {{ ref('stg_orders') }} o on o.order_id = oi.order_id
join {{ ref('stg_customers') }} c on c.customer_id = o.customer_id
join {{ ref('stg_products') }} p on p.product_id = oi.product_id
