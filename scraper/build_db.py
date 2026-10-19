"""
Build the SQLite database cenace.db from the files the bot keeps in git.

  data/*.csv                  -> one table per file (clean "final" values)
  data/history/YYYY/*.csv     -> table `observations` (every value of every capture)
                                 + table `captures` (one row per bot run)
  + handy SQL views (see VIEWS below)

The database is rebuilt from scratch on every run, so it is always consistent with
the git history (nothing can be lost if an upload fails — the next run rebuilds it).

Usage:  python scraper/build_db.py [output.db]      (default: _work/cenace.db)
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import os
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_work" / "cenace.db"

FINAL_TABLES = ["curve_realtime", "curve_daily", "snapshots", "demand_by_company",
                "plants_realtime", "plants_daily", "plants_daily_best", "plants_daily_wide",
                "plants_period", "daily_summary", "daily_best", "daily_compare", "period_summary"]
TEXT_COLS = {"date", "time", "plant", "group", "company", "unit", "period", "period_type", "as_of_text",
             "scraped_at_utc", "scraped_at_local", "page_last_modified", "realtime_date", "demand_date",
             "curve_last_time", "updated_at_local", "source", "variable", "realtime_close_at",
             "realtime_last_block"}

VIEWS = {
    # Clean half-hourly series: validated value when available, otherwise the last real-time value
    "v_curve_best": """
        SELECT r.date, r.time,
               COALESCE(d.hidraulica_mw, r.hidraulica_mw)               AS hidraulica_mw,
               COALESCE(d.termica_mw, r.termica_mw)                     AS termica_mw,
               COALESCE(d.renovable_mw, r.renovable_mw)                 AS renovable_mw,
               COALESCE(d.importacion_mw, r.importacion_mw)             AS importacion_mw,
               COALESCE(d.exportacion_mw, r.exportacion_mw)             AS exportacion_mw,
               COALESCE(d.produccion_total_mw, r.produccion_total_mw)   AS produccion_total_mw,
               COALESCE(d.demanda_nacional_mw, r.demanda_nacional_mw)   AS demanda_nacional_mw,
               CASE WHEN d.date IS NULL THEN 'tiempo_real' ELSE 'validado' END AS fuente
        FROM curve_realtime r
        LEFT JOIN curve_daily d ON d.date = r.date AND d.time = r.time
        UNION ALL
        SELECT d.date, d.time, d.hidraulica_mw, d.termica_mw, d.renovable_mw, d.importacion_mw,
               d.exportacion_mw, d.produccion_total_mw, d.demanda_nacional_mw, 'validado'
        FROM curve_daily d
        WHERE NOT EXISTS (SELECT 1 FROM curve_realtime r WHERE r.date = d.date AND r.time = d.time)""",

    # How much each half-hour value was revised: first value published vs last one
    "v_curve_revisions": """
        SELECT dataset, date, key AS time, variable,
               COUNT(*)                      AS n_versions,
               MIN(captured_at_local)        AS first_seen,
               MAX(captured_at_local)        AS last_seen,
               (SELECT o2.value FROM observations o2 WHERE o2.dataset=o.dataset AND o2.date=o.date
                  AND o2.key=o.key AND o2.variable=o.variable ORDER BY o2.captured_at_utc ASC  LIMIT 1) AS first_value,
               (SELECT o2.value FROM observations o2 WHERE o2.dataset=o.dataset AND o2.date=o.date
                  AND o2.key=o.key AND o2.variable=o.variable ORDER BY o2.captured_at_utc DESC LIMIT 1) AS last_value
        FROM observations o
        WHERE dataset IN ('curve_realtime', 'curve_daily')
        GROUP BY dataset, date, key, variable""",

    # Demand of each distribution company at every capture (30-min time series)
    "v_company_demand": """
        SELECT captured_at_utc, captured_at_local, date, key AS company, value AS mw
        FROM observations WHERE dataset = 'company_demand'""",

    # End-of-day values from the real-time page: the last capture of each day
    # (curve_last_time shows whether it reached the 23:30 block)
    "v_day_close": """
        SELECT s.* FROM snapshots s
        WHERE s.scraped_at_utc = (SELECT MAX(s2.scraped_at_utc) FROM snapshots s2
                                  WHERE s2.realtime_date = s.realtime_date)""",

    # Monthly energy per plant from the daily series (complete months use validated data)
    "v_plant_monthly": """
        SELECT substr(date, 1, 7) AS month, plant, "group", SUM(mwh) AS mwh, COUNT(*) AS days,
               SUM(source = 'validado') AS days_validated
        FROM plants_daily_best GROUP BY 1, 2, 3""",
}


def to_val(v: str):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return v


def load_csv_table(con: sqlite3.Connection, name: str, path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0
    cols = list(rows[0].keys())
    decl = ", ".join(f'"{c}" {"TEXT" if c in TEXT_COLS else "REAL"}' for c in cols)
    con.execute(f'CREATE TABLE "{name}" ({decl})')
    con.executemany(
        f'INSERT INTO "{name}" VALUES ({",".join("?" * len(cols))})',
        [[(r.get(c) or None) if c in TEXT_COLS else to_val(r.get(c)) for c in cols] for r in rows],
    )
    return len(rows)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA journal_mode = OFF")
    con.execute("PRAGMA synchronous = OFF")

    counts = {}
    for name in FINAL_TABLES:
        p = DATA / f"{name}.csv"
        if p.exists():
            counts[name] = load_csv_table(con, name, p)

    # Full capture history
    con.execute("""CREATE TABLE observations (
        captured_at_utc TEXT, captured_at_local TEXT, page_last_modified TEXT,
        dataset TEXT, date TEXT, key TEXT, variable TEXT, value REAL, value_text TEXT)""")
    n = 0
    for f in sorted((DATA / "history").glob("*/*.csv")):
        with f.open(newline="", encoding="utf-8") as fh:
            batch = []
            for r in csv.DictReader(fh):
                v = to_val(r["value"])
                num = v if isinstance(v, float) else None
                txt = None if isinstance(v, float) else v
                batch.append((r["captured_at_utc"], r["captured_at_local"], r["page_last_modified"] or None,
                              r["dataset"], r["date"], r["key"], r["variable"], num, txt))
            con.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)", batch)
            n += len(batch)
    counts["observations"] = n
    con.execute("CREATE INDEX ix_obs_series ON observations(dataset, date, key, variable, captured_at_utc)")
    con.execute("CREATE INDEX ix_obs_time ON observations(captured_at_utc)")
    con.execute("""CREATE TABLE captures AS
        SELECT captured_at_utc, MIN(captured_at_local) AS captured_at_local,
               MIN(page_last_modified) AS page_last_modified, COUNT(*) AS n_values
        FROM observations GROUP BY captured_at_utc ORDER BY captured_at_utc""")
    counts["captures"] = con.execute("SELECT COUNT(*) FROM captures").fetchone()[0]

    for t in ("curve_realtime", "curve_daily"):
        if t in counts:
            con.execute(f"CREATE INDEX ix_{t} ON {t}(date, time)")
    for name, sql in VIEWS.items():
        needed = [t for t in ("curve_realtime", "curve_daily", "plants_daily_best", "snapshots") if t in sql]
        if all(t in counts for t in needed):
            con.execute(f"CREATE VIEW {name} AS {sql}")

    built = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    first, last = con.execute("SELECT MIN(captured_at_local), MAX(captured_at_local) FROM captures").fetchone()
    con.execute("CREATE TABLE about (key TEXT PRIMARY KEY, value TEXT)")
    con.executemany("INSERT INTO about VALUES (?, ?)", [
        ("source", "https://www.cenace.gob.ec/info-operativa/InformacionOperativa.htm"),
        ("built_at_utc", built), ("first_capture_local", first), ("last_capture_local", last),
        ("timezone", "America/Guayaquil"),
        ("note", "Datos preliminares del SCADA de CENACE, sujetos a revisión."),
    ])
    # Does CENACE correct half-hours it already published? (count values that changed after first publication)
    revised = con.execute("""
        SELECT COUNT(*), COALESCE(MAX(ABS(last_v - first_v)), 0) FROM (
          SELECT o.dataset, o.date, o.key, o.variable,
                 (SELECT value FROM observations a WHERE a.dataset=o.dataset AND a.date=o.date AND a.key=o.key
                    AND a.variable=o.variable ORDER BY captured_at_utc ASC LIMIT 1)  AS first_v,
                 (SELECT value FROM observations a WHERE a.dataset=o.dataset AND a.date=o.date AND a.key=o.key
                    AND a.variable=o.variable ORDER BY captured_at_utc DESC LIMIT 1) AS last_v
          FROM observations o WHERE o.dataset = 'curve_realtime'
          GROUP BY o.dataset, o.date, o.key, o.variable HAVING COUNT(*) > 1)""").fetchone()
    total_rt = con.execute("""SELECT COUNT(*) FROM (SELECT 1 FROM observations WHERE dataset='curve_realtime'
                              GROUP BY date, key, variable)""").fetchone()[0]
    revisions = {"realtime_values": total_rt, "revised_values": revised[0], "max_abs_change_mw": round(revised[1], 1)}
    con.commit()
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.execute("VACUUM")
    con.close()
    tmp.replace(OUT)

    info = {"built_at_utc": built, "size_bytes": OUT.stat().st_size, "first_capture_local": first,
            "last_capture_local": last, "tables": counts, "views": list(VIEWS), "revisions": revisions}
    (DATA / "db_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"Built {OUT} ({info['size_bytes'] / 1e6:.2f} MB): {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
