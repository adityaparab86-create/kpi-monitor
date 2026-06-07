"""
Anomaly History & Trend Tracking — Mockup
Run: streamlit run docs/history_mockup.py

Shows two surfaces:
  1. Anomaly Alerts page — "Firing X days" badge + trend label on each row
  2. Investigate Anomaly — new History tab (streak chart + deviation trend)
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta

st.set_page_config(page_title="History Mockup", layout="wide", initial_sidebar_state="collapsed")

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.section-label {
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.8px;
    text-transform: uppercase; color: rgba(255,255,255,0.35);
    margin-bottom: 10px;
}
.alert-row {
    border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;
    border-left: 4px solid #ccc;
    display: flex; align-items: center; justify-content: space-between;
    background: rgba(255,255,255,0.03);
}
.alert-critical { border-color: #d62728; }
.alert-warning  { border-color: #ff7f0e; }
.alert-watch    { border-color: #bcbd22; }

.sev-badge {
    display: inline-block; padding: 2px 10px; border-radius: 10px;
    font-size: 0.72rem; font-weight: 700; color: white; margin-right: 8px;
}
.sev-critical { background: #d62728; }
.sev-warning  { background: #ff7f0e; }
.sev-watch    { background: #bcbd22; color: #333; }

.duration-badge {
    display: inline-block; padding: 2px 9px; border-radius: 10px;
    font-size: 0.70rem; font-weight: 600; border: 1px solid;
}
.dur-chronic  { color: #d62728; border-color: rgba(214,39,40,0.4);  background: rgba(214,39,40,0.08); }
.dur-recent   { color: #ff7f0e; border-color: rgba(255,127,14,0.4); background: rgba(255,127,14,0.08); }
.dur-new      { color: #2ca02c; border-color: rgba(44,160,44,0.4);  background: rgba(44,160,44,0.08); }

.trend-chip {
    font-size: 0.72rem; font-weight: 600; padding: 2px 8px;
    border-radius: 8px; display: inline-block;
}
.trend-worse    { color: #d62728; background: rgba(214,39,40,0.10); }
.trend-stable   { color: #ff7f0e; background: rgba(255,127,14,0.10); }
.trend-recover  { color: #2ca02c; background: rgba(44,160,44,0.10); }
.trend-new      { color: #7b68ee; background: rgba(123,104,238,0.10); }

.stat-card {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 10px; padding: 14px 16px; text-align: center;
}
.stat-value { font-size: 1.5rem; font-weight: 700; margin: 4px 0; }
.stat-label { font-size: 0.68rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 0.6px; }
.stat-sub   { font-size: 0.72rem; opacity: 0.55; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

# ── Shared data ───────────────────────────────────────────────────────────────

TODAY = date(2026, 6, 5)

# Simulated anomaly list with history fields
ANOMALIES = [
    {
        "sev": "Critical", "kpi": "Brokerage Revenue", "level": "Branch",
        "where": "East › Kolkata",   "deviation": -34.2,
        "first_seen": TODAY - timedelta(days=18), "days": 18,
        "trend": "Worsening",  "peak_dev": -38.1,
    },
    {
        "sev": "Critical", "kpi": "Equity Volume", "level": "Region",
        "where": "East",             "deviation": -28.7,
        "first_seen": TODAY - timedelta(days=18), "days": 18,
        "trend": "Worsening",  "peak_dev": -31.4,
    },
    {
        "sev": "Warning",  "kpi": "Net Flows",    "level": "Branch",
        "where": "South › Chennai",  "deviation": -22.1,
        "first_seen": TODAY - timedelta(days=7),  "days": 7,
        "trend": "Stable",    "peak_dev": -24.0,
    },
    {
        "sev": "Warning",  "kpi": "Active Clients", "level": "RM",
        "where": "RM-017",           "deviation": -21.4,
        "first_seen": TODAY - timedelta(days=2),  "days": 2,
        "trend": "New",       "peak_dev": -21.4,
    },
    {
        "sev": "Watch",    "kpi": "SIP Inflows",  "level": "Firm",
        "where": "Firm-wide",        "deviation": -11.8,
        "first_seen": TODAY - timedelta(days=11), "days": 11,
        "trend": "Recovering", "peak_dev": -19.3,
    },
]

SEV_COLOR   = {"Critical": "#d62728", "Warning": "#ff7f0e", "Watch": "#bcbd22"}
TREND_LABEL = {
    "Worsening":  ("🔺 Worsening",  "trend-worse"),
    "Stable":     ("➡️ Stable",     "trend-stable"),
    "Recovering": ("🔽 Recovering", "trend-recover"),
    "New":        ("✨ New",         "trend-new"),
}
DUR_CLASS = lambda d: "dur-chronic" if d >= 14 else "dur-recent" if d >= 5 else "dur-new"
DUR_LABEL = lambda d: (
    f"🔴 {d} days" if d >= 14 else
    f"🟠 {d} days" if d >= 5 else
    f"🟢 {d} days" if d >= 2 else
    "🟢 New today"
)

# ── Build weekly history for Brokerage Revenue / East › Kolkata ───────────────

np.random.seed(42)
weeks = 14
week_dates  = [TODAY - timedelta(weeks=w) for w in range(weeks - 1, -1, -1)]
week_labels = [d.strftime("%b %d") for d in week_dates]

# Deviation trajectory: normal → starts dipping → worsens → still bad
base_devs = (
    [np.random.uniform(-4, 3)  for _ in range(4)] +   # normal
    [np.random.uniform(-8, -5) for _ in range(2)] +   # early dip
    [np.random.uniform(-18,-12)for _ in range(2)] +   # crossing threshold
    [np.random.uniform(-28,-22)for _ in range(3)] +   # warning
    [np.random.uniform(-36,-30)for _ in range(3)]     # critical now
)
deviations  = base_devs[:weeks]
THRESHOLD   = -20.0   # "anomalous" if below this
firing_mask = [d < THRESHOLD for d in deviations]

# ── Page selector ─────────────────────────────────────────────────────────────

st.markdown("#### 🔍 Mockup: Anomaly History & Trend Tracking")
st.caption("Switch between surfaces to preview how history appears on each page.")
view = st.radio(
    "Preview surface",
    ["1 · Anomaly Alerts — with history columns",
     "2 · Investigate Anomaly — History tab"],
    horizontal=True,
    label_visibility="collapsed",
)
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SURFACE 1 — Anomaly Alerts with history columns
# ══════════════════════════════════════════════════════════════════════════════

if view.startswith("1"):

    st.markdown("### 🚨 Anomaly Alerts")
    st.caption(f"5 active anomalies · as of {TODAY}")

    # ── Filter bar
    fc1, fc2, _ = st.columns([1, 1, 3])
    fc1.selectbox("Domain", ["All domains", "Broking", "Wealth", "Clients"],
                  key="f_domain", label_visibility="collapsed")
    fc2.selectbox("Severity", ["All severities", "Critical", "Warning", "Watch"],
                  key="f_sev", label_visibility="collapsed")

    st.write("")

    # ── Column headers
    h1, h2, h3, h4, h5, h6, h7 = st.columns([2, 1.4, 1.8, 1.2, 1.4, 1.3, 0.9])
    for col, label in zip(
        [h1, h2, h3, h4, h5, h6, h7],
        ["KPI · Location", "Severity", "Deviation", "Duration", "First Seen", "Trend", ""],
    ):
        col.markdown(f'<div class="section-label">{label}</div>', unsafe_allow_html=True)

    # ── Alert rows
    for a in ANOMALIES:
        c1, c2, c3, c4, c5, c6, c7 = st.columns([2, 1.4, 1.8, 1.2, 1.4, 1.3, 0.9])
        sev_cls   = f"sev-{a['sev'].lower()}"
        dur_cls   = DUR_CLASS(a["days"])
        trend_lbl, trend_cls = TREND_LABEL[a["trend"]]
        dev_color = SEV_COLOR[a["sev"]]

        c1.markdown(
            f"**{a['kpi']}**<br>"
            f"<span style='font-size:0.78rem;opacity:0.6;'>{a['level']} · {a['where']}</span>",
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<span class="sev-badge {sev_cls}">{a["sev"]}</span>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<span style="font-size:1.0rem;font-weight:700;color:{dev_color};">'
            f'{a["deviation"]:+.1f}%</span><br>'
            f'<span style="font-size:0.70rem;opacity:0.5;">peak {a["peak_dev"]:+.1f}%</span>',
            unsafe_allow_html=True,
        )
        c4.markdown(
            f'<span class="duration-badge {dur_cls}">{DUR_LABEL(a["days"])}</span>',
            unsafe_allow_html=True,
        )
        days_ago = "today" if a["days"] == 0 else f'{a["days"]}d ago'
        c5.markdown(
            f'<span style="font-size:0.82rem;">{a["first_seen"].strftime("%b %d")}</span><br>'
            f'<span style="font-size:0.68rem;opacity:0.45;">{days_ago}</span>',
            unsafe_allow_html=True,
        )
        c6.markdown(
            f'<span class="trend-chip {trend_cls}">{trend_lbl}</span>',
            unsafe_allow_html=True,
        )
        c7.button("Investigate →", key=f"inv_{a['kpi']}", use_container_width=True)

    # ── Callout explaining new columns
    st.write("")
    st.markdown("""
    <div style="background:rgba(99,179,237,0.08);border:1px solid rgba(99,179,237,0.25);
                border-radius:8px;padding:12px 16px;font-size:0.82rem;">
        <b>New columns vs. current design:</b><br>
        &nbsp;• <b>Duration</b> — how many days this alert has been continuously firing
        (red ≥ 14 days, orange ≥ 5 days, green = new)<br>
        &nbsp;• <b>First Seen</b> — date the detector first flagged this KPI / dimension combination<br>
        &nbsp;• <b>Trend</b> — whether the deviation is growing, holding, or shrinking week-on-week<br>
        &nbsp;• <b>Peak</b> — worst deviation recorded since the alert started (small text under current dev)
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SURFACE 2 — Investigate Anomaly › History tab
# ══════════════════════════════════════════════════════════════════════════════

