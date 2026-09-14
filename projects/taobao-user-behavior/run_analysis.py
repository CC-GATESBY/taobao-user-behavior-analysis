"""Route B: query an existing sample_events table and export aggregates only."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

import duckdb
import matplotlib

if __name__ == "__main__":
    matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import pandas as pd

from prepare_data import PROJECT_DIR, SCHEMA, check_version

EXTENSION_MARKER = "-- Extended analysis:"
EXTENDED_QUERIES = {
    "weekday_comparison": "SELECT * FROM final_weekday_comparison ORDER BY before_date",
    "after_only_history": "SELECT * FROM final_after_only_history ORDER BY history_group",
    "cart_to_buy_24h": "SELECT * FROM final_cart_to_buy_24h ORDER BY cohort",
}


def enforce_quality(quality_check):
    row = quality_check.iloc[0]
    failed = any(int(row[name]) for name in [
        "missing_user_id", "missing_item_id", "missing_category_id",
        "invalid_behavior", "invalid_timestamp",
    ])
    if failed or int(row["total_records"]) == 0:
        counts = ", ".join(f"{name}={int(value)}" for name, value in row.items())
        raise ValueError(f"Data quality failed: {counts}")


def extended_tables(con):
    return {name: con.execute(sql).df() for name, sql in EXTENDED_QUERIES.items()}


def category_totals(category_change):
    changes = category_change["buy_event_change"]
    positive = int(changes[changes > 0].sum())
    top10 = int(changes[changes > 0].nlargest(10).sum())
    return pd.DataFrame.from_dict(
        {
            "categories_with_purchases": len(changes),
            "growing_categories": int((changes > 0).sum()),
            "declining_categories": int((changes < 0).sum()),
            "unchanged_categories": int((changes == 0).sum()),
            "positive_change_total": positive,
            "negative_change_total": int(changes[changes < 0].sum()),
            "net_change": int(changes.sum()),
            "top10_positive_change": top10,
            "top10_share_of_positive_change": top10 / positive if positive else float("nan"),
        }, orient="index", columns=["value"],
    )


def buyer_decomposition(daily):
    indexed = daily.set_index("event_date")
    before = indexed.loc[pd.Timestamp("2017-12-01")]
    after = indexed.loc[pd.Timestamp("2017-12-02")]
    a0, a1 = before["active_users"], after["active_users"]
    b0, b1 = before["buyers"], after["buyers"]
    r0, r1 = b0 / a0, b1 / a1
    scale = (a1 - a0) * (r0 + r1) / 2
    rate = (r1 - r0) * (a0 + a1) / 2
    return pd.DataFrame([{
        "active_user_component": scale,
        "buyer_rate_component": rate,
        "buyer_change": b1 - b0,
        "residual": (b1 - b0) - scale - rate,
    }])


def plot_daily(daily, output):
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    metrics = [
        ("active_users", "Active users", "#2563EB"),
        ("buyers", "Buyers", "#059669"),
        ("buyer_rate", "Buyer rate", "#D97706"),
    ]
    for ax, (column, label, color) in zip(axes, metrics):
        ax.plot(daily["event_date"], daily[column], marker="o", color=color)
        ax.set_ylabel(label)
        ax.set_ylim(0, float(daily[column].max()) * 1.12)
        ax.axvline(pd.Timestamp("2017-12-02"), color="gray", linestyle="--")
        ax.grid(axis="y", alpha=0.25)
    axes[2].yaxis.set_major_formatter(PercentFormatter(xmax=1))
    axes[2].xaxis.set_major_locator(mdates.DayLocator())
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    axes[2].set_xlabel("Date (Asia/Shanghai, 2017)")
    fig.suptitle("Taobao user sample: daily metrics")
    fig.tight_layout()
    fig.savefig(output / "daily_metrics.png", dpi=150)
    plt.close(fig)


def plot_context(daily, cart, output):
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), layout="constrained")
    axes[0].plot(daily["event_date"], daily["sample_active_share"], marker="o", color="#2563EB")
    axes[0].set_ylim(0, 1.08)
    axes[0].yaxis.set_major_formatter(PercentFormatter(1))
    axes[0].xaxis.set_major_locator(mdates.DayLocator())
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    users = int(daily["window_sample_users"].iloc[0])
    axes[0].set_title(f"Daily active share of {users:,} window sample users")
    axes[0].set_xlabel("Date (Asia/Shanghai, 2017)")
    axes[0].set_ylabel("Sample active share")
    detail = cart.set_index("cohort").loc[["after_only", "both_days"]]
    for i, (cohort, row) in enumerate(detail.iterrows()):
        rate = row["cart_item_pair_buy_rate_24h"]
        value = 0 if pd.isna(rate) else rate
        axes[1].barh(i, value, color="#2563EB", height=0.5)
        label = "No eligible pairs" if pd.isna(rate) else f"{int(row.success_pairs):,}/{int(row.eligible_pairs):,} = {rate:.2%}"
        axes[1].text(value + 0.003, i, label, va="center")
    axes[1].set_yticks([0, 1], ["After only", "Both days"])
    axes[1].set_xlim(0, max(0.15, detail["cart_item_pair_buy_rate_24h"].fillna(0).max() * 1.7))
    axes[1].xaxis.set_major_formatter(PercentFormatter(1))
    axes[1].set_title("Strict later purchase within 24h of first cart on Dec 2")
    axes[1].set_xlabel("User-item pair rate (purchases are behavior records)")
    axes[0].grid(axis="y", alpha=0.2)
    axes[1].grid(axis="x", alpha=0.2)
    fig.savefig(output / "context_diagnostics.png", dpi=150)
    plt.close(fig)


def validate_tables(tables):
    enforce_quality(tables["quality_check"])
    daily = tables["daily_metrics"].set_index("event_date")
    before, after = daily.loc[pd.Timestamp("2017-12-01")], daily.loc[pd.Timestamp("2017-12-02")]
    assert daily["event_records"].sum() == tables["analysis_summary"]["event_records"].iloc[0]
    assert tables["cohort_summary"]["buyer_change"].sum() == after["buyers"] - before["buyers"]
    assert tables["category_change"]["buy_event_change"].sum() == after["buy_events"] - before["buy_events"]
    assert abs(tables["buyer_decomposition"]["residual"].iloc[0]) < 1e-8
    cohort = tables["cohort_summary"].set_index("cohort")
    history = tables["after_only_history"]
    assert history["users"].sum() == (cohort.loc["after_only", "users"] if "after_only" in cohort.index else 0)
    assert history["buyers"].sum() == (cohort.loc["after_only", "buyers_after"] if "after_only" in cohort.index else 0)
    cart = tables["cart_to_buy_24h"].set_index("cohort")
    assert (cart["eligible_pairs"] + cart["excluded_incomplete_pairs"] == cart["start_pairs"]).all()
    assert (cart["success_pairs"] <= cart["eligible_pairs"]).all()
    for field in ["start_pairs", "eligible_pairs", "excluded_incomplete_pairs", "success_pairs", "same_second_buy_pairs"]:
        assert cart.loc[["after_only", "both_days"], field].sum() == cart.loc["all", field]


def export_tables(tables, output):
    # Finish every calculation and render before replacing successful outputs.
    validate_tables(tables)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".taobao-output-", dir=output.parent) as tmp:
        staging = Path(tmp)
        for name, frame in tables.items():
            if name == "category_summary":
                frame.to_csv(staging / f"{name}.csv", index_label="metric")
            else:
                frame.to_csv(staging / f"{name}.csv", index=False)
        plot_daily(tables["daily_metrics"], staging)
        plot_context(tables["daily_metrics"], tables["cart_to_buy_24h"], staging)
        output.mkdir(parents=True, exist_ok=True)
        for file in staging.iterdir():
            os.replace(file, output / file.name)


def run_analysis(db_path, output):
    check_version()
    db_path, output = Path(db_path), Path(output)
    if not db_path.is_file():
        raise FileNotFoundError("Database missing. Run prepare_data.py first (Route A).")
    # Read-only persistent database; all derived SQL tables are temporary.
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute("SET memory_limit = '1GB'")
        actual = {row[0]: row[1] for row in con.execute("DESCRIBE sample_events").fetchall()}
        if actual != SCHEMA:
            raise ValueError("sample_events must contain the five original VARCHAR columns.")
        con.execute((PROJECT_DIR / "analysis.sql").read_text(encoding="utf-8"))
        queries = {
            "sample_summary": "SELECT * FROM final_sample_summary",
            "quality_check": "SELECT * FROM final_quality_check",
            "duplicate_check": "SELECT * FROM final_duplicate_check",
            "range_check": "SELECT * FROM final_range_check",
            "analysis_summary": "SELECT * FROM final_analysis_summary",
            "daily_metrics": "SELECT * FROM final_daily_metrics ORDER BY event_date",
            "cohort_summary": "SELECT * FROM final_cohort_summary ORDER BY buyer_change DESC, cohort",
            "category_change": "SELECT * FROM final_category_change ORDER BY buy_event_change DESC, category_id",
        }
        tables = {name: con.execute(sql).df() for name, sql in queries.items()}
        tables.update(extended_tables(con))
    daily = tables["daily_metrics"]
    daily["event_date"] = pd.to_datetime(daily["event_date"])
    tables["category_summary"] = category_totals(tables["category_change"])
    tables["buyer_decomposition"] = buyer_decomposition(daily)
    export_tables(tables, output)
    print(tables["quality_check"].to_string(index=False))
    print(daily.to_string(index=False))
    print(tables["buyer_decomposition"].to_string(index=False))
    print(f"Exported {len(tables)} aggregate CSVs and two charts.")
    return tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=PROJECT_DIR / "data/taobao.duckdb")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "outputs")
    args = parser.parse_args()
    try:
        run_analysis(args.db, args.output)
    except (duckdb.Error, ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
