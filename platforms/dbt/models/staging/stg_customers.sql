select
    customer_id,
    cast(signup_date as date) as signup_date,
    acquisition_channel,
    region
from {{ source('raw', 'customers') }}
