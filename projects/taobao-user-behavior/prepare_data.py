"""Route A: read the raw CSV once and persist the user hash sample."""

import argparse
from pathlib import Path

import duckdb

PROJECT_DIR = Path(__file__).resolve().parent
SCHEMA = dict.fromkeys(
    ["user_id", "item_id", "category_id", "behavior_type", "timestamp"],
    "VARCHAR",
)


def check_version():
    # DuckDB's hash is not guaranteed to remain stable between versions.
    if duckdb.__version__ != "1.5.5":
        raise RuntimeError("Reproduction requires duckdb==1.5.5.")


def prepare_sample(csv_path, db_path):
    check_version()
    csv_path, db_path = Path(csv_path), Path(db_path)
    if not csv_path.is_file():
        raise FileNotFoundError("Raw CSV missing; see data/README.md or pass --csv.")
    if db_path.exists():
        raise FileExistsError(
            "Database already exists. Use run_analysis.py for Route B, "
            "or choose a new --db path for Route A."
        )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute("SET memory_limit = '1GB'")
        con.read_csv(str(csv_path.resolve()), header=False, columns=SCHEMA).create_view(
            "raw_events", replace=True
        )
        con.execute("""
            CREATE TABLE sample_events AS
            SELECT * FROM raw_events WHERE hash(user_id) % 100 = 0
        """)
        summary = con.execute("""
            SELECT COUNT(*) AS event_records,
                   COUNT(DISTINCT user_id) AS users
            FROM sample_events
        """).df()
        # Do not persist a CSV view containing a machine-specific source path.
        con.execute("DROP VIEW raw_events")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=PROJECT_DIR / "data/UserBehavior.csv")
    parser.add_argument("--db", type=Path, default=PROJECT_DIR / "data/taobao.duckdb")
    args = parser.parse_args()
    print(prepare_sample(args.csv, args.db).to_string(index=False))


if __name__ == "__main__":
    main()
