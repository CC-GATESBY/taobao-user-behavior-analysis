"""Small synthetic regressions; never open the author's source database."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("MPLBACKEND", "Agg")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import duckdb
import pandas as pd

from prepare_data import SCHEMA, prepare_sample
from run_analysis import category_totals, enforce_quality, run_analysis

SQL = (PROJECT / "analysis.sql").read_text()


def event(user, item, behavior, time, category="c"):
    seconds = int(pd.Timestamp(time, tz="Asia/Shanghai").timestamp())
    return (user, item, category, behavior, str(seconds))


def seed():
    return [event("base", "i", "pv", "2017-12-01 09:00"),
            event("base", "i", "buy", "2017-12-02 09:00")]


def database(path, rows):
    with duckdb.connect(str(path)) as con:
        fields = ", ".join(f"{name} {kind}" for name, kind in SCHEMA.items())
        con.execute(f"CREATE TABLE sample_events ({fields})")
        con.executemany("INSERT INTO sample_events VALUES (?, ?, ?, ?, ?)", rows)


def fingerprint(folder):
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob("*") if p.is_file()}


def notebook_core(con, include_metrics=True):
    notebook = json.loads((PROJECT / "analysis.ipynb").read_text())
    cells = {c["id"]: "".join(c["source"]) for c in notebook["cells"]}
    selected = ["taobao-012", "taobao-018"]
    if include_metrics:
        selected += ["taobao-022", "taobao-024", "taobao-026", "taobao-028",
                     "taobao-037", "taobao-039", "taobao-044"]
    scope = {"con": con, "pd": pd, "enforce_quality": enforce_quality}
    with contextlib.redirect_stdout(io.StringIO()):
        for key in selected:
            exec(compile(cells[key], key, "exec"), scope)
    return scope


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "sample.duckdb"
        self.output = self.root / "outputs"

    def tearDown(self):
        self.tmp.cleanup()

    def run_quietly(self, db=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_analysis(db or self.db, self.output)

    def test_notebook_category_share_handles_zero_and_positive_denominators(self):
        notebook = json.loads((PROJECT / "analysis.ipynb").read_text())
        cell = next(c for c in notebook["cells"] if c["id"] == "taobao-048")
        code = compile("".join(cell["source"]), "taobao-048", "exec")
        cases = {
            "no_growth": [-3, -1, 0],
            "positive_growth": list(range(1, 12)) + [-3, 0],
        }
        for name, changes in cases.items():
            with self.subTest(case=name):
                frame = pd.DataFrame({"buy_event_change": changes})
                scope = {"pd": pd, "category_change": frame}
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(code, scope)
                result = scope["category_summary"]
                pd.testing.assert_frame_equal(result, category_totals(frame))
                share = result.loc["top10_share_of_positive_change", "value"]
                if name == "no_growth":
                    self.assertTrue(pd.isna(share))
                    self.assertEqual(result.loc["positive_change_total", "value"], 0)
                else:
                    self.assertAlmostEqual(share, 65 / 66)

    def test_normalized_purchase_duplicates_and_notebook_agree(self):
        buy = event("001", "x", " buy ", "2017-12-02 10:00")
        database(self.db, seed() + [buy, buy])
        before = self.db.read_bytes()
        tables = self.run_quietly()
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(tables["quality_check"].iloc[0].normalized_behavior_records, 2)
        self.assertEqual(tables["duplicate_check"].iloc[0].extra_identical_records, 1)
        after = tables["daily_metrics"].iloc[-1]
        self.assertEqual((after.buyers, after.buy_events), (2, 3))
        with duckdb.connect(str(self.db), read_only=True) as con:
            scope = notebook_core(con)
            for name in ["daily_metrics", "cohort_summary", "category_change", "quality_check", "duplicate_check"]:
                pd.testing.assert_frame_equal(scope[name], tables[name], check_dtype=False)
            self.assertEqual(con.execute("SELECT behavior_type, behavior_type_clean FROM final_events WHERE user_id='001'").fetchall(), [(" buy ", "buy"), (" buy ", "buy")])

    def test_invalid_behavior_stops_sql_notebook_and_cli_without_overwrite(self):
        database(self.db, seed())
        self.run_quietly()
        old = fingerprint(self.output)
        for i, behavior in enumerate(["unknown", "BUY", "", None]):
            with self.subTest(behavior=behavior):
                bad = self.root / f"invalid-{i}.duckdb"
                database(bad, seed() + [event("bad-only", "x", behavior, "2017-12-02 10:00")])
                with duckdb.connect(str(bad), read_only=True) as con:
                    with self.assertRaisesRegex(duckdb.InvalidInputException, "invalid_behavior=1"):
                        con.execute(SQL)
                    self.assertNotIn(("final_events",), con.execute("SHOW TABLES").fetchall())
                con = duckdb.connect(str(bad), read_only=True)
                with self.assertRaisesRegex(ValueError, "invalid_behavior=1"):
                    notebook_core(con, include_metrics=False)
                con.close()
                with self.assertRaisesRegex(duckdb.InvalidInputException, "invalid_behavior=1"):
                    self.run_quietly(bad)
                self.assertEqual(fingerprint(self.output), old)
        result = subprocess.run([sys.executable, str(PROJECT / "run_analysis.py"),
                                 "--db", str(bad), "--output", str(self.output)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid_behavior=1", result.stderr)
        self.assertEqual(fingerprint(self.output), old)

    def test_missing_ids_and_unparseable_timestamp_fail_even_outside_window(self):
        cases = [(0, None, "missing_user_id"), (1, " ", "missing_item_id"),
                 (2, "", "missing_category_id"), (4, "not-a-time", "invalid_timestamp"),
                 (4, None, "invalid_timestamp"), (4, "9223372036854775807", "invalid_timestamp")]
        for i, (field, value, count_name) in enumerate(cases):
            with self.subTest(field=field, value=value):
                row = list(event("bad", "x", "pv", "2017-11-24 10:00"))
                row[field] = value
                path = self.root / f"missing-{i}.duckdb"
                database(path, seed() + [tuple(row)])
                with self.assertRaisesRegex(duckdb.InvalidInputException, f"{count_name}=1"):
                    self.run_quietly(path)
                con = duckdb.connect(str(path), read_only=True)
                with self.assertRaisesRegex(ValueError, f"{count_name}=1"):
                    notebook_core(con, include_metrics=False)
                con.close()
        self.assertFalse(self.output.exists())

    def test_render_failure_preserves_successful_outputs(self):
        database(self.db, seed())
        self.run_quietly()
        old = fingerprint(self.output)
        with patch("run_analysis.plot_context", side_effect=ValueError("render failed")):
            with self.assertRaisesRegex(ValueError, "render failed"):
                self.run_quietly()
        self.assertEqual(fingerprint(self.output), old)

    def test_after_only_history_uses_only_earlier_six_days(self):
        rows = seed() + [event("seen", "x", "pv", "2017-11-25 01:00"),
                         event("seen", "x", "buy", "2017-12-02 01:00"),
                         event("unseen", "x", "pv", "2017-11-24 01:00"),
                         event("unseen", "x", "cart", "2017-12-02 01:00"),
                         event("unseen", "x", "buy", "2017-12-03 01:00")]
        database(self.db, rows)
        tables = self.run_quietly()
        history = tables["after_only_history"].set_index("history_group")
        self.assertEqual(tuple(history.loc["seen_earlier_in_window", ["users", "buyers"]]), (1, 1))
        self.assertEqual(tuple(history.loc["not_seen_earlier_in_window", ["users", "buyers"]]), (1, 0))

    def test_cart_sequence_deduplicates_and_respects_time_and_pair_boundaries(self):
        rows = [event("a", "i", "pv", "2017-12-01 00:00")]
        def add(u, kind, time, item="i"):
            rows.append(event(u, item, kind, time))
        for kind, time in [("cart", "2017-12-02 10:00"), ("cart", "2017-12-02 10:00"),
                           ("cart", "2017-12-02 11:00"), ("buy", "2017-12-02 09:00"),
                           ("buy", "2017-12-02 10:00"), ("buy", "2017-12-02 11:00"),
                           ("buy", "2017-12-02 11:00")]:
            add("a", kind, time)
        add("b", "cart", "2017-12-02 10:00"); add("b", "buy", "2017-12-02 10:00")
        add("c", "cart", "2017-12-02 12:00"); add("c", "buy", "2017-12-03 12:00")
        add("d", "cart", "2017-12-02 12:00"); add("d", "buy", "2017-12-03 12:00:01")
        add("e", "cart", "2017-12-02 23:59:59"); add("e", "buy", "2017-12-03 23:59:59")
        add("f", "cart", "2017-12-02 00:00"); add("f", "buy", "2017-12-03 00:00")
        add("g", "cart", "2017-12-02 10:00"); add("other-user", "buy", "2017-12-02 11:00")
        add("g", "buy", "2017-12-02 11:00", item="different-item")
        add("outside-start", "cart", "2017-12-03 00:00")
        add("e", "buy", "2017-12-04 00:00")
        database(self.db, rows)
        with duckdb.connect(str(self.db), read_only=True) as con:
            con.execute(SQL)
            all_pairs = con.execute("SELECT eligible_pairs, success_pairs, same_second_buy_pairs, same_second_only_pairs FROM final_cart_to_buy_24h WHERE cohort='all'").fetchone()
            self.assertEqual(all_pairs, (7, 4, 2, 1))
            # Earlier synthetic observation end exercises incomplete and exact-end exclusions.
            con.execute("UPDATE final_observation_window SET end_time=TIMESTAMP '2017-12-03 12:00'")
            con.execute(SQL[SQL.index("-- The observation end"):])
            counts = con.execute("SELECT start_pairs, eligible_pairs, excluded_incomplete_pairs, success_pairs FROM final_cart_to_buy_24h WHERE cohort='all'").fetchone()
            self.assertEqual(counts, (7, 4, 3, 2))

    def test_csv_sampling_preserves_varchar_ids_and_source_rows(self):
        with duckdb.connect() as con:
            ids = [r[0] for r in con.execute("SELECT lpad(CAST(i AS VARCHAR), 6, '0') FROM range(1000) t(i) WHERE hash(lpad(CAST(i AS VARCHAR), 6, '0')) % 100 = 0 LIMIT 2").fetchall()]
        rows = [event(ids[0], "x", " buy ", "2017-12-02 10:00")]*2
        rows += [event(ids[1], "x", "pv", "2017-12-01 10:00")]
        csv = self.root / "UserBehavior.csv"
        csv.write_text("\n".join(",".join(r) for r in rows) + "\n")
        original = csv.read_bytes()
        prepare_sample(csv, self.db)
        self.assertEqual(csv.read_bytes(), original)
        with duckdb.connect(str(self.db), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sample_events").fetchone()[0], 3)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sample_events WHERE user_id=? AND behavior_type=' buy '", [ids[0]]).fetchone()[0], 2)
            self.assertEqual({r[0]:r[1] for r in con.execute("DESCRIBE sample_events").fetchall()}, SCHEMA)
        with self.assertRaises(FileExistsError):
            prepare_sample(csv, self.db)


if __name__ == "__main__":
    unittest.main()