else:
    st.markdown("### 🔍 Investigate Anomaly")
    st.markdown(
        '<div style="display:inline-block;background:rgba(214,39,40,0.12);'
        'border:1px solid rgba(214,39,40,0.3);border-radius:6px;'
        'padding:4px 14px;font-size:0.82rem;margin-bottom:14px;">'
        '🔴 <b>Brokerage Revenue</b> — East › Kolkata · Critical · −34.2%</div>',
        unsafe_allow_html=True,
    )

    tab_dd, tab_xkpi, tab_hyp, tab_hist = st.tabs([
        "📍 Drill-Down",
        "🔗 Cross-KPI Validation",
        "💡 Hypotheses",
        "📅 History",          # ← new tab
    ])

    # Other tabs — brief placeholders
    with tab_dd:
        st.caption("Drill-down content unchanged — showing for context.")
        st.dataframe(pd.DataFrame([
            {"Region": "East", "Deviation": "-34.2%", "Severity": "Critical"},
            {"Region": "South","Deviation": "-12.1%", "Severity": "Warning"},
            {"Region": "North","Deviation":  "-4.8%", "Severity": "Healthy"},
            {"Region": "West", "Deviation":  "+1.2%", "Severity": "Healthy"},
        ]), use_container_width=True, hide_index=True)

    with tab_xkpi:
        st.caption("Cross-KPI Validation content unchanged.")
        st.success("✓ Brokerage Revenue is healthy at firm level (+2.1%). Issue is contained to East › Kolkata.")

    with tab_hyp:
        st.caption("Hypotheses content unchanged.")
        st.info("💡 Genuine issue isolated to East › Kolkata — 90% confidence.")

    # ── History tab ───────────────────────────────────────────────────────────
    with tab_hist:

        # ── Stat cards row
        s1, s2, s3, s4 = st.columns(4)
        for col, val, lbl, sub, color in [
            (s1, "18 days",  "Duration",      f"Since {(TODAY - timedelta(days=18)).strftime('%b %d')}",    "#d62728"),
            (s2, "May 18",   "First Detected", "Crossed Critical on May 25",   "#ff7f0e"),
            (s3, "−38.1%",   "Peak Deviation", "Recorded May 29",              "#d62728"),
            (s4, "🔺 Worsening","Trend",        "Dev. grew 5.4 pp last 7 days", "#ff7f0e"),
        ]:
            col.markdown(
                f'<div class="stat-card">'
                f'<div class="stat-label">{lbl}</div>'
                f'<div class="stat-value" style="color:{color};">{val}</div>'
                f'<div class="stat-sub">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.write("")

        # ── Deviation trend line (14 weeks)
        st.markdown("#### Weekly deviation vs. baseline")
        st.caption(
            "Each point = average deviation of Brokerage Revenue at East › Kolkata "
            "for that week vs. the preceding 60-day baseline. "
            "Computed retrospectively by sliding the analysis window back."
        )

        threshold_line = [THRESHOLD] * weeks

        fig = go.Figure()

        # Shaded "anomalous" region
        fig.add_hrect(
            y0=THRESHOLD, y1=min(deviations) - 5,
            fillcolor="rgba(214,39,40,0.07)", line_width=0,
            annotation_text="Critical zone", annotation_position="top left",
            annotation_font_size=11, annotation_font_color="#d62728",
        )

        # Threshold line
        fig.add_trace(go.Scatter(
            x=week_labels, y=threshold_line,
            mode="lines",
            line=dict(color="rgba(214,39,40,0.5)", dash="dash", width=1.5),
            name="Anomaly threshold (−20%)",
            hoverinfo="skip",
        ))

        # Deviation line — colour by firing
        colors = ["#d62728" if f else "#2ca02c" for f in firing_mask]
        for i in range(len(week_labels) - 1):
            segment_color = "#d62728" if firing_mask[i] or firing_mask[i+1] else "#2ca02c"
            fig.add_trace(go.Scatter(
                x=week_labels[i:i+2], y=deviations[i:i+2],
                mode="lines",
                line=dict(color=segment_color, width=2.5),
                showlegend=False,
                hoverinfo="skip",
            ))

        # Dots
        fig.add_trace(go.Scatter(
            x=week_labels, y=deviations,
            mode="markers+text",
            marker=dict(color=colors, size=10, line=dict(color="white", width=1.5)),
            text=[f"{d:+.1f}%" for d in deviations],
            textposition="top center",
            textfont=dict(size=9),
            name="Weekly deviation",
            hovertemplate="Week of %{x}<br>Deviation: %{y:.1f}%<extra></extra>",
        ))

        # Annotation for first fire
        first_fire_idx = next(i for i, f in enumerate(firing_mask) if f)
        fig.add_annotation(
            x=week_labels[first_fire_idx], y=deviations[first_fire_idx],
            text="⚡ First fired",
            showarrow=True, arrowhead=2, arrowcolor="#ff7f0e",
            font=dict(size=11, color="#ff7f0e"),
            ay=-36, ax=20,
        )

        fig.update_layout(
            height=340,
            yaxis_title="Deviation vs. baseline (%)",
            yaxis_ticksuffix="%",
            xaxis_title="",
            hovermode="x unified",
            legend=dict(orientation="h", y=1.12),
            margin=dict(l=0, r=0, t=30, b=0),
            showlegend=False,
        )
        fig.update_xaxes(tickangle=-30)
        st.plotly_chart(fig, use_container_width=True)

        # ── Firing streak heatmap
        st.markdown("#### Firing streak — week by week")
        st.caption("Green = within normal range · Red = anomaly detected that week")

        streak_df = pd.DataFrame({
            "Week":   week_labels,
            "Status": ["Anomalous" if f else "Normal" for f in firing_mask],
            "Dev":    [f"{d:+.1f}%" for d in deviations],
            "y":      ["Brokerage Revenue\nEast › Kolkata"] * weeks,
        })

        fig2 = go.Figure(go.Heatmap(
            z=[[1 if f else 0 for f in firing_mask]],
            x=week_labels,
            y=["Brokerage Revenue · East › Kolkata"],
            colorscale=[[0, "#2ca02c"], [1, "#d62728"]],
            zmin=0, zmax=1,
            showscale=False,
            text=[[f"{d:+.1f}%" for d in deviations]],
            texttemplate="%{text}",
            textfont=dict(size=10, color="white"),
            hovertemplate="Week of %{x}<br>%{text}<extra></extra>",
        ))
        fig2.update_layout(
            height=110,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(tickangle=-30),
        )
        st.plotly_chart(fig2, use_container_width=True)

        # ── How it works callout
        st.markdown("""
        <div style="background:rgba(99,179,237,0.08);border:1px solid rgba(99,179,237,0.22);
                    border-radius:8px;padding:12px 16px;font-size:0.80rem;margin-top:8px;">
            <b>How this is computed:</b> The detector is re-run at weekly cutoff dates going back
            14 weeks, using the same Analysis / Baseline windows as today's run. No external
            database needed — history is derived retrospectively from the existing data.
            Cached after first load (~1–2 sec).
        </div>
        """, unsafe_allow_html=True)
