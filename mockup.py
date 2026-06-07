"""
Mockup of the 3 KPI card target-achievement options.
Run: streamlit run mockup.py --server.port 8502
"""
import streamlit as st

st.set_page_config(page_title="KPI Card Mockup", layout="wide")

st.markdown("""
<style>
.kpi-card {
    border-radius: 8px; padding: 14px 16px;
    margin-bottom: 8px; border-left: 5px solid #ccc;
}
.card-warning  { border-color: #ff7f0e; background: rgba(255,127,14,0.10); }
.card-ok       { border-color: #2ca02c; background: rgba(44,160,44,0.10); }
.card-critical { border-color: #d62728; background: rgba(214,39,40,0.10); }
.kpi-label { font-size: 0.78rem; opacity: 0.65; margin-bottom: 4px; }
.kpi-value { font-size: 1.35rem; font-weight: 700; }
.kpi-prior { font-size: 0.78rem; opacity: 0.60; margin-top: 2px; }
.kpi-note  { font-size: 0.72rem; opacity: 0.55; margin-top: 3px; }
.badge { display:inline-block; padding:2px 10px; border-radius:12px;
         font-size:0.75rem; font-weight:700; color:white; }
.badge-Warning  { background:#ff7f0e; }
.badge-OK       { background:#2ca02c; }
.badge-Critical { background:#d62728; }
.badge-target-ok  { background:#2ca02c; }
.badge-target-low { background:#d62728; }
.badge-target-mid { background:#ff7f0e; }
/* Progress bar */
.prog-wrap { background:rgba(128,128,128,0.2); border-radius:4px;
             height:8px; margin-top:6px; overflow:hidden; }
.prog-fill  { height:8px; border-radius:4px; }
</style>
""", unsafe_allow_html=True)

st.title("KPI Card — Target Achievement Options")
st.caption("Using real data from the system. Brokerage Revenue daily avg ₹37Cr vs baseline ₹37Cr. "
           "Cards below show the same KPI rendered in each layout.")

# ─── sample data ─────────────────────────────────────────────────────────────
CARDS = [
    {
        "kpi":          "Brokerage Revenue",
        "recent":       "₹37Cr /day",
        "baseline":     "₹37Cr",
        "baseline_lbl": "Baseline 90d avg",
        "delta_pct":    -0.8,
        "target_lbl":   "Monthly target: ₹1,050Cr",
        "target_val":   1050,          # Cr
        "actual_total": 518,           # Cr (14d sum)
        "period_target":490,           # Cr (monthly_target × 14/30)
        "achieve_pct":  106,
        "severity":     "Warning",
        "anom_note":    "Anomaly at South › HNI: -49.2% vs baseline",
    },
    {
        "kpi":          "Total AUM",
        "recent":       "₹19,376Cr",
        "baseline":     "₹19,352Cr",
        "baseline_lbl": "Baseline 90d avg",
        "delta_pct":    +0.1,
        "target_lbl":   "Annual target: ₹22,000Cr",
        "target_val":   22000,
        "actual_total": 19376,
        "period_target":22000,
        "achieve_pct":  88,
        "severity":     "OK",
        "anom_note":    "",
    },
    {
        "kpi":          "SIP Inflows",
        "recent":       "₹4.6Cr /day",
        "baseline":     "₹4.4Cr",
        "baseline_lbl": "Baseline 90d avg",
        "delta_pct":    +4.5,
        "target_lbl":   "Monthly target: ₹165Cr",
        "target_val":   165,
        "actual_total": 64,
        "period_target":77,
        "achieve_pct":  83,
        "severity":     "OK",
        "anom_note":    "",
    },
]

arrow = lambda d: ("↑" if d > 0 else "↓")
acolor = lambda d, dir_good_up: "green" if (d > 0) == dir_good_up else "red"

