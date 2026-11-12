-- `month` is a 'YYYY-MM' string in the raw table, not a date.
select
    month as spend_month,
    channel,
    cast(spend as {{ type_double() }}) as spend
from {{ source('raw', 'marketing_spend') }}
