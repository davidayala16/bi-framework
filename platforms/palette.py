"""Shared visual palette for bi-framework's platform demos.

Categorical (channel) and status (funnel outcome) colors, validated for
colorblind-safe adjacent separation and contrast via the project's dataviz
skill (`node scripts/validate_palette.js`). Both platforms/shiny and
platforms/slack-bot import this so a channel or outcome reads as the same
color everywhere it shows up, instead of each platform picking its own.
"""

CHANNEL_ORDER = ["direct", "email", "organic_search", "paid_social", "referral"]

CHANNEL_COLORS = {
    "direct": "#2a78d6",
    "email": "#eb6834",
    "organic_search": "#1baf7a",
    "paid_social": "#eda100",
    "referral": "#e87ba4",
}

# Ordinal, worst -> best; used both as the Sankey's outcome node order and
# as a status-style (not categorical) color: these are states, not series.
OUTCOME_ORDER = ["Never Purchased", "One-Time Buyer", "Repeat Buyer"]

OUTCOME_COLORS = {
    "Never Purchased": "#d03b3b",  # status: critical
    "One-Time Buyer": "#898781",  # neutral
    "Repeat Buyer": "#0ca30c",  # status: good
}

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
SURFACE = "#fcfcfb"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"
