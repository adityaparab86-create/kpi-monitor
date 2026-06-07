"""
KPI Monitoring Dashboard — Broking & Wealth Management
Run: streamlit run app.py
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from kpi_monitor.data_loader import DataLoader, HIERARCHY
from kpi_monitor.anomaly_detector import AnomalyDetector, Anomaly, SEVERITY_COLORS
from kpi_monitor.drill_down import DrillDownAnalyzer
from kpi_monitor.correlation import CorrelationValidator

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="KPI Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
[data-testid="stMetricValue"]   { font-size: 1.6rem; font-weight: 700; }
[data-testid="stMetricDelta"]   { font-size: 0.9rem; }
.kpi-card {
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 8px;
    border-left: 5px solid #ccc;
    display: flex;
    flex-direction: column;
    min-height: 175px;
    box-sizing: border-box;
}
.kpi-card-footer { margin-top: auto; padding-top: 6px; }
/* rgba backgrounds work on both light and dark themes */
.card-critical { border-color: #d62728; background: rgba(214,39,40,0.10); }
.card-warning  { border-color: #ff7f0e; background: rgba(255,127,14,0.10); }
.card-watch    { border-color: #bcbd22; background: rgba(188,189,34,0.10); }
.card-ok       { border-color: #2ca02c; background: rgba(44,160,44,0.10); }
/* dimmed text inherits the theme colour and just reduces opacity */
.kpi-label { font-size: 0.78rem; opacity: 0.65; margin-bottom: 4px; }
.kpi-value { font-size: 1.4rem; font-weight: 700; }
.kpi-prior { font-size: 0.78rem; opacity: 0.60; margin-top: 2px; }
.kpi-note  { font-size: 0.72rem; opacity: 0.55; margin-top: 3px; }
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 700;
    color: white;
}
.badge-Critical { background: #d62728; }
.badge-Warning  { background: #ff7f0e; }
.badge-Watch    { background: #bcbd22; color: #333; }
.badge-OK       { background: #2ca02c; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

if "selected_anomaly_idx" not in st.session_state:
    st.session_state.selected_anomaly_idx = None
if "page" not in st.session_state:
    st.session_state.page = "KPI Scorecard"


# ── Data loading (cached) ─────────────────────────────────────────────────────

@st.cache_resource
def get_loader():
    return DataLoader()


@st.cache_data(ttl=3600)
def get_volatility_regime(_loader_id) -> tuple[str, float, float]:
    """
    Compute Nifty 30-day rolling volatility and map to a sensitivity regime.
    Returns (label, vol_pct_per_day, zscore_multiplier).
    Multiplier >1 raises thresholds so market-driven noise doesn't trigger alerts.
    """
    loader = get_loader()
    mkt = loader.market
    if mkt.empty:
        return ("Normal", 0.0, 1.0)
    recent = mkt.sort_values("date").tail(30)["nifty_return"]
    vol = float(recent.std() * 100)   # daily std as %
    if vol < 0.8:
        return ("Normal", vol, 1.0)
    elif vol < 1.5:
        return ("Elevated", vol, 1.2)
    else:
        return ("High", vol, 1.4)


@st.cache_data(ttl=300)
def get_anomalies(
    _loader_id,
    b_aw: int, b_bw: int,   # Broking analysis / baseline
    w_aw: int, w_bw: int,   # Wealth
    c_aw: int, c_bw: int,   # Clients
    zscore_multiplier: float,
) -> list:
    """Run anomaly detection per domain with domain-specific windows."""
    loader   = get_loader()
    detector = AnomalyDetector(loader)

    domain_cfg = {
        "Broking": (b_aw, b_bw),
        "Wealth":  (w_aw, w_bw),
        "Clients": (c_aw, c_bw),
    }

    all_anomalies = []
    for domain, (aw, bw) in domain_cfg.items():
        kpis = loader.domain_kpis(domain)
        all_anomalies.extend(
            detector.detect_all(
                analysis_window=aw,
                baseline_window=bw,
                kpi_list=kpis,
                zscore_multiplier=zscore_multiplier,
            )
        )

    # Deduplicate across domains (shouldn't overlap, but safety net)
    seen: dict = {}
    for a in all_anomalies:
        key = f"{a.kpi}|{a.dimension_level}|{a.dimension_label()}"
        if key not in seen or a.severity_score > seen[key].severity_score:
            seen[key] = a

    result = list(seen.values())
    result.sort(key=lambda a: (-a.severity_score, -abs(a.deviation_pct)))
    return result


# ── Sidebar navigation ────────────────────────────────────────────────────────

def sidebar():
    st.sidebar.title("KPI Monitor")
    st.sidebar.caption("Broking & Wealth Management")

    try:
        loader = get_loader()
        end_dt = loader.df["date"].max().date()
        st.sidebar.caption(f"Data through: **{end_dt}**")
    except Exception:
        pass

    pages = [
        "KPI Scorecard",
        "Anomaly Alerts",
        "Investigate Anomaly",
        "Trend Explorer",
        "About",
    ]
    chosen = st.sidebar.radio("Navigate", pages,
                               index=pages.index(st.session_state.page))
    if chosen != st.session_state.page:
        st.session_state.page = chosen

    st.sidebar.divider()
    st.sidebar.subheader("Detection windows")
    st.sidebar.caption("Analysis / Baseline per domain")

    with st.sidebar.expander("📈 Broking", expanded=True):
        b_aw = st.slider("Analysis (days)", 3, 14,  5, key="brk_aw",
                         help="Volumes & revenue move daily — short window catches breaks fast")
        b_bw = st.slider("Baseline (days)", 30, 90, 60, key="brk_bw")

    with st.sidebar.expander("💰 Wealth / AUM", expanded=True):
        w_aw = st.slider("Analysis (days)", 7, 30,  14, key="wlt_aw",
                         help="AUM & flows change more slowly — needs a wider window to be meaningful")
        w_bw = st.slider("Baseline (days)", 60, 180, 90, key="wlt_bw")

    with st.sidebar.expander("👥 Clients", expanded=True):
        c_aw = st.slider("Analysis (days)", 14, 60, 30, key="cli_aw",
                         help="Acquisition & activation are campaign-driven — month-level analysis")
        c_bw = st.slider("Baseline (days)", 90, 365, 180, key="cli_bw")

    domain_windows = {
        "Broking": {"analysis": b_aw, "baseline": b_bw},
        "Wealth":  {"analysis": w_aw, "baseline": w_bw},
        "Clients": {"analysis": c_aw, "baseline": c_bw},
    }
    return domain_windows


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 1 — KPI Scorecard
# ─────────────────────────────────────────────────────────────────────────────

_REGIME_STYLE = {
    "Normal":   ("rgba(44,160,44,0.12)",  "#2ca02c"),
    "Elevated": ("rgba(255,127,14,0.12)", "#ff7f0e"),
    "High":     ("rgba(214,39,40,0.12)",  "#d62728"),
}


def page_scorecard(
    anomalies: list[Anomaly],
    domain_windows: dict | None = None,
    regime: tuple = ("Normal", 0.0, 1.0),
):
    if domain_windows is None:
        domain_windows = {
            "Broking": {"analysis": 5,  "baseline": 60},
            "Wealth":  {"analysis": 14, "baseline": 90},
            "Clients": {"analysis": 30, "baseline": 180},
        }

    st.title("KPI Health Scorecard")
    loader = get_loader()

    # Build a lookup: kpi → worst anomaly across all levels
    kpi_worst: dict[str, Anomaly] = {}
    for a in anomalies:
        if a.kpi not in kpi_worst or a.severity_score > kpi_worst[a.kpi].severity_score:
            kpi_worst[a.kpi] = a

    # Summary row
    n_critical = sum(1 for a in kpi_worst.values() if a.severity == "Critical")
    n_warning  = sum(1 for a in kpi_worst.values() if a.severity == "Warning")
    n_watch    = sum(1 for a in kpi_worst.values() if a.severity == "Watch")
    n_ok       = len(loader.firm_kpis()) - len(kpi_worst)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Critical", n_critical,  delta=None)
    c2.metric("Warning",  n_warning,   delta=None)
    c3.metric("Watch",    n_watch,      delta=None)
    c4.metric("Healthy",  max(n_ok, 0), delta=None)

    # Window summary caption
    st.caption(
        "  ·  ".join(
            f"{d} **{domain_windows[d]['analysis']}d** / {domain_windows[d]['baseline']}d"
            for d in ("Broking", "Wealth", "Clients")
        ) + "  *(analysis / baseline)*"
    )

    # Volatility regime badge
    reg_label, vol_pct, zs_mult = regime
    reg_bg, reg_fg = _REGIME_STYLE.get(reg_label, ("rgba(128,128,128,0.12)", "#888"))
    thresh_note = (
        f"Alert thresholds raised +{(zs_mult - 1)*100:.0f}% — market noise filtered"
        if zs_mult > 1.0 else "Normal alert sensitivity"
    )
    st.markdown(
        f'<div style="display:inline-flex;align-items:center;gap:12px;'
        f'background:{reg_bg};border:1px solid {reg_fg};'
        f'border-radius:7px;padding:6px 14px;margin-bottom:4px;font-size:0.80rem">'
        f'<span style="color:{reg_fg};font-weight:700">● {reg_label} market regime</span>'
        f'<span style="opacity:0.55">Nifty 30d vol: {vol_pct:.2f}%/day</span>'
        f'<span style="opacity:0.55">·</span>'
        f'<span style="color:{reg_fg};opacity:0.85">{thresh_note}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    targets_cfg = loader.config.get("targets", {})

    # Per-domain grids — each domain uses its own analysis & baseline window
    for domain in ["Broking", "Wealth", "Clients"]:
        aw = domain_windows[domain]["analysis"]
        bw = domain_windows[domain]["baseline"]

        recent_range   = loader.last_n_days(aw)
        baseline_range = loader.prior_n_days(bw, aw)
        firm_recent    = loader.firm_daily(recent_range)
        firm_baseline  = loader.firm_daily(baseline_range)

        kpis = loader.domain_kpis(domain)
        st.subheader(f"{domain} KPIs")
        cols = st.columns(min(len(kpis), 4))

        for i, kpi in enumerate(kpis):
            col = cols[i % 4]
            with col:
                unit      = loader.kpi_unit(kpi)
                direction = loader.kpi_direction(kpi)
                recent_val   = firm_recent[kpi].mean()   if kpi in firm_recent.columns   else 0.0
                baseline_val = firm_baseline[kpi].mean() if kpi in firm_baseline.columns else 0.0
                delta_pct    = (recent_val - baseline_val) / abs(baseline_val) * 100 if baseline_val else 0.0

                # Target: baseline daily avg grown by monthly_growth_pct
                growth_pct   = targets_cfg.get(kpi, {}).get("monthly_growth_pct", 0)
                target_daily = baseline_val * (1 + growth_pct / 100)
                if direction == "lower_is_better":
                    achieve_pct = (target_daily / recent_val * 100) if recent_val > 0 else 100.0
                else:
                    achieve_pct = (recent_val / target_daily * 100) if target_daily > 0 else 100.0
                tgt_delta = achieve_pct - 100.0
                tgt_col   = "#2ca02c" if tgt_delta >= 0 else "#ff7f0e" if tgt_delta >= -20 else "#d62728"
                tgt_arrow = "↑" if tgt_delta >= 0 else "↓"

                worst = kpi_worst.get(kpi)
                if worst:
                    severity  = worst.severity
                    css_cls   = f"card-{severity.lower()}"
                    badge     = f'<span class="badge badge-{severity}">{severity}</span>'
                    anom_note = (
                        f"Anomaly at {worst.dimension_label()}: "
                        f"{worst.deviation_pct:+.1f}% vs baseline"
                    )
                else:
                    css_cls   = "card-ok"
                    badge     = '<span class="badge badge-OK">Healthy</span>'
                    anom_note = ""

                arrow     = "↑" if delta_pct > 0 else "↓"
                arrow_col = (
                    "green" if (delta_pct > 0 and direction == "higher_is_better")
                             or (delta_pct < 0 and direction == "lower_is_better")
                    else "red"
                )
                anom_html = (
                    f'<div class="kpi-note">{anom_note}</div>'
                    if anom_note else ""
                )

                st.markdown(f"""
