# Order-item grain fact, built by dbt (platforms/dbt/models/marts/fct_order_items.sql).
view: fct_order_items {
  sql_table_name: analytics.fct_order_items ;;

  dimension: order_item_id {
    primary_key: yes
    hidden: yes
    type: number
    sql: ${TABLE}.order_item_id ;;
  }

  dimension: order_id {
    type: number
    sql: ${TABLE}.order_id ;;
  }

  dimension: customer_id {
    hidden: yes
    type: number
    sql: ${TABLE}.customer_id ;;
  }

  dimension_group: order {
    type: time
    timeframes: [date, week, month, quarter, year]
    datatype: date
    sql: ${TABLE}.order_date ;;
  }

  dimension: channel {
    type: string
    description: "Channel the order came through (per-order, not the customer's acquisition channel)."
    sql: ${TABLE}.channel ;;
  }

  dimension: region {
    type: string
    sql: ${TABLE}.region ;;
  }

  dimension: category {
    type: string
    sql: ${TABLE}.category ;;
  }

  dimension: quantity {
    type: number
    sql: ${TABLE}.quantity ;;
  }

  dimension: revenue {
    hidden: yes
    type: number
    sql: ${TABLE}.revenue ;;
  }

  measure: net_revenue {
    label: "Net Revenue"
    description: "Total revenue recognized across all order line items in the period. Gross of returns — the synthetic dataset has no returns table."
    type: sum
    sql: ${revenue} ;;
    value_format_name: usd
    tags: ["registry:net_revenue"]
  }

  measure: order_count {
    label: "Orders"
    type: count_distinct
    sql: ${order_id} ;;
  }

  measure: aov {
    label: "Average Order Value"
    description: "Net revenue divided by distinct orders. Computed at order grain, so multi-item orders aren't double counted."
    type: number
    sql: ${net_revenue} / NULLIF(${order_count}, 0) ;;
    value_format_name: usd
    tags: ["registry:aov"]
  }
}
