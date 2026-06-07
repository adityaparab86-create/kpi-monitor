"""
Quick Tour — Sidebar Panel Mockup
Run: streamlit run docs/tour_mockup.py
This is a standalone mockup to preview the tour UX before integrating it into the main app.
"""

import streamlit as st

st.set_page_config(page_title="Tour Mockup", layout="wide", initial_sidebar_state="expanded")

# ── Tour step definitions ─────────────────────────────────────────────────────

TOUR_STEPS = [
    {
        "icon": "👋",
        "title": "Welcome to KPI Monitor",
        "body": (
            "This dashboard watches <b>12 KPIs</b> across Broking, Wealth, and Clients "
            "and automatically surfaces anomalies — no manual threshold-setting needed.<br><br>"
            "The system compares a short <b>Analysis window</b> (what's happening now) against "
            "a long <b>Baseline window</b> (what normal looks like) and flags statistically "
            "significant deviations."
        ),
        "look_at": "The sidebar — your controls live here throughout the session.",
        "look_icon": "⬅️",
        "page_hint": "Start on any page",
        "page": None,
    },
    {
        "icon": "⚙️",
        "title": "Detection Windows",
        "body": (
            "Each domain has its own <b>Analysis</b> and <b>Baseline</b> window because "
            "KPIs move at different speeds — Broking reacts in days, AUM in weeks, "
            "client acquisition in months.<br><br>"
            "The defaults are pre-tuned for this org. Use the sliders for "
            "<b>what-if exploration</b>, not day-to-day monitoring."
        ),
        "look_at": "The three expanders below — Broking, Wealth / AUM, Clients.",
        "look_icon": "⬇️",
        "page_hint": "Sidebar → Detection windows",
        "page": None,
    },
    {
        "icon": "📊",
        "title": "KPI Scorecard",
        "body": (
            "<b>Start here every morning.</b> Each card shows a KPI's current value, "
            "deviation from baseline, and severity badge.<br><br>"
            "The <b>Market Regime banner</b> at the top tells you whether Nifty is "
            "bullish/bearish and calm/volatile — context that affects how you interpret "
            "any anomaly."
        ),
        "look_at": "The coloured cards and the regime banner above them.",
        "look_icon": "👆",
        "page_hint": "Page → KPI Scorecard",
        "page": "KPI Scorecard",
    },
    {
        "icon": "🚨",
        "title": "Anomaly Alerts",
        "body": (
            "A prioritised list of every firing anomaly — sorted by severity score. "
            "<b>Critical</b> = ≥35% bad deviation, <b>Warning</b> = ≥20%, <b>Watch</b> = ≥10%.<br><br>"
            "Each row shows the KPI, the dimension where it fired (Firm / Region / Branch / RM), "
            "and a quick deviation figure. Filter by domain or severity to focus."
        ),
        "look_at": "The alert rows — red = Critical, orange = Warning, yellow = Watch.",
        "look_icon": "👆",
        "page_hint": "Page → Anomaly Alerts",
        "page": "Anomaly Alerts",
    },
    {
        "icon": "🔍",
        "title": "Investigate Anomaly",
        "body": (
            "Pick any alert and dig in — three tabs take you through the full "
            "diagnostic loop:<br>"
            "• <b>Drill-Down</b> — where in the hierarchy is the damage concentrated?<br>"
            "• <b>Cross-KPI Validation</b> — are correlated KPIs also moving? Is it firm-wide?<br>"
            "• <b>Hypotheses</b> — ranked explanations with confidence scores."
        ),
        "look_at": "The three tabs: Drill-Down · Cross-KPI Validation · Hypotheses.",
        "look_icon": "👆",
        "page_hint": "Page → Investigate Anomaly",
        "page": "Investigate Anomaly",
    },
    {
        "icon": "🗺️",
        "title": "Team Scorecard",
        "body": (
            "See the <b>entire organisation's health in one grid</b>. "
            "Rows = entities (Regions or Branches), columns = KPIs, "
            "colour = deviation severity. Red = bad, green = good.<br><br>"
            "Switch to <b>RM Leaderboard</b> to rank all 48 RMs by their worst "
            "KPI, or use the <b>Entity Deep-Dive</b> for a full breakdown of one entity."
        ),
        "look_at": "The Heat Map / Leaderboard toggle and the entity selector below.",
        "look_icon": "👆",
        "page_hint": "Page → Team Scorecard",
        "page": "Team Scorecard",
    },
    {
        "icon": "✅",
        "title": "You're ready!",
        "body": (
            "Here's the daily workflow in three steps:<br>"
            "1. <b>Scorecard</b> — morning health check, spot the red cards<br>"
            "2. <b>Anomaly Alerts → Investigate</b> — pick the worst alert, run the diagnostic loop<br>"
            "3. <b>Team Scorecard</b> — check if the issue is isolated or spread across the org<br><br>"
            "You can restart this tour any time from the sidebar."
        ),
        "look_at": "The navigation radio above — those are your four pages.",
        "look_icon": "⬅️",
        "page_hint": "You're all set",
        "page": None,
    },
]

