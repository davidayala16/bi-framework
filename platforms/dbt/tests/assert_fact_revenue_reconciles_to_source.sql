-- fct_order_items must neither drop nor duplicate revenue on its joins:
-- its total has to equal raw line-item revenue exactly. Returns a row
-- (and fails) if the two diverge.
with modeled as (
    select round(sum(revenue), 2) as revenue from {{ ref('fct_order_items') }}
),
source as (
    select round(sum(quantity * unit_price), 2) as revenue
    from {{ source('raw', 'order_items') }}
)
select modeled.revenue as modeled_revenue, source.revenue as source_revenue
from modeled, source
where modeled.revenue != source.revenue
