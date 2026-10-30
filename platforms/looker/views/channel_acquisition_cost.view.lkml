# CAC inputs at channel grain. Spend and acquired customers are aggregated
# separately before joining (the same fix applied to the registry formula),
# so spend is never fanned out across customer rows. Keeping both inputs as
# additive measures means CAC is also correct when channels are combined.
view: channel_acquisition_cost {
  derived_table: {
    sql:
      WITH spend AS (
        SELECT channel, SUM(spend) AS spend
        FROM analytics.stg_marketing_spend
        GROUP BY channel
      ),
      acquired AS (
        SELECT first_order_channel AS channel, COUNT(*) AS acquired_customers
        FROM analytics.dim_customers
        WHERE first_order_channel IS NOT NULL
        GROUP BY first_order_channel
      )
      SELECT s.channel, s.spend, a.acquired_customers
      FROM spend s
      LEFT JOIN acquired a ON a.channel = s.channel ;;
  }

  dimension: channel {
    primary_key: yes
    type: string
    sql: ${TABLE}.channel ;;
  }

  measure: total_spend {
    label: "Marketing Spend"
    type: sum
    sql: ${TABLE}.spend ;;
    value_format_name: usd
  }

  measure: acquired_customers {
    label: "Acquired Customers"
    description: "Customers whose first order came through this channel."
    type: sum
    sql: ${TABLE}.acquired_customers ;;
  }

  measure: cac {
    label: "Customer Acquisition Cost by Channel"
    description: "Marketing spend divided by customers whose first order came through the channel."
    type: number
    sql: ${total_spend} / NULLIF(${acquired_customers}, 0) ;;
    value_format_name: usd
    tags: ["registry:cac_by_channel"]
  }
}