N_STEPS = len(TOUR_STEPS)

# ── Session state ─────────────────────────────────────────────────────────────

if "tour_active" not in st.session_state:
    st.session_state.tour_active = False
if "tour_step" not in st.session_state:
    st.session_state.tour_step = 0

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.tour-card {
    background: linear-gradient(145deg, #1a2035, #1e2a45);
    border: 1px solid rgba(99,179,237,0.25);
    border-radius: 12px;
    padding: 16px 14px 12px 14px;
    margin-bottom: 4px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.35);
}
.tour-step-label {
    font-size: 0.62rem;
    color: rgba(255,255,255,0.38);
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 6px;
}
.tour-title {
    font-size: 1.0rem;
    font-weight: 700;
    color: #fff;
    margin-bottom: 10px;
    line-height: 1.3;
}
.tour-body {
    font-size: 0.80rem;
    color: rgba(255,255,255,0.72);
    line-height: 1.55;
    margin-bottom: 12px;
}
.tour-look {
    background: rgba(99,179,237,0.12);
    border-left: 3px solid #63b3ed;
    border-radius: 0 6px 6px 0;
    padding: 7px 10px;
    font-size: 0.75rem;
    color: #90cdf4;
    margin-bottom: 14px;
    line-height: 1.4;
}
.tour-dots {
    display: flex;
    justify-content: center;
    gap: 6px;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid rgba(255,255,255,0.08);
}
.dot { width: 7px; height: 7px; border-radius: 50%; }
.dot-active   { background: #63b3ed; }
.dot-inactive { background: rgba(255,255,255,0.18); }
/* start button */
.tour-start-btn button {
    background: linear-gradient(135deg, #2b4c7e, #1a3a5c) !important;
    color: #fff !important;
    border: 1px solid rgba(99,179,237,0.3) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
}
/* main highlight box */
.highlight-box {
    border: 2.5px dashed #63b3ed;
    border-radius: 10px;
    padding: 16px 20px;
    margin: 8px 0 16px 0;
    background: rgba(99,179,237,0.05);
    position: relative;
}
.highlight-label {
    position: absolute;
    top: -11px; left: 14px;
    background: #63b3ed;
    color: #0a1628;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 10px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("KPI Monitor")
    st.caption("Broking & Wealth Management")
    st.caption("Data through: **2026-06-05**")

    st.radio("Navigate", ["KPI Scorecard", "Anomaly Alerts", "Investigate Anomaly", "Team Scorecard", "About"], key="mock_page")

    st.divider()
    st.subheader("Detection windows")
    st.caption("Analysis / Baseline per domain")

    with st.expander("📈 Broking", expanded=False):
        st.slider("Analysis (days)", 3, 14, 5, key="brk_aw")
        st.slider("Baseline (days)", 30, 90, 60, key="brk_bw")
    with st.expander("💰 Wealth / AUM", expanded=False):
        st.slider("Analysis (days)", 7, 30, 14, key="wlt_aw")
        st.slider("Baseline (days)", 60, 180, 90, key="wlt_bw")
    with st.expander("👥 Clients", expanded=False):
        st.slider("Analysis (days)", 14, 60, 30, key="cli_aw")
        st.slider("Baseline (days)", 90, 365, 180, key="cli_bw")

    st.divider()

    # ── Tour panel ────────────────────────────────────────────────────────────

    if not st.session_state.tour_active:
        st.markdown('<div class="tour-start-btn">', unsafe_allow_html=True)
        if st.button("🗺️  Quick Tour", use_container_width=True, help="Step-by-step orientation to the dashboard"):
            st.session_state.tour_active = True
            st.session_state.tour_step = 0
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        i    = st.session_state.tour_step
        step = TOUR_STEPS[i]

        dots_html = "".join(
            f'<div class="dot {"dot-active" if j == i else "dot-inactive"}"></div>'
            for j in range(N_STEPS)
        )

        st.markdown(f"""
        <div class="tour-card">
            <div class="tour-step-label">Step {i + 1} of {N_STEPS}</div>
            <div class="tour-title">{step["icon"]} &nbsp;{step["title"]}</div>
            <div class="tour-body">{step["body"]}</div>
            <div class="tour-look">
                {step["look_icon"]} <b>Where to look:</b><br>{step["look_at"]}
            </div>
            <div class="tour-dots">{dots_html}</div>
        </div>
        """, unsafe_allow_html=True)

        st.write("")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            if st.button("← Prev", disabled=(i == 0), use_container_width=True):
                st.session_state.tour_step -= 1
                st.rerun()
        with c2:
            if i < N_STEPS - 1:
                if st.button("Next →", use_container_width=True, type="primary"):
                    st.session_state.tour_step += 1
                    st.rerun()
            else:
                if st.button("Finish", use_container_width=True, type="primary"):
                    st.session_state.tour_active = False
                    st.session_state.tour_step = 0
                    st.rerun()
        with c3:
            if st.button("✕ Exit", use_container_width=True):
                st.session_state.tour_active = False
                st.session_state.tour_step = 0
                st.rerun()


# ── Main area — simulated page content ───────────────────────────────────────

if not st.session_state.tour_active:
    st.title("Quick Tour — Mockup Preview")
    st.info("Click **🗺️ Quick Tour** in the sidebar to see the panel in action.", icon="💡")
    st.markdown("""
    This is a standalone mockup for the tour UX. It simulates the sidebar panel
    across all 7 steps without touching the main app.

    **What to review:**
    - Card layout, typography, and information density in the sidebar
    - Progress dots and step counter
    - "Where to look" callout box
    - Prev / Next / Exit / Finish button behaviour
    - How the main area context changes per step

    Once approved, the same panel will be embedded into `app.py` with the
    same session-state mechanism.
    """)
else:
    i    = st.session_state.tour_step
    step = TOUR_STEPS[i]

    # Page hint badge
    if step["page_hint"]:
        st.markdown(
            f'<div style="display:inline-block;background:rgba(99,179,237,0.15);'
            f'border:1px solid rgba(99,179,237,0.35);border-radius:20px;'
            f'padding:3px 14px;font-size:0.75rem;color:#63b3ed;margin-bottom:16px;">'
            f'📍 {step["page_hint"]}</div>',
            unsafe_allow_html=True,
        )

    st.title(f"{step['icon']}  {step['title']}")

    # ── Per-step simulated content ────────────────────────────────────────────

    if i == 0:  # Welcome
        c1, c2, c3 = st.columns(3)
        c1.metric("KPIs Monitored", "12", "across 3 domains")
        c2.metric("Hierarchy Levels", "4", "Firm → Region → Branch → RM")
        c3.metric("Detection Method", "Z-score", "per domain window")
        st.markdown("""
        <div class="highlight-box">
            <div class="highlight-label">Tour panel</div>
            The sidebar panel guides you through each feature step by step.
            Use <b>Next →</b> to advance, <b>← Prev</b> to go back, or <b>✕ Exit</b> to dismiss.
        </div>
        """, unsafe_allow_html=True)

    elif i == 1:  # Detection Windows
        st.markdown("""
        <div class="highlight-box">
            <div class="highlight-label">Sidebar → Detection windows</div>
            Open the three expanders in the sidebar (Broking, Wealth, Clients) to see
            the Analysis and Baseline sliders. Each domain has independently tuned defaults.
        </div>
        """, unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### What the windows mean")
            st.markdown("""
| Window | What it measures | Typical length |
|---|---|---|
| **Analysis** | "What's happening now" | 5 – 30 days |
| **Baseline** | "What normal looks like" | 60 – 180 days |
            """)
        with col2:
            st.markdown("#### Domain defaults")
            st.markdown("""
| Domain | Analysis | Baseline |
|---|---|---|
| Broking | 5 days | 60 days |
| Wealth / AUM | 14 days | 90 days |
| Clients | 30 days | 180 days |
            """)

    elif i == 2:  # Scorecard
        st.markdown("""
        <div class="highlight-box">
            <div class="highlight-label">Market Regime Banner</div>
            Bull · Calm — Nifty +3.2% (30d) &nbsp;|&nbsp; Z-score multiplier: 1.0×
        </div>
        """, unsafe_allow_html=True)
        cols = st.columns(4)
        cards = [
            ("Brokerage Revenue", "₹ 2,41,500", "-18.4%", "Critical", "#d62728"),
            ("Equity Volume",     "1,84,200",   "-12.1%", "Warning",  "#ff7f0e"),
            ("AUM",              "₹ 8,92,000", "+2.3%",  "Healthy",  "#2ca02c"),
            ("Active Clients",   "12,840",     "-8.1%",  "Watch",    "#bcbd22"),
        ]
        for col, (name, val, delta, sev, color) in zip(cols, cards):
            col.markdown(f"""
            <div style="border-left:5px solid {color};background:rgba(0,0,0,0.04);
                        border-radius:8px;padding:12px 14px;">
                <div style="font-size:0.75rem;opacity:0.6;">{name}</div>
                <div style="font-size:1.3rem;font-weight:700;">{val}</div>
                <div style="font-size:0.78rem;color:{color};font-weight:600;">{delta} vs baseline</div>
                <div style="margin-top:6px;">
                    <span style="background:{color};color:{'#333' if sev=='Watch' else '#fff'};
                                 padding:2px 9px;border-radius:10px;font-size:0.72rem;font-weight:700;">
                        {sev}
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    elif i == 3:  # Anomaly Alerts
        st.markdown("""
        <div class="highlight-box">
            <div class="highlight-label">Anomaly Alerts list</div>
            Sorted by severity score. Click any row's Investigate button to deep-dive.
        </div>
        """, unsafe_allow_html=True)
        import pandas as pd
        alerts = pd.DataFrame([
            {"Severity": "🔴 Critical", "KPI": "Brokerage Revenue", "Level": "Branch",  "Where": "East › Kolkata",  "Deviation": "-34.2%"},
            {"Severity": "🔴 Critical", "KPI": "Equity Volume",      "Level": "Region",  "Where": "East",            "Deviation": "-28.7%"},
            {"Severity": "🟠 Warning",  "KPI": "Net Flows",          "Level": "Branch",  "Where": "South › Chennai", "Deviation": "-22.1%"},
            {"Severity": "🟠 Warning",  "KPI": "Active Clients",     "Level": "RM",      "Where": "RM-017",          "Deviation": "-21.4%"},
            {"Severity": "🟡 Watch",    "KPI": "SIP Inflows",        "Level": "Firm",    "Where": "Firm-wide",       "Deviation": "-11.8%"},
        ])
        st.dataframe(alerts, use_container_width=True, hide_index=True)

    elif i == 4:  # Investigate
        st.markdown("""
        <div class="highlight-box">
            <div class="highlight-label">Investigate Anomaly — three tabs</div>
            Each tab narrows the diagnosis: geography first, then cross-KPI context, then hypotheses.
        </div>
        """, unsafe_allow_html=True)
        tab1, tab2, tab3 = st.tabs(["📍 Drill-Down", "🔗 Cross-KPI Validation", "💡 Hypotheses"])
        with tab1:
            st.markdown("**L1 breakdown — by Region**")
            import pandas as pd
            st.dataframe(pd.DataFrame([
                {"Region": "East",  "Deviation": "-34.2%", "Severity": "Critical"},
                {"Region": "South", "Deviation": "-12.1%", "Severity": "Warning"},
                {"Region": "North", "Deviation":  "-4.8%", "Severity": "Healthy"},
                {"Region": "West",  "Deviation":  "+1.2%", "Severity": "Healthy"},
            ]), use_container_width=True, hide_index=True)
        with tab2:
            st.markdown("**Firm-level primary KPI check**")
            st.success("✓ Brokerage Revenue is healthy at firm level (+2.1%). The drop is contained to East — not a firm-wide problem.")
            st.markdown("**Correlated KPI status**")
            st.dataframe(pd.DataFrame([
                {"KPI": "Equity Volume",      "Status": "Anomalous", "Deviation": "-28.7%"},
                {"KPI": "Active Clients",     "Status": "Normal",    "Deviation":  "-3.1%"},
                {"KPI": "Derivatives Volume", "Status": "Normal",    "Deviation":  "+1.8%"},
                {"KPI": "Nifty Return",       "Status": "Normal",    "Deviation":  "+3.2%"},
            ]), use_container_width=True, hide_index=True)
        with tab3:
            st.markdown("**Ranked hypotheses**")
            for conf, title, verdict, body in [
                (90, "Genuine issue isolated to East › Kolkata", "Genuine Issue",
                 "Correlated KPIs are healthy firm-wide. Brokerage Revenue is flat at firm level (+2.1%), confirming the drop is contained to this branch."),
                (55, "Market-driven downturn", "Market-Driven",
                 "Nifty is showing no stress (+3.2% 30d). Market context does not explain this anomaly."),
            ]:
                color = "#2ca02c" if verdict == "Genuine Issue" else "#ff7f0e"
                st.markdown(f"""
                <div style="border-left:4px solid {color};padding:10px 14px;
                            border-radius:0 8px 8px 0;margin-bottom:10px;
                            background:rgba(0,0,0,0.03);">
                    <b>{title}</b> &nbsp;
                    <span style="background:{color};color:#fff;padding:1px 8px;
                                 border-radius:8px;font-size:0.72rem;">{verdict}</span>
                    &nbsp;<span style="font-size:0.78rem;opacity:0.6;">Confidence: {conf}%</span><br>
                    <span style="font-size:0.80rem;opacity:0.75;">{body}</span>
                </div>
                """, unsafe_allow_html=True)

    elif i == 5:  # Team Scorecard
        st.markdown("""
        <div class="highlight-box">
            <div class="highlight-label">Team Scorecard — Heat Map</div>
            Each cell = one entity × one KPI. Colour = deviation severity. Scan the red cells first.
        </div>
        """, unsafe_allow_html=True)
        import plotly.graph_objects as go, numpy as np
        kpis     = ["Brok. Rev.", "Eq. Vol.", "Deriv. Vol.", "AUM", "Net Flows", "Active Cl."]
        entities = ["North", "South", "East", "West"]
        z = np.array([
            [ -8,  -5,  +3,  +2,  -4,  -2],
            [-12,  -9,  -6,  -1,  -8,  -5],
            [-34, -28, -15,  -3, -18, -11],
            [  +4,  +2,  +7,  +5,  +3,  +6],
        ])
        fig = go.Figure(go.Heatmap(
            z=z, x=kpis, y=entities,
            colorscale=[[0,"#d62728"],[0.4,"#ff7f0e"],[0.5,"#f5f5f5"],[1,"#2ca02c"]],
            zmid=0, zmin=-40, zmax=40,
            text=[[f"{v:+.0f}%" for v in row] for row in z],
            texttemplate="%{text}", textfont={"size": 13, "color": "white"},
            showscale=True,
        ))
        fig.update_layout(height=280, margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig, use_container_width=True)

    elif i == 6:  # Done
        st.balloons()
        st.success("You've completed the Quick Tour! The dashboard is ready to use.")
        st.markdown("""
        ### Daily workflow recap
        | Step | Page | What to do |
        |---|---|---|
        | 1 | **KPI Scorecard** | Morning check — spot the red/orange cards |
        | 2 | **Anomaly Alerts** | Pick the highest-severity alert |
        | 3 | **Investigate Anomaly** | Drill-Down → Cross-KPI → Hypotheses |
        | 4 | **Team Scorecard** | Check if it's isolated or spread across the org |
        """)
        st.markdown("You can restart the tour any time via the **🗺️ Quick Tour** button in the sidebar.")
