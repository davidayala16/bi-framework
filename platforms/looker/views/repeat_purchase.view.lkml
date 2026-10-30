# Repeat purchase rate has to be computed per customer *after* filtering
# orders: a customer who placed two orders overall but only one on
# paid_social is a one-time buyer when filtered to paid_social. A plain
# measure on fct_order_items can't express that, so this view uses
# templated filters to push channel/region/category into a derived table
# before counting orders per customer — the same semantics as the
# registry's filterable formula.
view: repeat_purchase {
  derived_table: {
    sql:
      SELECT
        customer_id,
        COUNT(DISTINCT order_id) AS order_count
      FROM analytics.fct_order_items
      WHERE {% condition channel_filter %} channel {% endcondition %}
        AND {% condition region_filter %} region {% endcondition %}
        AND {% condition category_filter %} category {% endcondition %}
      GROUP BY customer_id ;;
  }

  filter: channel_filter {
    label: "Channel"
    type: string
    suggest_explore: fct_order_items
    suggest_dimension: fct_order_items.channel
  }

  filter: region_filter {
    label: "Region"
    type: string
    suggest_explore: fct_order_items
    suggest_dimension: fct_order_items.region
  }

  filter: category_filter {
    label: "Category"
    type: string
    suggest_explore: fct_order_items
    suggest_dimension: fct_order_items.category
  }

  dimension: customer_id {
    primary_key: yes
    hidden: yes
    type: number
    sql: ${TABLE}.customer_id ;;
  }

  dimension: order_count {
    type: number
    sql: ${TABLE}.order_count ;;
  }

  measure: repeat_customers {
    hidden: yes
    type: count
    filters: [order_count: ">=2"]
  }

  measure: customers {
    hidden: yes
    type: count
  }

  measure: repeat_purchase_rate {
    label: "Repeat Purchase Rate"
    description: "Share of customers with 2+ distinct orders matching the filters, out of customers with at least one matching order."
    type: number
    sql: 100.0 * ${repeat_customers} / NULLIF(${customers}, 0) ;;
    value_format: "0.0\"%\""
    tags: ["registry:repeat_purchase_rate"]
  }
}
