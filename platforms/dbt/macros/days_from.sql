{#- `date_expr` shifted by `days` (negative = earlier), via dbt's
    cross-database `dateadd` so the 90-day cohort windows don't depend on
    DuckDB's interval-literal syntax. Only ever used inside comparisons:
    the result type differs by warehouse (date on Snowflake/Databricks,
    timestamp on DuckDB/Redshift), which is harmless against a date column
    but shouldn't be selected as an output column. -#}
{% macro days_from(date_expr, days) -%}
    {{ dbt.dateadd('day', days, date_expr) }}
{%- endmacro %}
