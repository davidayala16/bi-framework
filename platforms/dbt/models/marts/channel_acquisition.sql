-- Channel grain: the two additive inputs to CAC. Spend and acquired
-- customers are each aggregated to channel grain *before* joining, so spend
-- is never fanned out across customer rows. Keeping them as separate
-- columns (rather than only the ratio) lets semantic layers recompute CAC
-- correctly when channels are combined.
with spend_by_channel as (
    select channel, sum(spend) as spend
    from {{ ref('stg_marketing_spend') }}
    group by channel
),

acquired_by_channel as (
    select first_order_channel as channel, count(*) as acquired_customers
    from {{ ref('dim_customers') }}
    where first_order_channel is not null
    group by first_order_channel
)

select
    s.channel,
    s.spend,
    a.acquired_customers
from spend_by_channel s
left join acquired_by_channel a on a.channel = s.channel
