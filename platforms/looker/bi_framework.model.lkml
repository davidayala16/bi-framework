# LookML layer for the bi-framework demo.
#
# Looker sits on top of the dbt marts (analytics schema), never on raw
# tables. Every governed measure carries a `registry:<metric_id>` tag that
# links it to its definition in metrics/registry.yaml;
# tests/test_lookml_coverage.py fails CI if a registry metric has no tagged
# measure, if a tag points at a metric that doesn't exist, or if any view
# reads from outside the analytics schema.
#
# The connection name is a placeholder: there's no Looker instance behind
# this demo. Point it at a connection to the warehouse dbt builds into.

connection: "bi_framework_warehouse"

include: "/views/*.view.lkml"

datagroup: dbt_build {
  sql_trigger: SELECT MAX(order_date) FROM analytics.fct_orders ;;
  max_cache_age: "24 hours"
  description: "Invalidates cached results whenever a dbt build adds new orders."
}

persist_with: dbt_build

explore: fct_order_items {
  label: "Orders"
  description: "Revenue and order metrics at order-item grain, sliceable by channel, region, and category."

  join: dim_customers {
    type: left_outer
    relationship: many_to_one
    sql_on: ${fct_order_items.customer_id} = ${dim_customers.customer_id} ;;
  }
}

explore: dim_customers {
  label: "Customers"
  description: "Customer-grain cohort metrics: 90-day LTV, 90-day churn, and the acquisition funnel."
}

explore: repeat_purchase {
  label: "Repeat Purchase"
  description: "Repeat purchase rate that respects channel, region, and category filters."
}

explore: channel_acquisition_cost {
  label: "Customer Acquisition Cost"
  description: "Marketing spend and acquired customers by channel."
}
