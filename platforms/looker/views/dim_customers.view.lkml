# Customer grain, built by dbt (platforms/dbt/models/marts/dim_customers.sql).
# Cohort metrics live here; like the registry, they're defined over the full
# dataset window rather than responding to order-level filters.
view: dim_customers {
  sql_table_name: analytics.dim_customers ;;

  dimension: customer_id {
    primary_key: yes
    type: number
    sql: ${TABLE}.customer_id ;;
  }

  dimension: acquisition_channel {
    type: string
    description: "Channel the customer was acquired through, fixed at signup."
    sql: ${TABLE}.acquisition_channel ;;
  }

  dimension: region {
    type: string
    sql: ${TABLE}.region ;;
  }

  dimension: purchase_outcome {
    type: string
    description: "Never Purchased / One-Time Buyer / Repeat Buyer."
    sql: ${TABLE}.purchase_outcome ;;
  }

  dimension: order_count {
    type: number
    sql: ${TABLE}.order_count ;;
  }

  dimension: revenue_first_90d {
    hidden: yes
    type: number
    sql: ${TABLE}.revenue_first_90d ;;
  }

  dimension: is_churned_90d {
    type: yesno
    description: "Most recent order is 90+ days before the dataset's last order date. Null for customers who never ordered."
    sql: ${TABLE}.is_churned_90d ;;
  }

  measure: customer_count {
    label: "Customers"
    description: "Customer count by acquisition channel and purchase outcome — the acquisition funnel when grouped by those two dimensions."
    type: count
    tags: ["registry:acquisition_funnel"]
  }

  measure: ltv_90d {
    label: "90-Day Customer Lifetime Value"
    description: "Average net revenue per customer within 90 days of their first order. No discounting or margin adjustment."
    type: average
    sql: ${revenue_first_90d} ;;
    value_format_name: usd
    tags: ["registry:ltv_90d"]
  }

  measure: churned_customers {
    hidden: yes
    type: count
    filters: [is_churned_90d: "yes"]
  }

  measure: purchasing_customers {
    hidden: yes
    type: count
    filters: [order_count: ">0"]
  }

  measure: churn_rate_90d {
    label: "90-Day Churn Rate"
    description: "Share of purchasing customers whose most recent order is more than 90 days before the dataset's max order date."
    type: number
    sql: 100.0 * ${churned_customers} / NULLIF(${purchasing_customers}, 0) ;;
    value_format: "0.0\"%\""
    tags: ["registry:churn_rate_90d"]
  }
}
