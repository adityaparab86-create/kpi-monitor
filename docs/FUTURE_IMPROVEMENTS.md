# Future Improvements

---

## 1. Pre-computed KPI Aggregates at All Hierarchy Levels

**Status:** Noted — not yet started  
**Priority:** Medium  

### Context

The current architecture stores data at the finest grain (**RM × Segment × Date**, 144 rows/day, ~75K rows over 2 years) and computes all aggregations at runtime via `loader.aggregate()`. Each call does a fresh `df.copy() → filter → groupby → agg` on the full dataset.

Existing caches:
- `DataLoader` object — `@st.cache_resource` (loaded once per server session)
- Anomaly detection output — `@st.cache_data(ttl=300)`
- Entity Health output — `@st.cache_data(ttl=300)`
- All other `aggregate()` calls — **no cache, computed live**

Performance is acceptable today (~5–20 ms per call) but will degrade at higher data volumes or concurrent users.

### Problem

1. **Alert inconsistency** — Analysis/Baseline window sliders are user-adjustable, so two analysts viewing the same anomaly with different slider positions see different z-scores, severities, and firing alerts. There is no single canonical "org state."

2. **No pre-computation possible** — Dynamic windows prevent materialising aggregated tables ahead of time.

### Proposed Solution

Fix the canonical windows per domain at the org level (already implicitly set: Broking=5/60d, Wealth=14/90d, Clients=30/180d) and pre-compute aggregated KPI windows at all four hierarchy levels on each data refresh.

```
Pre-computed layer (run once on data refresh):
  data/kpi_aggregates.parquet
    columns: level | entity | kpi | analysis_mean | baseline_mean | deviation_pct | window_tag
    rows:    firm / region / branch / rm_id — one row per (entity, kpi, window)
```

The sliders remain available as an analyst "what-if" override for investigation, but canonical alerts and the org banner always reflect the fixed org-level windows.

### What to Build

- `generate_aggregates.py` — materialisation script, run after `generate_data.py` (or on each real data refresh)
- Updated `DataLoader` — reads from `kpi_aggregates.parquet` for standard queries; falls back to live aggregation only for custom window overrides
- Updated anomaly detector — primary detection path reads pre-aggregated rows; removes redundant `df.copy()` calls
- Alert history table — because canonical alerts are now reproducible, store when each anomaly first fired and track severity trend over time
- Proactive alerting hook — a scheduler can run detection on the pre-computed table and push notifications without a user session

### Benefits

- Sub-millisecond anomaly detection reads
- All users see the same canonical alerts (alerts become org state, not personal state)
- Enables alert history, first-seen timestamps, severity trend tracking
- Unlocks proactive / scheduled alerting

---

## 2. Anomaly History & Trend Tracking

**Status:** Noted — not yet started  
**Priority:** Medium  
**Mockup:** `docs/history_mockup.py` (run with `streamlit run docs/history_mockup.py`)

### Context

Every page load re-detects anomalies from scratch against the current end date. There is no record of when an anomaly first fired or whether it is getting better or worse. The 2-year synthetic dataset makes retrospective detection possible without any external storage.

### Approach

Two complementary methods, both using only existing data:

**Option A — Retrospective sliding window** *(answers "how long has this been firing?")*  
Re-run the anomaly detector at weekly cutoff dates going back 12–16 weeks. Since all historical data exists, the detector can be asked *"what would it have seen on May 25? May 18?"* and a genuine firing history can be assembled. Cost: ~1–2 seconds, cached after first load.

**Option B — Deviation trend** *(answers "is it getting worse or better?")*  
For each current anomaly, compute the KPI's weekly deviation from baseline over the past 14 weeks — no re-detection needed, just rolling groupby calls. Very cheap.

### What to Build

**Anomaly Alerts page — 3 new columns:**
- **Duration** — colour-coded badge: 🔴 ≥14 days (chronic) · 🟠 ≥5 days · 🟢 new
- **First Seen** — calendar date the detector first flagged this KPI / dimension
- **Trend** — 🔺 Worsening · ➡️ Stable · 🔽 Recovering · ✨ New

**Investigate Anomaly — new 📅 History tab:**
- 4 stat cards: Duration · First Detected · Peak Deviation · Trend direction
- Weekly deviation line chart (14 weeks, green = normal, red = anomalous, threshold line, ⚡ "First fired" annotation)
- Firing streak heatmap — single-row calendar strip, green/red per week, deviation value in each cell
- "How this is computed" callout explaining the retrospective method

### Benefits

- Distinguishes chronic problems (firing 3 weeks) from new ones (firing today)
- Lets analysts see if an intervention is working (Recovering trend)
- Adds operational urgency context without needing a database or persistence layer
- Natural complement to improvement #1 — once canonical windows are fixed, history can be stored permanently

---
