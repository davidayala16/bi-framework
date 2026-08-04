"""Local mock of a Slack BI-report bot.

Simulates the multi-step Block Kit modal a real Slack app would show:
  1. Pick a report (a metric from the registry)
  2. Enter filters (optional, only for filterable metrics)
  3. Pick an output format: CSV / Slack text / image

Runs entirely on the terminal against the local synthetic warehouse — no
Slack workspace, app, or token required. See README.md in this folder for
how this maps onto a real Slack app (Block Kit views + slash command) if
you wanted to actually deploy it.

Run:
    python platforms/slack-bot/bot.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from metrics.resolver import (
    ALLOWED_FILTER_COLUMNS,
    UnsupportedFilterError,
    distinct_values,
    list_metrics,
    load_registry,
    resolve_metric,
)
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
)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def prompt_choice(label: str, options: list[str]) -> str:
    print(f"\n{label}")
    for i, opt in enumerate(options, start=1):
        print(f"  {i}. {opt}")
    while True:
        raw = input("Select an option: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("Not a valid choice, try again.")


def step_1_pick_report(registry: dict) -> dict:
    metrics = list_metrics(registry)
    labels = [f"{m['name']} ({m['category']})" for m in metrics]
    choice = prompt_choice("Step 1/3 — Pick which report to generate:", labels)
    return metrics[labels.index(choice)]


def step_2_pick_filters(metric: dict) -> dict[str, str]:
    dims = metric["filterable_dimensions"]
    if not dims:
        print(f"\nStep 2/3 — {metric['name']} is a cohort metric and doesn't "
              f"support filters. Skipping.")
        return {}

    print(f"\nStep 2/3 — Filters for {metric['name']} "
          f"(supported: {', '.join(dims)}). Leave blank for none.")
    filters: dict[str, str] = {}
    for dim in dims:
        values = distinct_values(dim)
        raw = input(f"  {dim} [{', '.join(values)}] (blank = all): ").strip()
        if not raw:
            continue
        if raw not in values:
            print(f"  '{raw}' isn't a known {dim}, skipping this filter.")
            continue
        filters[dim] = raw
    return filters


def step_3_pick_format() -> str:
    return prompt_choice(
        "Step 3/3 — How should the result be delivered?",
        ["csv", "slack_text", "image"],
    )


def deliver(metric: dict, df, filters: dict[str, str], fmt: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{metric['id']}_{stamp}"

    if fmt == "csv":
        path = OUTPUT_DIR / f"{base_name}.csv"
        df.to_csv(path, index=False)
        print(f"\n[would upload to Slack as a file] -> {path}")

    elif fmt == "slack_text":
        filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items()) or "none"
        lines = [
            f"*{metric['name']}*  _(filters: {filter_desc})_",
            "```",
            df.to_string(index=False),
            "```",
        ]
        message = "\n".join(lines)
        print("\n[would post to Slack as a message]\n")
        print(message)

    elif fmt == "image":
        path = OUTPUT_DIR / f"{base_name}.png"
        fig = _render_image(metric, df)
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"\n[would upload to Slack as an image] -> {path}")


def _style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRIDLINE)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(colors=INK_SECONDARY, labelsize=10)
    ax.yaxis.grid(True, color=GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def _render_image(metric: dict, df):
    """Three shapes: a single scalar -> a stat card; a two-column result
    (label, value) -> a bar chart, colored by channel when the label is a
    channel; a three-column result (channel, outcome, count) -> a stacked
    bar, one segment per outcome. Same palette as the Shiny dashboard.
    """
    if len(df) == 1 and len(df.columns) == 1:
        fig, ax = plt.subplots(figsize=(6, 4))
        fig.patch.set_facecolor(SURFACE)
        ax.set_facecolor(SURFACE)
        value = df.iloc[0, 0]
        formatted = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
        if metric["unit"] == "USD":
            formatted = f"${formatted}"
        elif metric["unit"] == "percent":
            formatted = f"{formatted}%"
        ax.text(0.5, 0.55, formatted, fontsize=40, ha="center", va="center",
                 color=INK_PRIMARY, fontweight="bold")
        ax.text(0.5, 0.22, metric["name"], fontsize=13, ha="center", va="center",
                 color=INK_SECONDARY)
        ax.axis("off")
        return fig

    if len(df.columns) == 3:
        pivot = df.pivot(index=df.columns[0], columns=df.columns[1], values=df.columns[2])
        row_order = [c for c in CHANNEL_ORDER if c in pivot.index]
        pivot = pivot.reindex(row_order)
        col_order = [o for o in OUTCOME_ORDER if o in pivot.columns]
        pivot = pivot[col_order]

        fig, ax = plt.subplots(figsize=(7, 4.5))
        fig.patch.set_facecolor(SURFACE)
        bottoms = [0] * len(pivot)
        for outcome in col_order:
            values = pivot[outcome].fillna(0).values
            ax.bar(
                pivot.index, values, bottom=bottoms,
                color=OUTCOME_COLORS[outcome], label=outcome,
                width=0.6, edgecolor=SURFACE, linewidth=2, zorder=3,
            )
            bottoms = [b + v for b, v in zip(bottoms, values)]
        _style_axes(ax)
        ax.set_ylabel("Customers", color=INK_SECONDARY, fontsize=11)
        ax.legend(
            loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3,
            frameon=False, fontsize=9, labelcolor=INK_SECONDARY,
        )
        ax.margins(y=0.1)
        plt.xticks(rotation=25, ha="right")
        fig.suptitle(metric["name"], color=INK_PRIMARY, fontsize=13, y=0.98)
        fig.tight_layout(rect=(0, 0.05, 1, 0.95))
        return fig

    label_col, value_col = df.columns[0], df.columns[-1]
    colors = [
        CHANNEL_COLORS.get(str(v), "#2a78d6") for v in df[label_col]
    ]
    fig, ax = plt.subplots(figsize=(6.5, 4))
    fig.patch.set_facecolor(SURFACE)
    bars = ax.bar(df[label_col].astype(str), df[value_col], color=colors, width=0.6, zorder=3)
    for bar, value in zip(bars, df[value_col]):
        label = f"{value:,.0f}" if float(value) >= 1 else f"{value:,.2f}"
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), label,
                 ha="center", va="bottom", fontsize=10, color=INK_PRIMARY)
    _style_axes(ax)
    ax.set_ylabel(value_col, color=INK_SECONDARY, fontsize=11)
    ax.margins(y=0.15)
    fig.suptitle(metric["name"], color=INK_PRIMARY, fontsize=13, y=0.98)
    plt.xticks(rotation=25, ha="right")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def main() -> None:
    print("=== BI Report Bot (local mock) ===")
    print("Simulates the /bi-report Slack modal against the synthetic warehouse.")
    registry = load_registry()

    metric = step_1_pick_report(registry)
    filters = step_2_pick_filters(metric)

    try:
        df = resolve_metric(metric["id"], filters, registry=registry)
    except UnsupportedFilterError as e:
        print(f"\nCouldn't run that report: {e}")
        return

    fmt = step_3_pick_format()
    deliver(metric, df, filters, fmt)


if __name__ == "__main__":
    main()
