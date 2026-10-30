{#- Use the schema exactly as configured (`analytics`) instead of dbt's
    default `<target_schema>_<custom_schema>` concatenation, so LookML and
    the parity tests can reference stable table names. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
