"""Route B: query an existing sample_events table and export aggregates only."""

import argparse
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import pandas as pd

from prepare_data import PROJECT_DIR, SCHEMA, check_version


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
            "cohort_summary": "SELECT * FROM final_cohort_summary ORDER BY buyer_change DESC",
            "category_change": "SELECT * FROM final_category_change ORDER BY buy_event_change DESC, category_id",
        }
        tables = {name: con.execute(sql).df() for name, sql in queries.items()}
    daily = tables["daily_metrics"]
    daily["event_date"] = pd.to_datetime(daily["event_date"])
    tables["category_summary"] = category_totals(tables["category_change"])
    tables["buyer_decomposition"] = buyer_decomposition(daily)
    # Reconciliations derive expectations from this run, never from reported totals.
    assert daily["event_records"].sum() == tables["analysis_summary"]["event_records"].iloc[0]
    indexed = daily.set_index("event_date")
    baseline, comparison = indexed.loc[pd.Timestamp("2017-12-01")], indexed.loc[pd.Timestamp("2017-12-02")]
    assert tables["cohort_summary"]["buyer_change"].sum() == comparison["buyers"] - baseline["buyers"]
    assert tables["category_change"]["buy_event_change"].sum() == comparison["buy_events"] - baseline["buy_events"]
    assert abs(tables["buyer_decomposition"]["residual"].iloc[0]) < 1e-8
    output.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        if name == "category_summary":
            frame.to_csv(output / f"{name}.csv", index_label="metric")
        else:
            frame.to_csv(output / f"{name}.csv", index=False)
    plot_daily(daily, output)
    print(daily.to_string(index=False))
    print(tables["buyer_decomposition"].to_string(index=False))
    print(f"Exported {len(tables)} aggregate CSVs and one trend chart.")
    return tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=PROJECT_DIR / "data/taobao.duckdb")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "outputs")
    args = parser.parse_args()
    run_analysis(args.db, args.output)


if __name__ == "__main__":
    main()