# ════════════════════════════════════════════════════════════════════
# Option A — Progress bar
# ════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Option A — Progress bar")
st.caption("Fill bar under the value. Visually immediate; shows both baseline delta and target progress.")
cols_a = st.columns(len(CARDS))
for col, c in zip(cols_a, CARDS):
    with col:
        d = c["delta_pct"]
        ach = c["achieve_pct"]
        bar_pct = min(ach, 100)
        bar_col = "#2ca02c" if ach >= 90 else "#ff7f0e" if ach >= 70 else "#d62728"
        badge_cls = f"badge-{c['severity']}"
        anom_html = f'<div class="kpi-note">{c["anom_note"]}</div>' if c["anom_note"] else ""
        st.markdown(f"""
<div class="kpi-card card-{'ok' if c['severity']=='OK' else c['severity'].lower()}">
  <div class="kpi-label">{c['kpi']}</div>
  <div class="kpi-value">{c['recent']}</div>
  <div class="kpi-prior">{c['baseline_lbl']}: {c['baseline']}</div>
  <div style="font-size:0.82rem;color:{acolor(d,True)};margin-top:2px">
    {arrow(d)} {abs(d):.1f}% vs baseline
  </div>
  <div style="margin-top:8px;font-size:0.75rem;opacity:0.65">{c['target_lbl']}</div>
  <div class="prog-wrap">
    <div class="prog-fill" style="width:{bar_pct}%;background:{bar_col}"></div>
  </div>
  <div style="font-size:0.78rem;font-weight:600;color:{bar_col};margin-top:3px">
    {ach}% of target achieved
  </div>
  <div style="margin-top:6px"><span class="badge {badge_cls}">{c['severity']}</span></div>
  {anom_html}
</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# Option B — Two comparison rows
# ════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Option B — Two comparison rows")
st.caption("Baseline delta and target delta shown as parallel rows. Compact — no extra height needed.")
cols_b = st.columns(len(CARDS))
for col, c in zip(cols_b, CARDS):
    with col:
        d = c["delta_pct"]
        ach = c["achieve_pct"]
        tgt_delta = ach - 100
        tgt_col = "#2ca02c" if tgt_delta >= 0 else "#d62728" if tgt_delta < -20 else "#ff7f0e"
        badge_cls = f"badge-{c['severity']}"
        anom_html = f'<div class="kpi-note">{c["anom_note"]}</div>' if c["anom_note"] else ""
        st.markdown(f"""
<div class="kpi-card card-{'ok' if c['severity']=='OK' else c['severity'].lower()}">
  <div class="kpi-label">{c['kpi']}</div>
  <div class="kpi-value">{c['recent']}</div>
  <div style="display:flex;gap:12px;margin-top:6px">
    <div>
      <div style="font-size:0.68rem;opacity:0.55">vs Baseline (90d)</div>
      <div style="font-size:0.85rem;color:{acolor(d,True)};font-weight:600">
        {arrow(d)} {abs(d):.1f}%
      </div>
    </div>
    <div style="border-left:1px solid rgba(128,128,128,0.3);padding-left:12px">
      <div style="font-size:0.68rem;opacity:0.55">vs Target ({ach}%)</div>
      <div style="font-size:0.85rem;color:{tgt_col};font-weight:600">
        {arrow(tgt_delta)} {abs(tgt_delta):.0f}%
      </div>
    </div>
  </div>
  <div style="margin-top:6px"><span class="badge {badge_cls}">{c['severity']}</span></div>
  {anom_html}
</div>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# Option C — Achievement % badge
# ════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("Option C — Achievement % badge")
st.caption("Minimal extra space: a coloured pill shows achievement next to the status badge.")
cols_c = st.columns(len(CARDS))
for col, c in zip(cols_c, CARDS):
    with col:
        d = c["delta_pct"]
        ach = c["achieve_pct"]
        ach_cls = "badge-target-ok" if ach >= 90 else "badge-target-low" if ach < 70 else "badge-target-mid"
        badge_cls = f"badge-{c['severity']}"
        anom_html = f'<div class="kpi-note">{c["anom_note"]}</div>' if c["anom_note"] else ""
        st.markdown(f"""
<div class="kpi-card card-{'ok' if c['severity']=='OK' else c['severity'].lower()}">
  <div class="kpi-label">{c['kpi']}</div>
  <div class="kpi-value">{c['recent']}</div>
  <div class="kpi-prior">Baseline 90d avg: {c['baseline']}</div>
  <div style="font-size:0.82rem;color:{acolor(d,True)};margin-top:2px">
    {arrow(d)} {abs(d):.1f}% vs baseline
  </div>
  <div style="margin-top:6px">
    <span class="badge {badge_cls}">{c['severity']}</span>
    &nbsp;
    <span class="badge {ach_cls}">{ach}% of target</span>
  </div>
  {anom_html}
</div>
""", unsafe_allow_html=True)

st.divider()
st.info("Pick an option above, then let me know and I will build it into the main dashboard.")
