-- fct_order_items must neither drop nor duplicate revenue on its joins:
-- its total has to equal raw line-item revenue exactly. Returns a row
-- (and fails) if the two diverge.
with modeled as (
    select round(sum(revenue), 2) as revenue from {{ ref('fct_order_items') }}
),
raw_source as (
    select round(sum(quantity * cast(unit_price as {{ type_double() }})), 2) as revenue
    from {{ source('raw', 'order_items') }}
)
select modeled.revenue as modeled_revenue, raw_source.revenue as source_revenue
from modeled
cross join raw_source
where modeled.revenue <> raw_source.revenue
