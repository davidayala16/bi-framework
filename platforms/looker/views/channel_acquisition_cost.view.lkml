# CAC inputs at channel grain, built by dbt
# (platforms/dbt/models/marts/channel_acquisition.sql). Spend and acquired
# customers are aggregated separately before joining (the same fix applied
# to the registry formula), so spend is never fanned out across customer
# rows. Keeping both inputs as additive measures means CAC is also correct
# when channels are combined.
view: channel_acquisition_cost {
  sql_table_name: analytics.channel_acquisition ;;

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
