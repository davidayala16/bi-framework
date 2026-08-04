"""Golden-query verification tests for metrics/registry.yaml.

Every metric formula is run against the synthetic warehouse and checked
against known bounds/values for the fixed random seed in
data/generate_synthetic_data.py. This is the gate referenced by each
metric's `verified_by` field: a change to a formula that breaks its test
is a change that must not merge (see .github/workflows/verify-metrics.yml).
"""

ALLOWED_FILTER_COLUMNS = {"channel", "region", "category"}


def run_metric(warehouse, registry, metric_id, filters=None):
    metric = registry[metric_id]
    if metric["filterable_dimensions"]:
        if filters:
            assert set(filters) <= ALLOWED_FILTER_COLUMNS, "unsupported filter column"
            where = " AND ".join(f"{col} = ?" for col in filters)
            params = list(filters.values())
        else:
            where, params = "1=1", []
        sql = metric["formula_sql_template"].format(
            base_fact_sql=registry["__base_fact_sql__"], where=where
        )
        return warehouse.execute(sql, params).df()
    return warehouse.execute(metric["formula_sql"]).df()


def test_registry_is_well_formed(registry):
    required = {
        "id", "name", "category", "description", "grain", "unit", "owner",
        "filterable_dimensions", "verified_by",
    }
    for metric_id, metric in registry.items():
        if metric_id == "__base_fact_sql__":
            continue
        missing = required - metric.keys()
        assert not missing, f"{metric_id} missing fields: {missing}"
        has_template = "formula_sql_template" in metric
        has_fixed = "formula_sql" in metric
        assert has_template != has_fixed, (
            f"{metric_id} must define exactly one of "
            "formula_sql_template (filterable) or formula_sql (fixed)"
        )
        assert has_template == bool(metric["filterable_dimensions"]), (
            f"{metric_id}: filterable_dimensions must be non-empty iff "
            "formula_sql_template is used"
        )


def test_net_revenue(warehouse, registry):
    df = run_metric(warehouse, registry, "net_revenue")
    value = df["net_revenue"].iloc[0]
    assert value == 936726.22


def test_net_revenue_filtered_is_subset_of_total(warehouse, registry):
    total = run_metric(warehouse, registry, "net_revenue")["net_revenue"].iloc[0]
    filtered = run_metric(
        warehouse, registry, "net_revenue", filters={"channel": "paid_social"}
    )["net_revenue"].iloc[0]
    assert 0 < filtered < total


def test_aov(warehouse, registry):
    df = run_metric(warehouse, registry, "aov")
    value = df["aov"].iloc[0]
    assert value == 390.3


def test_repeat_purchase_rate(warehouse, registry):
    df = run_metric(warehouse, registry, "repeat_purchase_rate")
    value = df["repeat_purchase_rate_pct"].iloc[0]
    assert 0 <= value <= 100
    assert value == 78.7


def test_cac_by_channel(warehouse, registry):
    df = run_metric(warehouse, registry, "cac_by_channel")
    assert set(df["channel"]) == {
        "direct", "email", "organic_search", "paid_social", "referral",
    }
    assert (df["cac"] > 0).all()
    # paid_social is deliberately the most expensive channel in the
    # synthetic spend model — regression check that the weighting held.
    assert df.set_index("channel").loc["paid_social", "cac"] == df["cac"].max()


def test_ltv_90d(warehouse, registry):
    df = run_metric(warehouse, registry, "ltv_90d")
    value = df["ltv_90d"].iloc[0]
    assert value == 1123.43


def test_churn_rate_90d(warehouse, registry):
    df = run_metric(warehouse, registry, "churn_rate_90d")
    value = df["churn_rate_90d_pct"].iloc[0]
    assert 0 <= value <= 100
    assert value == 27.3


def test_acquisition_funnel(warehouse, registry):
    df = run_metric(warehouse, registry, "acquisition_funnel")
    assert set(df["outcome"]) == {"Never Purchased", "One-Time Buyer", "Repeat Buyer"}
    assert set(df["channel"]) == {
        "direct", "email", "organic_search", "paid_social", "referral",
    }
    # every (channel, outcome) pair present, and it partitions all customers
    assert len(df) == 15
    assert df["customer_count"].sum() == 600


def test_unfilterable_metrics_reject_filters():
    """Cohort metrics (cac, ltv, churn, acquisition_funnel) declare
    filterable_dimensions: [] on purpose — their logic doesn't compose with
    a row-level WHERE. This just pins that the registry keeps declaring
    them that way."""
    import yaml
    from pathlib import Path

    reg = yaml.safe_load(
        open(Path(__file__).resolve().parents[1] / "metrics" / "registry.yaml")
    )
    fixed_ids = {"cac_by_channel", "ltv_90d", "churn_rate_90d", "acquisition_funnel"}
    for metric in reg["metrics"]:
        if metric["id"] in fixed_ids:
            assert metric["filterable_dimensions"] == []
            assert "formula_sql" in metric
