-- Customer grain, including customers who never ordered. Holds the
-- customer-level facts the cohort metrics (LTV, churn, acquisition funnel,
-- CAC attribution) are built from, so those metrics and their LookML
-- measures read one shared definition of "first order" and "last order".
with order_stats as (
    select
        customer_id,
        min(order_date) as first_order_date,
        max(order_date) as last_order_date,
        count(*) as order_count,
        max(case when customer_order_number = 1 then channel end) as first_order_channel
    from {{ ref('fct_orders') }}
    group by customer_id
),

revenue_90d as (
    select
        o.customer_id,
        sum(o.order_revenue) as revenue_first_90d
    from {{ ref('fct_orders') }} o
    join order_stats s on s.customer_id = o.customer_id
    where o.order_date <= {{ days_from('s.first_order_date', 90) }}
    group by o.customer_id
),

dataset_bounds as (
    select max(order_date) as as_of_date from {{ ref('fct_orders') }}
)

select
    c.customer_id,
    c.signup_date,
    c.acquisition_channel,
    c.region,
    s.first_order_date,
    s.last_order_date,
    s.first_order_channel,
    coalesce(s.order_count, 0) as order_count,
    r.revenue_first_90d,
    case
        when s.order_count is null then 'Never Purchased'
        when s.order_count = 1 then 'One-Time Buyer'
        else 'Repeat Buyer'
    end as purchase_outcome,
    -- null for customers with no orders: churn only applies to buyers
    case
        when s.last_order_date is null then cast(null as {{ dbt.type_boolean() }})
        when s.last_order_date <= {{ days_from('b.as_of_date', -90) }} then true
        else false
    end as is_churned_90d
from {{ ref('stg_customers') }} c
left join order_stats s on s.customer_id = c.customer_id
left join revenue_90d r on r.customer_id = c.customer_id
cross join dataset_bounds b
