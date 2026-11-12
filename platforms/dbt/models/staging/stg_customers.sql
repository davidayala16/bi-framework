select
    cast(customer_id as {{ dbt.type_bigint() }}) as customer_id,
    cast(signup_date as date) as signup_date,
    acquisition_channel,
    region
from {{ source('raw', 'customers') }}
