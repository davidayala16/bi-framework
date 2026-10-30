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
    round(s.spend / nullif(a.acquired_customers, 0), 2) as cac
from spend_by_channel s
left join acquired_by_channel a on a.channel = s.channel
order by s.channel
