"""Generates a synthetic DTC e-commerce dataset for the bi-framework demo.

Everything here is fabricated with a fixed random seed. No real business,
customer, or transaction data is used anywhere in this repository.

Run:
    python data/generate_synthetic_data.py

Produces CSVs under data/synthetic/ and a DuckDB warehouse at
data/warehouse.duckdb (both gitignored — regenerate on demand, or via
scripts/build_warehouse.sh which calls this automatically).
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

SEED = 42
random.seed(SEED)

OUT_DIR = Path(__file__).parent / "synthetic"
WAREHOUSE_PATH = Path(__file__).parent / "warehouse.duckdb"

START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 6, 30)
NUM_CUSTOMERS = 600
NUM_ORDERS = 2400
MAX_ITEMS_PER_ORDER = 4

CHANNELS = ["paid_social", "organic_search", "email", "referral", "direct"]
REGIONS = ["West", "Midwest", "South", "Northeast"]
CATEGORIES = ["Apparel", "Footwear", "Accessories", "Home"]

# Rough acquisition cost skew per channel, used to derive synthetic spend.
CHANNEL_COST_WEIGHT = {
    "paid_social": 1.6,
    "organic_search": 0.3,
    "email": 0.4,
    "referral": 0.2,
    "direct": 0.1,
}


def _random_date(start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, delta_days))


def build_products(n: int = 40) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        category = random.choice(CATEGORIES)
        unit_cost = round(random.uniform(8, 60), 2)
        margin = random.uniform(1.6, 3.2)
        rows.append(
            {
                "product_id": i,
                "product_name": f"{category} Item {i:03d}",
                "category": category,
                "unit_cost": unit_cost,
                "unit_price": round(unit_cost * margin, 2),
            }
        )
    return pd.DataFrame(rows)


def build_customers(n: int = NUM_CUSTOMERS) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        rows.append(
            {
                "customer_id": i,
                "signup_date": _random_date(START_DATE, END_DATE),
                "acquisition_channel": random.choices(
                    CHANNELS, weights=[35, 25, 15, 15, 10]
                )[0],
                "region": random.choice(REGIONS),
            }
        )
    return pd.DataFrame(rows)


def build_orders_and_items(
    customers: pd.DataFrame, products: pd.DataFrame, n_orders: int = NUM_ORDERS
):
    order_rows = []
    item_rows = []
    item_id = 1

    # Skew repeat orders towards a subset of customers so repeat-purchase /
    # churn metrics have real signal instead of being uniformly random.
    loyal_customers = customers.sample(frac=0.35, random_state=SEED)["customer_id"].tolist()

    for order_id in range(1, n_orders + 1):
        if random.random() < 0.55 and loyal_customers:
            customer_id = random.choice(loyal_customers)
        else:
            customer_id = random.choice(customers["customer_id"].tolist())

        signup = customers.loc[
            customers["customer_id"] == customer_id, "signup_date"
        ].iloc[0]
        order_date = _random_date(max(signup, START_DATE), END_DATE)

        order_rows.append(
            {
                "order_id": order_id,
                "customer_id": customer_id,
                "order_date": order_date,
                "channel": random.choice(CHANNELS),
            }
        )

        n_items = random.randint(1, MAX_ITEMS_PER_ORDER)
        for _ in range(n_items):
            product = products.sample(1, random_state=random.randint(0, 10_000)).iloc[0]
            item_rows.append(
                {
                    "order_item_id": item_id,
                    "order_id": order_id,
                    "product_id": int(product["product_id"]),
                    "quantity": random.randint(1, 3),
                    "unit_price": product["unit_price"],
                }
            )
            item_id += 1

    return pd.DataFrame(order_rows), pd.DataFrame(item_rows)


def build_marketing_spend(orders: pd.DataFrame) -> pd.DataFrame:
    """Synthetic monthly spend per channel, scaled so CAC comes out realistic."""
    orders = orders.copy()
    orders["month"] = pd.to_datetime(orders["order_date"]).dt.to_period("M").astype(str)
    order_counts = orders.groupby(["month", "channel"]).size().reset_index(name="orders")

    rows = []
    for _, r in order_counts.iterrows():
        weight = CHANNEL_COST_WEIGHT[r["channel"]]
        base_spend_per_order = random.uniform(18, 32) * weight
        spend = round(r["orders"] * base_spend_per_order, 2)
        rows.append({"month": r["month"], "channel": r["channel"], "spend": spend})
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    products = build_products()
    customers = build_customers()
    orders, order_items = build_orders_and_items(customers, products)
    marketing_spend = build_marketing_spend(orders)

    products.to_csv(OUT_DIR / "products.csv", index=False)
    customers.to_csv(OUT_DIR / "customers.csv", index=False)
    orders.to_csv(OUT_DIR / "orders.csv", index=False)
    order_items.to_csv(OUT_DIR / "order_items.csv", index=False)
    marketing_spend.to_csv(OUT_DIR / "marketing_spend.csv", index=False)

    if WAREHOUSE_PATH.exists():
        WAREHOUSE_PATH.unlink()

    con = duckdb.connect(str(WAREHOUSE_PATH))
    for name in ["products", "customers", "orders", "order_items", "marketing_spend"]:
        con.execute(
            f"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{OUT_DIR / (name + '.csv')}')"
        )
    con.close()

    print(f"Wrote {len(customers)} customers, {len(orders)} orders, "
          f"{len(order_items)} order_items to {OUT_DIR} and {WAREHOUSE_PATH}")


if __name__ == "__main__":
    main()
