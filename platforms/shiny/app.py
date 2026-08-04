"""Hero dashboard for the bi-framework demo.

Deliberately light: value boxes, a Sankey funnel, and a CAC chart, all
sourced through metrics/resolver.py — the same module the Slack bot mock
uses. Nothing here defines a formula; it only renders what the registry
says. Colors come from platforms/palette.py, shared with the Slack bot so
a channel/outcome reads the same color on both platforms.

Run:
    python data/generate_synthetic_data.py   # once, to build the warehouse
    shiny run platforms/shiny/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go
from shiny import App, reactive, render, ui

from metrics.resolver import distinct_values, load_registry, resolve_metric
from platforms.palette import (
    BASELINE,
    CHANNEL_COLORS,
    CHANNEL_ORDER,
    GRIDLINE,
    INK_PRIMARY,
    INK_SECONDARY,
    OUTCOME_COLORS,
    OUTCOME_ORDER,
    SURFACE,
    hex_to_rgba,
)

registry = load_registry()
channels = ["All"] + distinct_values("channel")

FONT_FAMILY = "system-ui, -apple-system, Segoe UI, sans-serif"


def _evenly_spaced(n: int, low: float = 0.06, high: float = 0.94):
    if n == 1:
        return [0.5]
    step = (high - low) / (n - 1)
    return [low + i * step for i in range(n)]

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
    ui.card(
        ui.card_header("Acquisition Funnel: Channel → Customer Outcome"),
        ui.p("Sourced from the acquisition_funnel metric — a cohort metric, "
             "not affected by the sidebar filter.", class_="text-muted small"),
        ui.output_ui("acquisition_sankey"),
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

    @render.ui
    def acquisition_sankey():
        df = resolve_metric("acquisition_funnel", registry=registry)

        # Fixed top-to-bottom order, independent of plotly's default
        # crossing-minimization layout, so channel order stays the same
        # alphabetical order used by every other chart/dropdown in the repo.
        sankey_outcome_order = ["Repeat Buyer", "One-Time Buyer", "Never Purchased"]

        node_labels = list(CHANNEL_ORDER) + sankey_outcome_order
        node_colors = [CHANNEL_COLORS[c] for c in CHANNEL_ORDER] + [
            OUTCOME_COLORS[o] for o in sankey_outcome_order
        ]
        node_index = {label: i for i, label in enumerate(node_labels)}

        n_channels = len(CHANNEL_ORDER)
        n_outcomes = len(sankey_outcome_order)
        node_x = [0.01] * n_channels + [0.99] * n_outcomes
        node_y = (
            list(_evenly_spaced(n_channels)) + list(_evenly_spaced(n_outcomes))
        )

        sources, targets, values, link_colors = [], [], [], []
        for _, row in df.iterrows():
            sources.append(node_index[row["channel"]])
            targets.append(node_index[row["outcome"]])
            values.append(int(row["customer_count"]))
            link_colors.append(hex_to_rgba(CHANNEL_COLORS[row["channel"]], 0.38))

        fig = go.Figure(
            data=[
                go.Sankey(
                    arrangement="fixed",
                    node=dict(
                        pad=22,
                        thickness=16,
                        line=dict(color=BASELINE, width=0.5),
                        label=node_labels,
                        color=node_colors,
                        x=node_x,
                        y=node_y,
                    ),
                    link=dict(
                        source=sources,
                        target=targets,
                        value=values,
                        color=link_colors,
                        hovertemplate="%{source.label} → %{target.label}: "
                        "%{value} customers<extra></extra>",
                    ),
                )
            ]
        )
        fig.update_layout(
            font=dict(family=FONT_FAMILY, size=13, color=INK_PRIMARY),
            paper_bgcolor=SURFACE,
            plot_bgcolor=SURFACE,
            margin=dict(l=10, r=10, t=10, b=10),
            height=380,
        )
        html = fig.to_html(
            include_plotlyjs=True,
            full_html=False,
            config={"displayModeBar": False, "responsive": True},
        )
        return ui.HTML(html)

    @render.plot
    def cac_chart():
        import matplotlib.pyplot as plt

        df = resolve_metric("cac_by_channel", registry=registry)
        colors = [CHANNEL_COLORS[c] for c in df["channel"]]

        fig, ax = plt.subplots(figsize=(6.5, 4))
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)

        bars = ax.bar(df["channel"], df["cac"], color=colors, width=0.6, zorder=3)
        for bar, value in zip(bars, df["cac"]):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"${value:,.0f}",
                ha="center",
                va="bottom",
                fontsize=10,
                color=INK_PRIMARY,
            )

        ax.set_ylabel("CAC ($)", color=INK_SECONDARY, fontsize=11)
        ax.set_xlabel("")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(GRIDLINE)
        ax.spines["bottom"].set_color(BASELINE)
        ax.tick_params(colors=INK_SECONDARY, labelsize=10)
        ax.yaxis.grid(True, color=GRIDLINE, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        ax.margins(y=0.15)
        fig.autofmt_xdate(rotation=25)
        fig.tight_layout()
        return fig


app = App(app_ui, server)
