# CENACE Monitor — Ecuador electricity bot + dashboard

A bot that runs **in the cloud every 30 minutes** (GitHub Actions — your computer can be off), scrapes
[CENACE · Información Operativa](https://www.cenace.gob.ec/info-operativa/InformacionOperativa.htm),
stores **every capture permanently** in this GitHub repository, keeps an always-up-to-date **SQLite database**
(`cenace.db`), and publishes a **dashboard** on GitHub Pages. CENACE's page only shows the current day — this bot
keeps all of it.

**Dashboard:** https://pabesjimenez.github.io/cenace-monitor/ · **Database:** [cenace.db](https://github.com/pabesjimenez/cenace-monitor/releases/download/database/cenace.db) · **Runs:** [Actions](https://github.com/pabesjimenez/cenace-monitor/actions)

```
 every 30 min (GitHub cron)
        │
        ▼
 ┌──────────────────────┐ commit ┌─────────────────────┐ build ┌──────────────────────────────┐
 │ scraper/cenace.py    │──────▶ │ data/*.csv          │─────▶ │ cenace.db  (GitHub Releases) │
 │ downloads CENACE page│        │ data/history/  ◀── every value of every capture, forever │
 └──────────────────────┘        └─────────────────────┘       └──────────────────────────────┘
                                          │ deploy
                                          ▼
                                 index.html dashboard (GitHub Pages)
```

Everything is free for a public repository (unlimited Actions minutes and free Pages hosting).

---

## Setup (≈10 minutes, one time)

### 1. Create the repository
1. Go to <https://github.com/new>.
2. Name: `cenace-monitor` (any name works). Visibility: **Public**. Do **not** add a README.
3. Click **Create repository**.

### 2. Upload the files
**Option A — browser (easiest)**
1. On the new repo page click **“uploading an existing file”**.
2. In Finder open this `cenace-monitor` folder and press **⌘ + Shift + .** to show hidden files —
   you must also upload the hidden **`.github`** folder (it contains the bot schedule).
3. Select *everything* inside the folder (`.github`, `scraper`, `data`, `index.html`, `requirements.txt`,
   `README.md`, `.gitignore`) and drag it onto the GitHub page. Click **Commit changes**.
4. Check that the repo now shows `.github/workflows/scrape.yml`. If not, create it with
   **Add file → Create new file**, type the name `.github/workflows/scrape.yml` and paste the content.

**Option B — Terminal**
```bash
cd ~/Claude_cowork/Energia/cenace-monitor
git init -b main && git add . && git commit -m "CENACE monitor"
git remote add origin https://github.com/pabesjimenez/cenace-monitor.git
git push -u origin main
```

### 3. Turn on GitHub Pages
Repo → **Settings → Pages → Build and deployment → Source: “GitHub Actions”**.

### 4. Allow the bot to save data
Repo → **Settings → Actions → General → Workflow permissions →
“Read and write permissions”** → Save.

### 5. Run it the first time
Repo → **Actions** tab → (click *“I understand… enable workflows”* if asked) →
**Scrape CENACE and publish dashboard** → **Run workflow**.
After ~1 minute the run turns green ✅ and your dashboard is live at:

```
https://pabesjimenez.github.io/cenace-monitor/
```

> The automatic run triggered by your upload (before Pages was switched on) may show a red ❌ — that's expected; the manual run above fixes it.

From then on it runs automatically at **:05 and :35 of every hour**.

---

## What gets stored (`data/`) — clean “final” values

| File | Content | Updated |
|---|---|---|
| `curve_realtime.csv` | Half-hourly MW by source (hidráulica, térmica, renovable, importación, exportación, producción total, demanda nacional) for the current day — **builds a continuous 30-min time series** | upsert by date+time |
| `curve_daily.csv` | Same, but CENACE's validated day (“Información operativa diaria”) | upsert by date+time |
| `snapshots.csv` | One row per run: day-to-date production KPIs (MWh), demand KPIs (MW), last half-hour values | append |
| `demand_by_company.csv` | MW for each distribution company (CNEL Guayaquil, E.E. Quito, …) at each run | append |
| `plants_daily_best.csv` | **Daily production per plant (MWh)** — Coca Codo, Paute, Sopladora, San Francisco, Delsitanisagua, Agoyán, Mazar, Minas San Francisco, Otras Hidro, Térmica, Gas Natural, Renovable. Uses CENACE's validated value when published (≈2 days later), otherwise the end-of-day real-time value; column `source` says which | rebuilt every run |
| `plants_daily_wide.csv` | Same, one column per plant — ready for Excel | rebuilt every run |
| `plants_period.csv` | Month-to-date (MWh) and year-to-date (GWh) per plant | upsert by period+plant |
| `plants_realtime.csv` | Day-to-date MWh per plant (Coca Codo, Paute, Sopladora, Mazar…); last value of the day ≈ daily total | upsert by date+plant |
| `plants_daily.csv` | Validated daily MWh per plant | upsert by date+plant |
| `daily_best.csv` | **Daily production by source with no gaps** (MWh): CENACE's validated day when the daily tab publishes it, otherwise the bot's end-of-day real-time capture. Column `source`: `validado`, `tiempo_real` (end-of-day capture reached the 23:30 block) or `tiempo_real_parcial` (incomplete, e.g. today). `sum_parts` = hidráulica + térmica + no convencional + importación | rebuilt every run |
| `daily_compare.csv` | For days that have both: end-of-day real-time value vs validated value, difference in MWh and % | rebuilt every run |
| `daily_summary.csv` | Validated daily production by source (only the days CENACE's daily tab showed) | upsert by date |
| `period_summary.csv` | Month-to-date (MWh) and year-to-date (GWh) totals | upsert by period |
| `latest.json` | Everything parsed in the last run | overwritten |

Times are Ecuador local time (`America/Guayaquil`); `scraped_at_utc` is also kept.
You can open any CSV directly in Excel, or use its “raw” GitHub URL in Python/Power BI, e.g.
`https://raw.githubusercontent.com/pabesjimenez/cenace-monitor/main/data/curve_realtime.csv`.

## The database (`cenace.db`)

**Download:** `https://github.com/pabesjimenez/cenace-monitor/releases/download/database/cenace.db`
(also the blue button on the dashboard). It is rebuilt from the repository on every run, so it always contains
everything since the bot started.

**How nothing gets lost**
- `data/history/YYYY/YYYY-MM-DD.csv` — append-only log in git: every value CENACE showed at every capture
  (curves, KPIs, plants, companies, month/year totals, notes). A value is written when it is new or when CENACE
  revises it, so intra-day corrections are kept. These text files are the permanent record.
- `cenace.db` is generated from those files (it is not stored in git, which would bloat the repo).
  If an upload ever fails, the next run simply rebuilds it.
- The original CENACE HTML page of each day is archived as `cenace-YYYY-MM-DD.html.gz`
  in the release **raw-YYYY** (Releases section of the repo), in case something needs to be re-processed.

**Tables and views**

| Name | What it is |
|---|---|
| `curve_realtime`, `curve_daily`, `snapshots`, `demand_by_company`, `plants_*`, `daily_best`, `daily_compare`, `daily_summary`, `period_summary` | Same as the CSV files above |
| `observations` | Every value of every capture: `captured_at_utc, captured_at_local, dataset, date, key, variable, value` |
| `captures` | One row per bot run |
| `v_day_close` | End-of-day values: the last capture of each day (normally the ~23:31 page with the 23:30 block). `curve_last_time` tells you if it reached 23:30 |
| `v_plant_monthly` | Monthly MWh per plant from the daily series, with how many days were validated |
| `v_curve_best` | One clean half-hourly series: validated value when CENACE has published it, real-time otherwise (`fuente` column) |
| `v_curve_revisions` | First vs. last published value of each half-hour (how much SCADA data gets revised) |
| `v_company_demand` | MW of each distribution company every 30 min |
| `about` | Source, build time, first/last capture |

**Open it with:** [DB Browser for SQLite](https://sqlitebrowser.org) (free, Mac/Windows — double-click and browse),
Python (`pandas.read_sql`), R, DBeaver, or Power BI/Excel through the SQLite ODBC driver.

```sql
-- Approx. daily energy (MWh, from 30-min samples) and peak demand
SELECT date,
       ROUND(SUM(produccion_total_mw) * 0.5) AS energia_mwh,
       MAX(demanda_nacional_mw)              AS demanda_max_mw,
       ROUND(100.0 * SUM(hidraulica_mw) / SUM(produccion_total_mw), 1) AS pct_hidro
FROM v_curve_best GROUP BY date ORDER BY date;

-- Coca Codo Sinclair daily energy (validated when available)
SELECT date, mwh, source FROM plants_daily_best WHERE plant LIKE 'Coca Codo%' ORDER BY date;
```

```python
import pandas as pd, sqlite3, urllib.request
urllib.request.urlretrieve("https://github.com/pabesjimenez/cenace-monitor/releases/download/database/cenace.db", "cenace.db")
df = pd.read_sql("SELECT * FROM v_curve_best", sqlite3.connect("cenace.db"))
```

---

## Good to know
- **Timing:** GitHub starts scheduled runs on a best-effort basis; delays of 5–15 min are normal.
  Because `curve_realtime.csv` stores every half-hour block of the day, a late or skipped run loses nothing —
  the next run fills in the gaps.
- **End of day:** the page published at ~23:31 is the most complete version of the day. Besides the regular
  :05/:35 runs, the bot runs again at 23:45 and 23:55 (Ecuador) so that page is captured even if GitHub is late.
  The final tables always keep the latest value seen for each day / half-hour.
- **The daily tab is irregular:** CENACE's “Información operativa diaria” lags and does not appear every day.
  `daily_best` and `plants_daily_best` fill every day anyway with the end-of-day real-time capture, and switch to
  the validated figure if CENACE publishes it later. `daily_compare` shows how close the two usually are.
- **Per-plant data:** the real-time tab lists 8 hydro plants plus Térmica / Gas Natural / Renovable (whole MWh);
  the validated daily tab adds “Otras Hidro”. Real-time days are replaced by validated values automatically
  once CENACE publishes them.
- **Does CENACE correct earlier values?** Unknown — the bot measures it. Every change to an already-published
  half-hour is logged; the dashboard's database card shows how many corrections have been detected and
  `v_curve_revisions` shows each one. If it stays at 0, CENACE doesn't revise.
- **Failures:** if CENACE is down or changes its page, the run turns red and GitHub emails you. The page that
  failed is attached to the run (artifact `debug-page`) so the parser can be fixed.
- **60-day rule:** GitHub may pause schedules in repos with no activity for 60 days. If you get that email,
  open **Actions** and click **Enable workflow**.
- **Change the frequency:** edit the `cron:` line in `.github/workflows/scrape.yml`
  (e.g. `"5 * * * *"` = hourly).
- **Run locally (optional):** `pip install -r requirements.txt && python scraper/cenace.py && python scraper/build_db.py`
- **Size:** expect roughly 100–200 MB of database per year; GitHub release files can be up to 2 GB.
- Data are CENACE's preliminary SCADA values, subject to revision.
