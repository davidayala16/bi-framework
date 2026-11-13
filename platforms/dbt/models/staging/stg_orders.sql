select
    cast(order_id as {{ dbt.type_bigint() }}) as order_id,
    cast(customer_id as {{ dbt.type_bigint() }}) as customer_id,
    cast(order_date as date) as order_date,
    channel
from {{ source('raw', 'orders') }}
