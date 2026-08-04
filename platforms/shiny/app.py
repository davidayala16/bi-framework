"""Hero dashboard for the bi-framework demo.

Deliberately light: a handful of value boxes plus one chart, all sourced
through metrics/resolver.py — the same module the Slack bot mock uses.
Nothing here defines a formula; it only renders what the registry says.

Run:
    python data/generate_synthetic_data.py   # once, to build the warehouse
    shiny run platforms/shiny/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shiny import App, reactive, render, ui

from metrics.resolver import distinct_values, load_registry, resolve_metric

registry = load_registry()
channels = ["All"] + distinct_values("channel")

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h4("bi-framework"),
        ui.p("Synthetic DTC e-commerce demo — every number below is "
             "resolved from metrics/registry.yaml, not hardcoded here."),
        ui.input_select("channel", "Channel", channels, selected="All"),
    ),
    ui.layout_columns(
        ui.value_box("Net Revenue", ui.output_text("net_revenue"), showcase="$"),
        ui.value_box("Average Order Value", ui.output_text("aov"), showcase="$"),
        ui.value_box("Repeat Purchase Rate", ui.output_text("repeat_purchase_rate"), showcase="%"),
        col_widths=[4, 4, 4],
    ),
    ui.layout_columns(
        ui.card(
            ui.card_header("Customer Acquisition Cost by Channel"),
            ui.p("Cohort metric — not affected by the sidebar filter; "
                 "CAC is already channel-grained.", class_="text-muted small"),
            ui.output_plot("cac_chart"),
        ),
        ui.card(
            ui.card_header("Retention Snapshot"),
            ui.output_text("ltv_90d"),
            ui.output_text("churn_rate_90d"),
        ),
        col_widths=[8, 4],
    ),
    title="bi-framework — DTC E-Commerce Demo",
)


def _filters(channel: str) -> dict:
    return {} if channel == "All" else {"channel": channel}


def server(input, output, session):
    @reactive.calc
    def channel_filter():
        return _filters(input.channel())

    @render.text
    def net_revenue():
        df = resolve_metric("net_revenue", channel_filter(), registry=registry)
        return f"${df['net_revenue'].iloc[0]:,.2f}"

    @render.text
    def aov():
        df = resolve_metric("aov", channel_filter(), registry=registry)
        return f"${df['aov'].iloc[0]:,.2f}"

    @render.text
    def repeat_purchase_rate():
        df = resolve_metric("repeat_purchase_rate", channel_filter(), registry=registry)
        return f"{df['repeat_purchase_rate_pct'].iloc[0]:.1f}%"

    @render.text
    def ltv_90d():
        df = resolve_metric("ltv_90d", registry=registry)
        return f"90-Day LTV: ${df['ltv_90d'].iloc[0]:,.2f}"

    @render.text
    def churn_rate_90d():
        df = resolve_metric("churn_rate_90d", registry=registry)
        return f"90-Day Churn: {df['churn_rate_90d_pct'].iloc[0]:.1f}%"

    @render.plot
    def cac_chart():
        import matplotlib.pyplot as plt

        df = resolve_metric("cac_by_channel", registry=registry)
        fig, ax = plt.subplots()
        ax.bar(df["channel"], df["cac"])
        ax.set_ylabel("CAC ($)")
        ax.set_xlabel("Channel")
        fig.autofmt_xdate(rotation=30)
        return fig


app = App(app_ui, server)