<div class="kpi-card {css_cls}">
  <div class="kpi-label">{loader.kpi_display(kpi)}</div>
  <div class="kpi-value">{_fmt(recent_val, unit)}<span style="font-size:0.65rem;opacity:0.55"> /day avg</span></div>
  <div style="display:flex;gap:12px;margin-top:6px">
    <div>
      <div style="font-size:0.68rem;opacity:0.55">vs Baseline ({bw}d)</div>
      <div style="font-size:0.85rem;color:{arrow_col};font-weight:600">{arrow} {abs(delta_pct):.1f}%</div>
    </div>
    <div style="border-left:1px solid rgba(128,128,128,0.3);padding-left:12px">
      <div style="font-size:0.68rem;opacity:0.55">vs Target ({_fmt(target_daily, unit)})</div>
      <div style="font-size:0.85rem;color:{tgt_col};font-weight:600">{tgt_arrow} {abs(tgt_delta):.0f}%</div>
    </div>
  </div>
  <div class="kpi-card-footer">{badge}{anom_html}</div>
</div>
""", unsafe_allow_html=True)

        st.write("")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — Anomaly Alerts
# ─────────────────────────────────────────────────────────────────────────────

def page_anomalies(anomalies: list[Anomaly]):
    st.title("Anomaly Alerts")

    loader = get_loader()
    if not anomalies:
        st.success("No anomalies detected in the current analysis window.")
        return

    # Filters
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        sev_filter = st.multiselect(
            "Severity", ["Critical", "Warning", "Watch"],
            default=["Critical", "Warning", "Watch"],
        )
    with fc2:
        domain_filter = st.multiselect(
            "Domain", ["Broking", "Wealth", "Clients"],
            default=["Broking", "Wealth", "Clients"],
        )
    with fc3:
        level_filter = st.multiselect(
            "Dimension level",
            ["firm"] + HIERARCHY,
            default=["firm"] + HIERARCHY,
        )

    filtered = [
        a for a in anomalies
        if a.severity in sev_filter
        and a.domain in domain_filter
        and a.dimension_level in level_filter
    ]

    st.caption(f"Showing {len(filtered)} of {len(anomalies)} anomalies")
    st.divider()

    for idx, anom in enumerate(filtered[:50]):
        sev_color = SEVERITY_COLORS.get(anom.severity, "#ccc")
        dim_label = anom.dimension_label()
        dev_arrow = "▼" if anom.deviation_pct < 0 else "▲"
        dev_color = (
            "red"   if (anom.deviation_pct < 0 and anom.direction == "higher_is_better")
                    or (anom.deviation_pct > 0 and anom.direction == "lower_is_better")
            else "green"
        )

        with st.container():
            col1, col2, col3, col4, col5 = st.columns([1, 3, 2, 2, 2])
            col1.markdown(
                f'<span class="badge badge-{anom.severity}">{anom.severity}</span>',
                unsafe_allow_html=True,
            )
            col2.markdown(f"**{anom.kpi_name}**  \n`{dim_label}`")
            col3.markdown(
                f"<span style='color:{dev_color};font-size:1.1rem'>"
                f"{dev_arrow} {abs(anom.deviation_pct):.1f}%</span>",
                unsafe_allow_html=True,
            )
            col4.caption(
                f"Actual: **{_fmt(anom.actual_value, anom.unit)}**  \n"
                f"Exp: {_fmt(anom.expected_value, anom.unit)}"
            )
            if col5.button("Investigate", key=f"inv_{idx}_{anom.kpi}_{dim_label}"):
                st.session_state.selected_anomaly_idx = anomalies.index(anom)
                st.session_state.page = "Investigate Anomaly"
                st.rerun()

        st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — Investigate Anomaly
# ─────────────────────────────────────────────────────────────────────────────

def page_investigate(
    anomalies: list[Anomaly],
    domain_windows: dict | None = None,
    regime: tuple = ("Normal", 0.0, 1.0),
):
    st.title("Anomaly Investigation")
    loader = get_loader()

    if not anomalies:
        st.info("No anomalies to investigate. Adjust detection settings in the sidebar.")
        return

    # Anomaly selector
    options = [
        f"[{a.severity}] {a.kpi_name} — {a.dimension_label()} ({a.deviation_pct:+.1f}%)"
        for a in anomalies[:30]
    ]
    sel_idx = st.session_state.get("selected_anomaly_idx") or 0
    sel_idx = min(sel_idx, len(options) - 1)

    chosen_label = st.selectbox(
        "Select anomaly to investigate",
        options,
        index=sel_idx,
    )
    anom_idx  = options.index(chosen_label)
    anom      = anomalies[anom_idx]
    st.session_state.selected_anomaly_idx = anom_idx

    # Derive windows from the anomaly's domain
    _dw = domain_windows or {}
    baseline_window = _dw.get(anom.domain, {}).get("baseline", 90)

    # Header
    st.markdown(
        f"### {anom.kpi_name} &nbsp; "
        f'<span class="badge badge-{anom.severity}">{anom.severity}</span>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"**Domain:** {anom.domain} &nbsp;|&nbsp; "
        f"**Dimension:** {anom.dimension_label()} &nbsp;|&nbsp; "
        f"**Period:** {anom.analysis_start} → {anom.analysis_end} &nbsp;|&nbsp; "
        f"**Method:** {anom.detection_method.replace('_', ' ')}"
    )
    st.info(anom.summary)
    st.divider()

    tab1, tab2, tab3 = st.tabs(["Drill-Down", "Cross-KPI Validation", "Historical Trend"])

    with tab1:
        _tab_drill_down(anom, loader, baseline_window)

    with tab2:
        _tab_correlation(anom, loader, baseline_window)

    with tab3:
        _tab_trend(anom, loader)


def _tab_drill_down(anom: Anomaly, loader: DataLoader, baseline_window: int = 90):
    st.subheader("Hierarchical Drill-Down")
    st.caption(
        "The system decomposes the anomaly across hierarchy levels to identify "
        "which region, branch, RM, or segment is the primary contributor."
    )

    with st.spinner("Analyzing drill-down path…"):
        analyzer  = DrillDownAnalyzer(loader)
        drill_path = analyzer.analyze(anom, baseline_window=baseline_window)

    if not drill_path.nodes:
        st.warning("Insufficient data to drill down further from this dimension level.")
        return

    # Root cause callout
    st.success(f"**Root cause path:** {drill_path.root_cause_label}")

    # Waterfall / bar chart per level
    for level in HIERARCHY:
        level_nodes = [n for n in drill_path.nodes if n.level == level]
        if not level_nodes:
            continue

        st.markdown(f"#### By {level.replace('_', ' ').title()}")

        df_level = pd.DataFrame([{
            "Dimension": n.dimension_value,
            "Actual":    round(n.actual_avg, 2),
            "Expected":  round(n.expected_avg, 2),
            "Deviation %": round(n.deviation_pct, 1),
            "Contribution %": round(n.contribution_pct, 1),
            "Primary": n.is_primary_contributor,
        } for n in level_nodes])

        # Sort by absolute deviation
        df_level = df_level.reindex(
            df_level["Deviation %"].abs().sort_values(ascending=False).index
        )

        fig = go.Figure()
        colors = [
            "#d62728" if r["Deviation %"] < -15
            else "#ff7f0e" if r["Deviation %"] < 0
            else "#2ca02c"
            for _, r in df_level.iterrows()
        ]
        fig.add_trace(go.Bar(
            x=df_level["Dimension"],
            y=df_level["Deviation %"],
            marker_color=colors,
            text=[f"{v:+.1f}%" for v in df_level["Deviation %"]],
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Deviation: %{y:.1f}%<br>"
                "Actual: %{customdata[0]:.2f}<br>"
                "Expected: %{customdata[1]:.2f}<br>"
                "Contribution: %{customdata[2]:.1f}%<extra></extra>"
            ),
            customdata=df_level[["Actual", "Expected", "Contribution %"]].values,
        ))
        fig.update_layout(
            yaxis_title="Deviation from Baseline (%)",
            height=280,
            margin=dict(t=10, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Table
        st.dataframe(
            df_level.drop(columns=["Primary"]).style.map(
                lambda v: "background-color:#ffe0e0" if isinstance(v, float) and v < -15
                else "background-color:#fff3cd" if isinstance(v, float) and v < 0
                else "",
                subset=["Deviation %"],
            ),
            use_container_width=True,
            hide_index=True,
        )


def _tab_correlation(anom: Anomaly, loader: DataLoader, baseline_window: int = 90):
    st.subheader("Cross-KPI Validation")
    st.caption(
        "Checks whether correlated KPIs are also anomalous to determine "
        "if this is a genuine problem, market-driven, or a false alarm."
    )

    with st.spinner("Running correlation analysis…"):
        validator = CorrelationValidator(loader)
        report    = validator.validate(anom, baseline_window=baseline_window)

    # Verdict
    verdict_colors = {
        "Genuine Issue":  "#d62728",
        "Market-Driven":  "#1f77b4",
        "False Alarm":    "#2ca02c",
        "Unclear":        "#7f7f7f",
    }
    v_color = verdict_colors.get(report.overall_verdict, "#888")
    st.markdown(
        f"**Overall verdict:** "
        f'<span style="color:{v_color};font-weight:700;font-size:1.1rem">'
        f'{report.overall_verdict}</span> &nbsp; '
        f'(confidence: {report.verdict_confidence*100:.0f}%)',
        unsafe_allow_html=True,
    )
    st.divider()

    # Correlate status table
    if report.correlate_status:
        st.markdown("#### Correlated KPI Status")
        rows = []
        for c in report.correlate_status:
            rows.append({
                "KPI": c["kpi_name"],
                "Status": c["status"],
                "Deviation %": c.get("deviation_pct", 0),
                "Z-score": c.get("z_score", 0),
                "Note": c.get("note", ""),
            })
        df_c = pd.DataFrame(rows)

        def color_status(val):
            if val in ("Anomalous", "Market Stress"):
                return "background-color:#ffe0e0"
            if val == "Normal":
                return "background-color:#e0ffe0"
            return ""

        st.dataframe(
            df_c.style.map(color_status, subset=["Status"]),
            use_container_width=True,
            hide_index=True,
        )

    # Radial chart: correlate deviation landscape
    if report.correlate_status:
        theta = [c["kpi_name"] for c in report.correlate_status]
        r     = [abs(c.get("deviation_pct", 0)) for c in report.correlate_status]
        colors_r = [
            "red" if c.get("anomalous") else "green"
            for c in report.correlate_status
        ]

        fig = go.Figure(go.Bar(
            x=theta,
            y=r,
            marker_color=colors_r,
            text=[f"{v:.1f}%" for v in r],
            textposition="outside",
        ))
        fig.update_layout(
            title="Correlate Deviation Magnitude (%)",
            yaxis_title="|Deviation %|",
            height=300,
            margin=dict(t=40, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Hypotheses
    st.markdown("#### Hypotheses (ranked by confidence)")
    for i, hyp in enumerate(report.hypotheses):
        conf_color = "#d62728" if hyp.confidence >= 0.8 else "#ff7f0e" if hyp.confidence >= 0.6 else "#888"
        with st.expander(
            f"{'★' * round(hyp.confidence * 5)} **{hyp.hypothesis}** "
            f"— {hyp.verdict} ({hyp.confidence*100:.0f}% confidence)",
            expanded=(i == 0),
        ):
            st.markdown(f"**Evidence:** {hyp.evidence}")
            if hyp.supporting_kpis:
                st.markdown(f"**Supporting KPIs:** {', '.join(hyp.supporting_kpis)}")
            if hyp.contradicting_kpis:
                st.markdown(f"**Contradicting KPIs:** {', '.join(hyp.contradicting_kpis)}")


def _tab_trend(anom: Anomaly, loader: DataLoader):
    st.subheader("Historical Trend")

    end_date = loader.df["date"].max().date()
    start_date = end_date - timedelta(days=180)

    # Dimension filters from anomaly
    filters = {k: v for k, v in anom.dimension_values.items() if v}

    df = loader.aggregate(date_range=(start_date, end_date), filters=filters)
    if anom.kpi not in df.columns:
        st.warning("No data for this KPI.")
        return

    df = df.sort_values("date")
    agg_fn = "mean" if anom.kpi in _MEAN_KPIS else "sum"
    series = df.groupby("date")[anom.kpi].agg(agg_fn).reset_index()
    series.columns = ["date", "value"]

    # Rolling baseline band (±1.5 std)
    roll_mean = series["value"].rolling(30, min_periods=10).mean()
    roll_std  = series["value"].rolling(30, min_periods=10).std()
    upper = roll_mean + 1.5 * roll_std
    lower = roll_mean - 1.5 * roll_std

    fig = go.Figure()

    # Confidence band
    fig.add_trace(go.Scatter(
        x=pd.concat([series["date"], series["date"][::-1]]),
        y=pd.concat([upper, lower[::-1]]),
        fill="toself",
        fillcolor="rgba(31,119,180,0.10)",
        line=dict(color="rgba(255,255,255,0)"),
        name="Normal range (±1.5σ)",
        hoverinfo="skip",
    ))

    # Rolling mean
    fig.add_trace(go.Scatter(
        x=series["date"], y=roll_mean,
        line=dict(color="#1f77b4", dash="dot", width=1),
        name="30-day avg",
    ))

    # Actual line
    fig.add_trace(go.Scatter(
        x=series["date"], y=series["value"],
        line=dict(color="#2c3e50", width=2),
        name=anom.kpi_name,
    ))

    # Shade anomaly window
    fig.add_vrect(
        x0=anom.analysis_start, x1=anom.analysis_end,
        fillcolor="rgba(214,39,40,0.12)",
        line_width=0,
        annotation_text="Anomaly window",
        annotation_position="top left",
    )

    fig.update_layout(
        title=f"{anom.kpi_name} — Last 180 days  |  {anom.dimension_label()}",
        yaxis_title=f"{anom.kpi_name} ({anom.unit})",
        xaxis_title="Date",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=400,
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # MoM breakdown by dimension
    if anom.dimension_level not in ("firm", "rm_id"):
        next_idx = HIERARCHY.index(anom.dimension_level) + 1 if anom.dimension_level in HIERARCHY else 0
        if next_idx < len(HIERARCHY):
            next_level = HIERARCHY[next_idx]
            st.markdown(f"**Breakdown by {next_level.title()} (last 30 days)**")
            last30 = loader.last_n_days(30)
            df_breakdown = loader.aggregate(
                group_by=[next_level],
                date_range=last30,
                filters=filters,
            )
            if not df_breakdown.empty and anom.kpi in df_breakdown.columns:
                bd_agg = "mean" if anom.kpi in _MEAN_KPIS else "sum"
                by_dim = df_breakdown.groupby(next_level)[anom.kpi].agg(bd_agg).reset_index()
                by_dim.columns = [next_level, "Total"]
                by_dim = by_dim.sort_values("Total", ascending=False)
                fig2 = px.bar(
                    by_dim, x=next_level, y="Total",
                    title=f"{anom.kpi_name} by {next_level.title()}",
                    height=280,
                )
                st.plotly_chart(fig2, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 4 — Trend Explorer
# ─────────────────────────────────────────────────────────────────────────────

def page_trend_explorer():
    st.title("Trend Explorer")
    st.caption("Manually explore any KPI with dimension filters and compare periods.")

    loader = get_loader()
    end_date   = loader.df["date"].max().date()

    tc1, tc2, tc3 = st.columns([2, 2, 2])
    with tc1:
        domain_sel = st.selectbox("Domain", ["Broking", "Wealth", "Clients"])
        kpi_options = loader.domain_kpis(domain_sel)
        kpi_sel = st.selectbox("KPI", kpi_options,
                               format_func=loader.kpi_display)
    with tc2:
        region_sel  = st.selectbox("Region",  ["All"] + ["North", "South", "East", "West"])
        branch_opts = (
            ["All"] + loader.config["dimensions"]["branches"].get(region_sel, [])
            if region_sel != "All" else ["All"]
        )
        branch_sel = st.selectbox("Branch", branch_opts)
    with tc3:
        segment_sel = st.selectbox("Segment", ["All", "Retail", "HNI", "Ultra_HNI"])
        lookback = st.slider("Lookback (days)", 30, 365, 180)

    filters = {}
    if region_sel  != "All": filters["region"]  = region_sel
    if branch_sel  != "All": filters["branch"]  = branch_sel
    if segment_sel != "All": filters["segment"] = segment_sel

    start_date = end_date - timedelta(days=lookback)
    df = loader.aggregate(date_range=(start_date, end_date), filters=filters)

    if kpi_sel not in df.columns or df.empty:
        st.warning("No data for the selected filters.")
        return

    ts_agg = "mean" if kpi_sel in _MEAN_KPIS else "sum"
    df_ts = df.groupby("date")[kpi_sel].agg(ts_agg).reset_index()
    df_ts.columns = ["date", "value"]
    df_ts = df_ts.sort_values("date")

    roll_mean = df_ts["value"].rolling(30, min_periods=5).mean()
    roll_std  = df_ts["value"].rolling(30, min_periods=5).std()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pd.concat([df_ts["date"], df_ts["date"][::-1]]),
        y=pd.concat([roll_mean + 2*roll_std, (roll_mean - 2*roll_std)[::-1]]),
        fill="toself",
        fillcolor="rgba(44,160,44,0.08)",
        line=dict(color="rgba(0,0,0,0)"),
        name="±2σ band",
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=df_ts["date"], y=roll_mean,
        line=dict(color="#1f77b4", dash="dot", width=1.5),
        name="30-day MA",
    ))
    fig.add_trace(go.Scatter(
        x=df_ts["date"], y=df_ts["value"],
        line=dict(color="#2c3e50", width=2),
        mode="lines",
        name=loader.kpi_display(kpi_sel),
    ))
    fig.update_layout(
        title=f"{loader.kpi_display(kpi_sel)}",
        yaxis_title=f"{loader.kpi_display(kpi_sel)} ({loader.kpi_unit(kpi_sel)})",
        height=420,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Period comparison
    st.subheader("Period comparison")
    pc1, pc2 = st.columns(2)
    with pc1:
        current_n = st.number_input("Current period (days)", 7, 90, 30)
    with pc2:
        compare_n = st.number_input("Compare against prior (days)", 7, 90, 30)

    cur_range  = loader.last_n_days(int(current_n))
    prev_range = loader.prior_n_days(int(compare_n), int(current_n))

    cur_df  = loader.aggregate(date_range=cur_range,  filters=filters)
    prev_df = loader.aggregate(date_range=prev_range, filters=filters)

    if not cur_df.empty and not prev_df.empty and kpi_sel in cur_df.columns:
        cur_val  = _period_agg(cur_df,  kpi_sel)
        prev_val = _period_agg(prev_df, kpi_sel)
        delta    = (cur_val - prev_val) / abs(prev_val) * 100 if prev_val else 0
        direction = loader.kpi_direction(kpi_sel)
        delta_color = (
            "normal" if (delta > 0 and direction == "higher_is_better")
                     or (delta < 0 and direction == "lower_is_better")
            else "inverse"
        )

        m1, m2, m3 = st.columns(3)
        m1.metric(f"Current {current_n}d", _fmt(cur_val, loader.kpi_unit(kpi_sel)))
        m2.metric(f"Prior {compare_n}d",   _fmt(prev_val, loader.kpi_unit(kpi_sel)))
        m3.metric("Change", f"{delta:+.1f}%", delta_color=delta_color)

    # Breakdown bar
    if region_sel == "All":
        breakdown_level = "region"
    elif branch_sel == "All":
        breakdown_level = "branch"
    else:
        breakdown_level = "segment"

    st.subheader(f"Last {current_n}d breakdown by {breakdown_level.title()}")
    cur_break = loader.aggregate(
        group_by=[breakdown_level],
        date_range=cur_range,
        filters=filters,
    )
    if not cur_break.empty and kpi_sel in cur_break.columns:
        agg_fn = "mean" if kpi_sel in _MEAN_KPIS else "sum"
        by_dim = cur_break.groupby(breakdown_level)[kpi_sel].agg(agg_fn).reset_index()
        by_dim.columns = [breakdown_level, "value"]
        fig2 = px.pie(
            by_dim, values="value", names=breakdown_level,
            title=f"{loader.kpi_display(kpi_sel)} share by {breakdown_level.title()}",
            height=350,
        )
        st.plotly_chart(fig2, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 5 — About
# ─────────────────────────────────────────────────────────────────────────────

def page_about():
    st.title("About This System")
    st.markdown("""
