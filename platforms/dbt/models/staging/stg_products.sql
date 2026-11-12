select
    cast(product_id as {{ dbt.type_bigint() }}) as product_id,
    product_name,
    category,
    cast(unit_cost as {{ type_double() }}) as unit_cost,
    cast(unit_price as {{ type_double() }}) as unit_price
from {{ source('raw', 'products') }}
