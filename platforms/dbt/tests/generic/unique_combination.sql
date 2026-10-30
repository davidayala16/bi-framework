{#- Fails if any combination of `columns` appears more than once.
    A dependency-free stand-in for dbt_utils.unique_combination_of_columns,
    so the project runs with nothing but dbt-core + dbt-duckdb. -#}
{% test unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as row_count
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