### KPI Monitoring System — Architecture

This system monitors KPIs across **Broking**, **Wealth**, and **Client** domains
for a broking / wealth management firm. It detects anomalies, traces them to their
root source, and validates whether they are genuine issues or noise.

---

#### Detection methods

| Method | Description |
|---|---|
| **Rolling Z-score** | Flags when the analysis-window average deviates >2σ from 90-day baseline |
| **Target breach** | Flags when deviation from baseline exceeds per-KPI threshold % |
| **Trend reversal** | Detects when the 7-day slope flips sign vs. the 30-day trend |

#### Drill-down engine
Decomposes any anomaly hierarchically: **Firm → Region → Branch → RM → Segment**,
computing each sub-dimension's contribution % to the total variance. The path to the
highest-contributing leaf is surfaced as the root cause.

#### Cross-KPI validation
Each KPI declares its correlates in `kpi_config.yaml`. When an anomaly fires, the
system checks whether correlates are also anomalous and generates ranked hypotheses:
- **Genuine Issue** — correlates confirm the problem
- **Market-Driven** — Nifty stress explains the drop
- **False Alarm** — all correlates are healthy

#### KPIs monitored

| Domain | KPIs |
|---|---|
| Broking | Brokerage Revenue, Equity Volume, Derivatives Volume, Active Clients, New Accounts |
| Wealth | Total AUM, SIP Inflows, Lumpsum Inflows, Redemptions, Net Flows |
| Clients | Total Active Clients, Client Activation Rate |

