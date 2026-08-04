# Shiny Dashboard (Python)

The hero, fully-working demo platform. Renders value boxes and a chart
entirely from `metrics/resolver.py` — this file has no metric formulas of
its own, only presentation.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/generate_synthetic_data.py   # builds data/warehouse.duckdb
shiny run platforms/shiny/app.py
```

Open http://127.0.0.1:8000. Use the channel dropdown in the sidebar to
re-slice Net Revenue, AOV, and Repeat Purchase Rate — those are the three
metrics in the registry marked `filterable_dimensions: [channel, ...]`.
CAC, LTV, and Churn are cohort metrics and intentionally don't respond to
the filter; the app doesn't hide that, it labels it.

## Why it's "light" on purpose

This isn't meant to be a polished production dashboard — it's meant to
prove the pattern: swap `metrics/registry.yaml`, and this app's numbers
change with zero code edits here. Deploying it live (shinyapps.io, Posit
Connect, etc.) is a couple of commands away if you want a hosted demo link,
but isn't included here so the repo has no ongoing hosting dependency.
