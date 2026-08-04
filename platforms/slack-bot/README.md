# Slack Bot (local mock)

Simulates a `/bi-report` Slack slash command that opens a multi-step
Block Kit modal: pick a report, set filters, choose delivery format. Runs
entirely on the terminal against the local synthetic warehouse — no Slack
workspace, app manifest, or token required, so anyone cloning the repo can
try it in under a minute.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/generate_synthetic_data.py   # builds data/warehouse.duckdb
python platforms/slack-bot/bot.py
```

Walk through the three prompts:
1. **Report** — any metric in `metrics/registry.yaml`
2. **Filters** — only shown for metrics with `filterable_dimensions` set;
   cohort metrics (CAC, LTV, churn) skip straight past this step
3. **Format** — `csv` (written to `platforms/slack-bot/output/`),
   `slack_text` (formatted mrkdwn block printed to the terminal), or
   `image` (a chart or big-number card, saved as a PNG)

## Mapping this to a real Slack app

The three steps correspond directly to Block Kit `views`:

| Mock step | Real Slack equivalent |
|---|---|
| Step 1 (pick report) | a `static_select` block in a modal `view`, options generated from `metrics/registry.yaml` |
| Step 2 (filters) | conditional blocks shown via `views.update` once a report is selected, populated from `metrics.resolver.distinct_values()` the same way the mock's prompts are |
| Step 3 (format) | a `radio_buttons` or `static_select` block, submitted via `view_submission` |
| Delivery | `csv`/`image` → `files.upload`; `slack_text` → `chat.postMessage` with the same mrkdwn block built here |

The business logic (`metrics/resolver.py`) doesn't change between the mock
and a real deployment — only the I/O layer around it does. That's the
point of keeping the resolver Slack-agnostic: a real app would be a
`slack_bolt` handler calling the exact same `resolve_metric()` used here
and by the Shiny app.