#### Hierarchy
```
Firm
  └─ Region  (North / South / East / West)
       └─ Branch  (12 branches)
            └─ RM  (48 RMs)
                 └─ Segment  (Retail / HNI / Ultra_HNI)
```

#### Configuration
Edit `kpi_config.yaml` to:
- Add or remove KPIs
- Adjust Z-score and target breach thresholds per KPI
- Change declared correlates

#### Injected demo anomalies
The synthetic dataset contains 4 deliberate anomalies for demonstration:
1. **South region HNI brokerage** — down ~48% (last 18 days)
2. **East Kolkata redemptions** — up ~140% (last 10 days)
3. **North Delhi new accounts** — near zero (last 8 days)
4. **West Mumbai Ultra-HNI AUM** — down ~32% (last 14 days)
""")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# KPIs that represent a level/rate — use mean over period, not sum.
# Sum would count e.g. AUM 14 times (once per trading day).
_MEAN_KPIS = {"aum", "client_count", "active_clients", "activation_rate"}


def _period_agg(df: pd.DataFrame, kpi: str) -> float:
    """Return the appropriate period aggregate: mean for stock/rate KPIs, sum for flows."""
    if kpi not in df.columns or df.empty:
        return 0.0
    return float(df[kpi].mean() if kpi in _MEAN_KPIS else df[kpi].sum())


def _fmt(value: float, unit: str) -> str:
    if unit == "%":
        # activation_rate stored as 0–1; multiply to get human-readable %
        return f"{value * 100:.1f}%"
    if unit in ("₹ Lakhs",):
        sign = "-" if value < 0 else ""
        v = abs(value)
        if v >= 1_00_000:           # ≥ 1 lakh Lakhs = 1 Lakh Crore
            return f"{sign}₹{v/1_00_000:.2f}L Cr"
        elif v >= 100:              # ≥ 100 Lakhs = 1 Crore
            return f"{sign}₹{v/100:,.0f}Cr"
        else:
            return f"{sign}₹{v:.1f}L"
    if unit == "Count":
        return f"{int(value):,}"
    return f"{value:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    domain_windows = sidebar()

    # Verify data exists
    data_path = Path("data/kpi_data.parquet")
    if not data_path.exists():
        st.error(
            "Data not found. Run `python generate_data.py` first to generate synthetic data."
        )
        st.stop()

    try:
        loader = get_loader()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        st.stop()

    regime            = get_volatility_regime(id(loader))
    zscore_multiplier = regime[2]
    dw                = domain_windows

    with st.spinner("Running anomaly detection…"):
        anomalies = get_anomalies(
            id(loader),
            dw["Broking"]["analysis"], dw["Broking"]["baseline"],
            dw["Wealth"]["analysis"],  dw["Wealth"]["baseline"],
            dw["Clients"]["analysis"], dw["Clients"]["baseline"],
            zscore_multiplier,
        )

    page = st.session_state.page

    if page == "KPI Scorecard":
        page_scorecard(anomalies, domain_windows, regime)
    elif page == "Anomaly Alerts":
        page_anomalies(anomalies)
    elif page == "Investigate Anomaly":
        page_investigate(anomalies, domain_windows, regime)
    elif page == "Trend Explorer":
        page_trend_explorer()
    elif page == "About":
        page_about()


if __name__ == "__main__":
    main()
