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
        fig, ax = plt.subplots(figsize=(6, 4))
        if len(df) == 1 and len(df.columns) == 1:
            value = df.iloc[0, 0]
            ax.text(0.5, 0.5, f"{value:,}", fontsize=36, ha="center", va="center")
            ax.set_title(metric["name"])
            ax.axis("off")
        else:
            label_col = df.columns[0]
            value_col = df.columns[-1]
            ax.bar(df[label_col].astype(str), df[value_col])
            ax.set_title(metric["name"])
            ax.set_ylabel(value_col)
            plt.xticks(rotation=30, ha="right")
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"\n[would upload to Slack as an image] -> {path}")


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
