-- Explicit casts so the arithmetic downstream is the same 64-bit float math
-- on every warehouse, however the raw table was loaded.
with typed as (
    select
        cast(order_item_id as {{ dbt.type_bigint() }}) as order_item_id,
        cast(order_id as {{ dbt.type_bigint() }}) as order_id,
        cast(product_id as {{ dbt.type_bigint() }}) as product_id,
        cast(quantity as {{ dbt.type_bigint() }}) as quantity,
        cast(unit_price as {{ type_double() }}) as unit_price
    from {{ source('raw', 'order_items') }}
)

select
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price,
    quantity * unit_price as line_revenue
from typed
