{#- 64-bit floating point type, spelled the way each warehouse wants it.

    dbt's built-in `dbt.type_float()` is not safe here: on DuckDB and
    Databricks `float` is 32-bit, which would silently change every revenue
    figure. The raw money columns are 64-bit doubles in the synthetic
    warehouse, so staging casts to this type on every target to keep the
    arithmetic identical no matter how the raw tables were loaded. -#}
{% macro type_double() -%}
    {{ return(adapter.dispatch('type_double', 'bi_framework')()) }}
{%- endmacro %}

{% macro default__type_double() -%}
    double
{%- endmacro %}

{# Snowflake's FLOAT / DOUBLE are both 64-bit; FLOAT is its canonical name. #}
{% macro snowflake__type_double() -%}
    float
{%- endmacro %}

{% macro redshift__type_double() -%}
    double precision
{%- endmacro %}
