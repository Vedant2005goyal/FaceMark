"""Database benchmark: a fresh MySQL connection per query (how the original classes and
per-request code behave) vs the pooled DatabaseManager, plus the latency of the queries
attendance marking runs. Needs a MySQL loaded with schema.sql, configured through .env / env vars.

Usage:  python benchmarks/eval_system.py [--n 300]
Output: benchmarks/results/system.json
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import mysql.connector
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import Config  # noqa: E402
from database import DatabaseManager  # noqa: E402

RESULTS = ROOT / 'benchmarks' / 'results'
QUERY = "SELECT Setting_Value FROM Attendance_Settings WHERE Setting_Key = %s"
PARAMS = ('late_threshold_minutes',)


def stats(samples):
    return {'median_ms': round(1000 * statistics.median(samples), 3),
            'p95_ms': round(1000 * float(np.percentile(samples, 95)), 3)}


def timed(fn, n):
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return samples


def fresh_connection_query():
    conn = mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT, user=Config.DB_USER,
                                   password=Config.DB_PASSWORD, database=Config.DB_NAME)
    cur = conn.cursor(dictionary=True)
    cur.execute(QUERY, PARAMS)
    cur.fetchone()
    cur.close()
    conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--n', type=int, default=300)
    args = ap.parse_args()

    db = DatabaseManager()
    db.execute_query(QUERY, PARAMS, fetch_one=True)  # warm the pool

    fresh = stats(timed(fresh_connection_query, args.n))
    pooled = stats(timed(lambda: db.execute_query(QUERY, PARAMS, fetch_one=True), args.n))
    duplicate_check = stats(timed(lambda: db.execute_query(
        "SELECT 1 FROM Attendance WHERE User_ID = %s AND Session_ID = %s", (21, 1), fetch_one=True), args.n))

    results = {
        'queries': args.n,
        'fresh_connection_per_query': fresh,
        'pooled_connection': pooled,
        'speedup_median': round(fresh['median_ms'] / pooled['median_ms'], 1),
        'attendance_duplicate_check': duplicate_check,
        'note': 'local MySQL on the same machine; a remote DB adds network round trips to both',
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / 'system.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
