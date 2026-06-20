"""
KPI Monitoring Dashboard — Broking & Wealth Management
Run: streamlit run app.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import time as _time
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

from kpi_monitor.data_loader import DataLoader, HIERARCHY
from kpi_monitor.anomaly_detector import AnomalyDetector, Anomaly, SEVERITY_COLORS, METHOD_LABELS
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
def get_volatility_regime(_loader_id) -> tuple:
    """
    Combines Nifty 30-day volatility (relative to 90-day baseline) and
    30-day cumulative return (relative to baseline drift).
    Returns (combined_label, vol_pct_per_day, zscore_multiplier,
             dir_label, vol_label, ret_30d_pct).
    Index 2 is always zscore_multiplier for backward-compatible callers.
    """
    loader = get_loader()
    mkt    = loader.market
    if mkt.empty:
        return ("Flat + Calm", 0.0, 1.0, "Flat", "Calm", 0.0)

    mkt     = mkt.sort_values("date")
    returns = mkt["nifty_return"]

    # Split: recent = last 30 trading days, baseline = prior 90 trading days
    recent_30   = returns.tail(30)
    baseline_90 = returns.iloc[-(30 + 90):-30] if len(returns) >= 120 else returns.iloc[:-30]
    if len(baseline_90) < 10:
        baseline_90 = returns

    # ── Volatility: ratio of recent vs baseline daily std ──────────────────
    recent_vol   = float(recent_30.std()   * 100) if len(recent_30)   > 2 else 0.0
    baseline_vol = float(baseline_90.std() * 100) if len(baseline_90) > 2 else (recent_vol or 1.0)
    vol_ratio    = recent_vol / baseline_vol if baseline_vol > 0 else 1.0

    if vol_ratio < 1.2:
        vol_label = "Calm"
    elif vol_ratio < 1.8:
        vol_label = "Elevated"
    else:
        vol_label = "High"

    # ── Direction: recent 30d cumulative return vs baseline daily drift ─────
    ret_30d_pct        = float((recent_30 + 1).prod() - 1) * 100   # cumulative %
    baseline_30d_equiv = float(baseline_90.mean() * 100) * 30       # baseline drift over 30 days
    divergence         = ret_30d_pct - baseline_30d_equiv            # positive = outpacing baseline

    if divergence > 3.0:
        dir_label = "Bull"
    elif divergence < -3.0:
        dir_label = "Bear"
    else:
        dir_label = "Flat"

    # ── Multiplier matrix ───────────────────────────────────────────────────
    _matrix = {
        ("Bull", "Calm"):     1.0,
        ("Bull", "Elevated"): 1.1,
        ("Bull", "High"):     1.2,
        ("Flat", "Calm"):     1.0,
        ("Flat", "Elevated"): 1.2,
        ("Flat", "High"):     1.4,
        ("Bear", "Calm"):     1.2,
        ("Bear", "Elevated"): 1.4,
        ("Bear", "High"):     1.6,
    }
    zscore_multiplier = _matrix[(dir_label, vol_label)]
    combined_label    = f"{dir_label} + {vol_label}"

    return (combined_label, recent_vol, zscore_multiplier, dir_label, vol_label, ret_30d_pct)


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

    if st.sidebar.button("💬 Ask Claude", key="ask_claude_btn", use_container_width=True, type="primary"):
        st.session_state.page = "Ask Claude"
        st.session_state.nav_radio = "Ask Claude"
        st.session_state._nav_source = "button"
        st.rerun()

    st.sidebar.divider()

    pages = [
        "KPI Scorecard",
        "Anomaly Alerts",
        "Investigate Anomaly",
        "Team Scorecard",
        "Ask Claude",
        "About",
    ]
    # Sync the radio to any button-driven navigation BEFORE the widget renders.
    # (Widget keys can only be written before instantiation, not after.)
    if "nav_radio" not in st.session_state:
        st.session_state.nav_radio = st.session_state.page
    if st.session_state.get("_nav_source") == "button":
        st.session_state.nav_radio = st.session_state.page
        del st.session_state["_nav_source"]

    st.sidebar.radio("Navigate", pages, key="nav_radio")

    # If the user clicked the radio, propagate to page state.
    if st.session_state.nav_radio != st.session_state.page:
        st.session_state.page = st.session_state.nav_radio

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

def _regime_style(zscore_multiplier: float) -> tuple[str, str]:
    if zscore_multiplier >= 1.4:
        return "rgba(214,39,40,0.12)", "#d62728"
    if zscore_multiplier > 1.0:
        return "rgba(255,127,14,0.12)", "#ff7f0e"
    return "rgba(44,160,44,0.12)", "#2ca02c"


def page_scorecard(
    anomalies: list[Anomaly],
    domain_windows: dict | None = None,
    regime: tuple = ("Flat + Calm", 0.0, 1.0, "Flat", "Calm", 0.0),
):
    if domain_windows is None:
        domain_windows = {
            "Broking": {"analysis": 5,  "baseline": 60},
            "Wealth":  {"analysis": 14, "baseline": 90},
            "Clients": {"analysis": 30, "baseline": 180},
        }

    st.title("KPI Health Scorecard")
    loader = get_loader()

    # Build a lookup: kpi → (worst anomaly, its index in the global anomalies list)
    # Ranking: highest severity → deepest hierarchy level → largest absolute impact.
    # This surfaces the single most actionable root-cause dimension for each KPI card.
    _dim_depth = {"firm": 0, "region": 1, "branch": 2, "rm_id": 3, "segment": 4}
    def _anomaly_rank(a: Anomaly) -> tuple:
        return (
            -a.severity_score,
            -_dim_depth.get(a.dimension_level, 0),
            -abs(a.actual_value - a.expected_value),
        )

    kpi_worst: dict[str, tuple[Anomaly, int]] = {}
    for _i, a in enumerate(anomalies):
        if a.kpi not in kpi_worst or _anomaly_rank(a) < _anomaly_rank(kpi_worst[a.kpi][0]):
            kpi_worst[a.kpi] = (a, _i)

    # Summary row
    n_critical = sum(1 for a, _ in kpi_worst.values() if a.severity == "Critical")
    n_warning  = sum(1 for a, _ in kpi_worst.values() if a.severity == "Warning")
    n_watch    = sum(1 for a, _ in kpi_worst.values() if a.severity == "Watch")
    n_ok       = len(loader.firm_kpis()) - len(kpi_worst)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Critical", n_critical,  delta=None)
    c2.metric("Warning",  n_warning,   delta=None)
    c3.metric("Watch",    n_watch,      delta=None)
    c4.metric("Healthy",  max(n_ok, 0), delta=None)

    # Window summary caption
    st.caption(
        "*(analysis window / baseline window):*  "
        + "  ·  ".join(
            f"{d} **{domain_windows[d]['analysis']}d** / {domain_windows[d]['baseline']}d"
            for d in ("Broking", "Wealth", "Clients")
        )
    )

    # Volatility regime badge
    reg_label, vol_pct, zs_mult, dir_label, vol_label, ret_30d = regime
    reg_bg, reg_fg = _regime_style(zs_mult)
    thresh_note = (
        f"Thresholds raised +{(zs_mult - 1)*100:.0f}% — market noise filtered"
        if zs_mult > 1.0 else "Standard thresholds"
    )
    dir_arrow = "↑" if dir_label == "Bull" else "↓" if dir_label == "Bear" else "→"
    st.markdown(
        f'<div style="display:inline-flex;align-items:center;gap:12px;'
        f'background:{reg_bg};border:1px solid {reg_fg};'
        f'border-radius:7px;padding:6px 14px;margin-bottom:4px;font-size:0.80rem">'
        f'<span style="color:{reg_fg};font-weight:700">● {reg_label}</span>'
        f'<span style="opacity:0.55">'
        f'Nifty 30d: {dir_arrow} {ret_30d:+.1f}% return · {vol_pct:.2f}%/day vol'
        f'</span>'
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

                worst_pair = kpi_worst.get(kpi)
                worst, worst_idx = worst_pair if worst_pair else (None, 0)
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
                    is_bad_move = (
                        (delta_pct < 0 and direction == "higher_is_better")
                        or (delta_pct > 0 and direction == "lower_is_better")
                    )
                    anom_note = (
                        f"↓{abs(delta_pct):.0f}% drop within normal variance"
                        if is_bad_move and abs(delta_pct) >= 3
                        else ""
                    )

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

                # ── Option A: mini region breakdown inside anomalous cards ────
                bd_frag = ""
                if worst:
                    bd_rows = get_card_breakdown(id(loader), kpi, aw, bw)[:3]
                    if bd_rows:
                        bd_frag = (
                            '<div style="margin-top:8px;padding-top:7px;'
                            'border-top:1px solid rgba(128,128,128,0.15)">'
                            '<div style="font-size:0.60rem;text-transform:uppercase;'
                            'letter-spacing:0.07em;opacity:0.4;margin-bottom:5px">'
                            'by region</div>'
                            + _breakdown_rows_html(bd_rows, direction)
                            + '</div>'
                        )

                st.markdown(f"""
<div class="kpi-card {css_cls}">
  <div class="kpi-label">{loader.kpi_display(kpi)}</div>
  <div class="kpi-value">{_fmt(recent_val, unit)}<span style="font-size:0.65rem;opacity:0.55">{"" if loader.kpi_is_stock(kpi) else " /day avg"}</span></div>
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
  {bd_frag}
  <div class="kpi-card-footer">{badge}{anom_html}</div>
</div>
""", unsafe_allow_html=True)
                # Expand button — only for anomalous KPIs (Option A)
                if worst:
                    if st.button(
                        "Investigate →",
                        key=f"inv_sc_{kpi}",
                        use_container_width=True,
                    ):
                        st.session_state.selected_anomaly_idx = worst_idx
                        st.session_state.page = "Investigate Anomaly"
                        st.session_state._nav_source = "button"
                        st.rerun()

        st.write("")


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 2 — Anomaly Alerts
# ─────────────────────────────────────────────────────────────────────────────

def page_anomalies(anomalies: list[Anomaly], domain_windows: dict | None = None):
    st.title("Anomaly Alerts")

    loader = get_loader()
    if not anomalies:
        st.success("No anomalies detected in the current analysis window.")
        return

    # Persistent filter store — plain session state keys (not widget keys).
    # Streamlit removes widget-key entries when the widget isn't rendered,
    # but leaves plain keys alone, so these survive page navigation.
    kpi_options = sorted(set(a.kpi_name for a in anomalies))
    _all_levels = ["firm"] + HIERARCHY
    if "_f_sev"    not in st.session_state: st.session_state._f_sev    = ["Critical", "Warning", "Watch"]
    if "_f_domain" not in st.session_state: st.session_state._f_domain = ["Broking", "Wealth", "Clients"]
    if "_f_level"  not in st.session_state: st.session_state._f_level  = _all_levels
    if "_f_kpi"    not in st.session_state: st.session_state._f_kpi    = kpi_options
    else:
        st.session_state._f_kpi = [k for k in st.session_state._f_kpi if k in kpi_options]

    # Filters — row 1: Severity / Domain / Dimension level
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        sev_filter    = st.multiselect("Severity",        ["Critical", "Warning", "Watch"],
                                       default=st.session_state._f_sev)
    with fc2:
        domain_filter = st.multiselect("Domain",          ["Broking", "Wealth", "Clients"],
                                       default=st.session_state._f_domain)
    with fc3:
        level_filter  = st.multiselect("Dimension level", _all_levels,
                                       default=st.session_state._f_level)

    # Filters — row 2: KPI search
    kpi_filter = st.multiselect("KPI", kpi_options, default=st.session_state._f_kpi,
                                placeholder="All KPIs — select to narrow down")

    # Write selections back to persistent store immediately after render
    st.session_state._f_sev    = sev_filter
    st.session_state._f_domain = domain_filter
    st.session_state._f_level  = level_filter
    st.session_state._f_kpi    = kpi_filter

    _level_order = {"firm": 0, "region": 1, "branch": 2, "rm_id": 3, "segment": 4}
    filtered = sorted(
        (
            a for a in anomalies
            if a.severity in sev_filter
            and a.domain in domain_filter
            and a.dimension_level in level_filter
            and a.kpi_name in kpi_filter
        ),
        key=lambda a: (
            _level_order.get(a.dimension_level, 9),   # region first … segment last
            -abs(a.actual_value - a.expected_value),   # largest contribution first
        ),
    )

    st.caption(f"Showing {len(filtered)} of {len(anomalies)} anomalies")
    st.divider()

    if not filtered:
        if "firm" in level_filter and len(level_filter) == 1:
            st.info(
                "No firm-wide anomalies detected. Current anomalies are localised within "
                "specific regions or branches — the firm aggregate remains within normal range. "
                "Try including **Region** or **Branch** in the Dimension Level filter."
            )
        else:
            st.info("No anomalies match the current filters. Try broadening the Severity, Domain, or Dimension Level selections.")
        return

    _dw = domain_windows or {}

    for row_idx, anom in enumerate(filtered[:50]):
        # Determine bad-direction colour
        is_bad = (
            (anom.deviation_pct < 0 and anom.direction == "higher_is_better")
            or (anom.deviation_pct > 0 and anom.direction == "lower_is_better")
        )
        dev_col = "#d62728" if is_bad else "#2ca02c"
        sign    = "↓" if anom.deviation_pct < 0 else "↑"
        method  = METHOD_LABELS.get(anom.detection_method, anom.detection_method)

        # ── Option C: left = metadata, right = ranked contributors ───────────
        left, right = st.columns([5, 7])

        with left:
            st.markdown(
                f'<div style="padding:4px 0 8px">'
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
                f'<span class="badge badge-{anom.severity}">{anom.severity}</span>'
                f'<span style="font-size:0.68rem;opacity:0.45">{method} · {anom.domain}</span>'
                f'</div>'
                f'<div style="font-size:0.93rem;font-weight:700;margin-bottom:2px">'
                f'{anom.kpi_name}</div>'
                f'<div style="font-size:0.72rem;opacity:0.55;margin-bottom:10px">'
                f'{anom.dimension_label()}</div>'
                f'<div style="display:flex;gap:18px">'
                f'<div><div style="font-size:0.62rem;opacity:0.45">Actual</div>'
                f'<div style="font-size:0.85rem;font-weight:600">'
                f'{_fmt(anom.actual_value, anom.unit)}</div></div>'
                f'<div><div style="font-size:0.62rem;opacity:0.45">Expected</div>'
                f'<div style="font-size:0.85rem;font-weight:600">'
                f'{_fmt(anom.expected_value, anom.unit)}</div></div>'
                f'<div><div style="font-size:0.62rem;opacity:0.45">Deviation</div>'
                f'<div style="font-size:0.85rem;font-weight:600;color:{dev_col}">'
                f'{sign}{abs(anom.deviation_pct):.1f}%</div></div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("Investigate →", key=f"inv_{row_idx}_{anom.kpi}"):
                st.session_state.selected_anomaly_idx = anomalies.index(anom)
                st.session_state.page = "Investigate Anomaly"
                st.session_state._nav_source = "button"
                st.rerun()

        with right:
            aw         = _dw.get(anom.domain, {}).get("analysis", 14)
            bw         = _dw.get(anom.domain, {}).get("baseline", 90)
            dims_tuple = tuple(sorted(anom.dimension_values.items()))
            l1_rows, l2_rows, l1_label, l2_label = get_alert_breakdown(
                id(loader), anom.kpi, aw, bw, anom.dimension_level, dims_tuple,
            )

            if l1_rows:
                l1_html   = _breakdown_rows_html(l1_rows, anom.direction)
                divider_h = (
                    '<div style="width:1px;background:rgba(128,128,128,0.2);'
                    'margin:0 6px;flex-shrink:0"></div>'
                ) if l2_rows else ""
                l2_block = (
                    f'<div style="flex:1;min-width:0">'
                    f'<div style="font-size:0.68rem;opacity:0.5;margin-bottom:5px">'
                    f'{l2_label}</div>'
                    + _breakdown_rows_html(l2_rows, anom.direction)
                    + '</div>'
                ) if l2_rows else ""

                st.markdown(
                    '<div style="padding:4px 0 8px">'
                    '<div style="font-size:0.60rem;text-transform:uppercase;'
                    'letter-spacing:0.07em;opacity:0.4;margin-bottom:8px">'
                    'Ranked contributors</div>'
                    '<div style="display:flex;gap:4px">'
                    '<div style="flex:1;min-width:0">'
                    f'<div style="font-size:0.68rem;opacity:0.5;margin-bottom:5px">'
                    f'{l1_label}</div>'
                    + l1_html
                    + '</div>'
                    + divider_h
                    + l2_block
                    + '</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No sub-level breakdown available for this dimension.")

        st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 3 — Investigate Anomaly
# ─────────────────────────────────────────────────────────────────────────────

def page_investigate(
    anomalies: list[Anomaly],
    domain_windows: dict | None = None,
    regime: tuple = ("Flat + Calm", 0.0, 1.0, "Flat", "Calm", 0.0),
):
    st.title("Anomaly Investigation")
    loader = get_loader()

    if not anomalies:
        st.info("No anomalies to investigate. Adjust detection settings in the sidebar.")
        return

    # Anomaly selector — use the FULL anomalies list so buttons that navigate
    # to an anomaly beyond position 30 still land on the correct entry.
    options = [
        f"[{a.severity}] {a.kpi_name} — {a.dimension_label()} ({a.deviation_pct:+.1f}%)"
        for a in anomalies
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
        f"**Method:** {METHOD_LABELS.get(anom.detection_method, anom.detection_method)}"
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

    # Primary KPI at firm level — the anchor for interpreting everything else
    pfs = report.primary_firm_status
    if pfs:
        firm_anomalous = pfs.get("anomalous", False)
        firm_dev       = pfs.get("deviation_pct", 0)
        if firm_anomalous:
            firm_icon, firm_bg, firm_msg = (
                "⚠️", "rgba(214,39,40,0.08)",
                f"<b>{anom.kpi_name} is also anomalous at firm level</b> ({firm_dev:+.1f}%). "
                f"This dimension is likely the worst-hit part of a broader decline."
            )
        else:
            firm_icon, firm_bg, firm_msg = (
                "✓", "rgba(44,160,44,0.08)",
                f"<b>{anom.kpi_name} is healthy at firm level</b> ({firm_dev:+.1f}%). "
                f"The drop is contained to {anom.dimension_label()} — not a firm-wide problem."
            )
        st.markdown(
            f'<div style="background:{firm_bg};border-radius:8px;padding:10px 14px;'
            f'margin-bottom:12px;font-size:0.88rem">'
            f'{firm_icon} {firm_msg}</div>',
            unsafe_allow_html=True,
        )

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
# PAGE 4 — Team Scorecard
# ─────────────────────────────────────────────────────────────────────────────

_EH_KPIS = [
    "brokerage_revenue", "equity_volume", "derivatives_volume", "active_clients",
    "aum", "sip_inflows", "lumpsum_inflows", "redemptions", "net_flows",
    "new_accounts", "client_count", "activation_rate",
]
_EH_KPI_BY_DOMAIN = {
    "Broking": ["brokerage_revenue", "equity_volume", "derivatives_volume", "active_clients"],
    "Wealth":  ["aum", "sip_inflows", "lumpsum_inflows", "redemptions", "net_flows"],
    "Clients": ["new_accounts", "client_count", "activation_rate"],
}
_BADGE_COLORS = {
    "Critical": "#d62728",
    "Warning":  "#ff7f0e",
    "Watch":    "#bcbd22",
    "Healthy":  "#2ca02c",
}
_SEV_ORDER = {"Critical": 0, "Warning": 1, "Watch": 2, "Healthy": 3}


@st.cache_data(ttl=300)
def get_entity_health_data(_loader_id: int, level: str, dw_tuple: tuple) -> dict:
    """
    Returns entity_path -> kpi -> {deviation_pct, actual, baseline, direction}.
    Mean-vs-mean comparison so both flow and stock KPIs are consistent.
    """
    loader = get_loader()
    dw = {d: {"analysis": aw, "baseline": bw} for d, aw, bw in dw_tuple}

    h_idx     = HIERARCHY.index(level)
    group_cols = HIERARCHY[: h_idx + 1]
    results: dict[str, dict] = {}

    for kpi in _EH_KPIS:
        domain = loader.kpi_domain(kpi)
        aw = dw.get(domain, {}).get("analysis", 14)
        bw = dw.get(domain, {}).get("baseline", 90)

        df = loader.aggregate(group_by=group_cols)
        if kpi not in df.columns or df.empty:
            continue

        end     = df["date"].max()
        a_start = end - timedelta(days=aw - 1)
        b_start = end - timedelta(days=bw + aw)
        b_end   = a_start - timedelta(days=1)

        act  = df[df["date"] >= a_start].groupby(group_cols)[kpi].mean()
        base = df[(df["date"] >= b_start) & (df["date"] <= b_end)].groupby(group_cols)[kpi].mean()

        for idx in act.index.intersection(base.index):
            b_val = float(base[idx])
            a_val = float(act[idx])
            if b_val == 0:
                continue
            dev_pct    = (a_val - b_val) / abs(b_val) * 100
            entity_key = " › ".join(
                str(v) for v in (idx if isinstance(idx, tuple) else (idx,))
            )
            if entity_key not in results:
                results[entity_key] = {}
            results[entity_key][kpi] = {
                "deviation_pct": round(dev_pct, 1),
                "actual":        round(a_val, 2),
                "baseline":      round(b_val, 2),
                "direction":     loader.kpi_direction(kpi),
            }

    return results


def _dev_severity(dev_pct: float, direction: str) -> str:
    bad = -dev_pct if direction == "higher_is_better" else dev_pct
    if bad <= 0:
        return "Healthy"
    if bad >= 35:
        return "Critical"
    if bad >= 20:
        return "Warning"
    if bad >= 10:
        return "Watch"
    return "Healthy"


def _entity_assessment(kpi_stats: dict, loader) -> str:
    by_sev: dict[str, list] = {"Critical": [], "Warning": [], "Watch": []}
    for kpi, info in kpi_stats.items():
        sev = info.get("severity")
        if sev in by_sev:
            by_sev[sev].append((kpi, info["deviation_pct"]))

    if not any(v for v in by_sev.values()):
        return "All KPIs are within normal range. No concerns detected."

    parts = []
    if by_sev["Critical"]:
        worst_kpi, worst_dev = min(by_sev["Critical"], key=lambda x: x[1])
        domains = sorted({loader.kpi_domain(k) for k, _ in by_sev["Critical"]})
        n = len(by_sev["Critical"])
        parts.append(
            f"<b>{n} KPI{'s' if n > 1 else ''} at Critical level</b> ({', '.join(domains)}). "
            f"Worst: <b>{loader.kpi_display(worst_kpi)}</b> at {worst_dev:+.1f}% vs baseline."
        )
    if by_sev["Warning"]:
        n = len(by_sev["Warning"])
        domains = sorted({loader.kpi_domain(k) for k, _ in by_sev["Warning"]})
        parts.append(
            f"{n} KPI{'s' if n > 1 else ''} at Warning level ({', '.join(domains)})."
        )
    if by_sev["Watch"]:
        n = len(by_sev["Watch"])
        parts.append(
            f"{n} KPI{'s' if n > 1 else ''} under Watch — early signals, monitor closely."
        )
    return " ".join(parts)


def _eh_render_heatmap(entity_order: list, kpi_order: list, entity_data: dict, loader) -> None:
    z_vals, text_vals, hover_vals = [], [], []

    for entity in entity_order:
        row_z, row_t, row_h = [], [], []
        for kpi in kpi_order:
            info = entity_data.get(entity, {}).get(kpi)
            if info is None:
                row_z.append(None)
                row_t.append("")
                row_h.append(f"<b>{entity}</b><br>{loader.kpi_display(kpi)}: N/A")
                continue
            dev       = info["deviation_pct"]
            direction = info["direction"]
            # Flip lower_is_better so red always = bad outcome
            display_val = dev if direction == "higher_is_better" else -dev
            row_z.append(display_val)
            row_t.append(f"{dev:+.0f}%")
            row_h.append(
                f"<b>{entity}</b><br>"
                f"{loader.kpi_display(kpi)}: {dev:+.1f}%<br>"
                f"Actual {info['actual']:,.1f} · Baseline {info['baseline']:,.1f}"
            )
        z_vals.append(row_z)
        text_vals.append(row_t)
        hover_vals.append(row_h)

    fig = go.Figure(go.Heatmap(
        z=z_vals,
        x=[loader.kpi_display(k) for k in kpi_order],
        y=entity_order,
        colorscale=[
            [0.00, "#b22222"],
            [0.25, "#ff7f0e"],
            [0.42, "#ffe066"],
            [0.50, "#f5f5f5"],
            [0.62, "#c7e9c0"],
            [1.00, "#2ca02c"],
        ],
        zmid=0, zmin=-50, zmax=50,
        text=text_vals,
        texttemplate="%{text}",
        textfont={"size": 9},
        customdata=hover_vals,
        hovertemplate="%{customdata}<extra></extra>",
        colorbar=dict(title="vs baseline", ticksuffix="%", thickness=12, len=0.75),
    ))

    n = len(entity_order)
    row_h = max(28, min(44, 400 // max(n, 1)))
    fig.update_layout(
        height=max(300, row_h * n + 130),
        margin=dict(t=40, b=20, l=160, r=60),
        xaxis=dict(side="top", tickangle=-35, tickfont=dict(size=10)),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
    )
    st.plotly_chart(fig, use_container_width=True)


def _eh_render_leaderboard(entity_order: list, entity_meta: dict, loader) -> None:
    rows = []
    for rank, entity in enumerate(entity_order, 1):
        meta      = entity_meta[entity]
        worst_name = loader.kpi_display(meta["worst_kpi"]) if meta["worst_kpi"] else "—"
        rows.append({
            "Rank":      rank,
            "Entity":    entity,
            "Health":    meta["badge"],
            "Critical":  meta["n_crit"]  or "—",
            "Warning":   meta["n_warn"]  or "—",
            "Watch":     meta["n_watch"] or "—",
            "Healthy":   meta["n_ok"],
            "Worst KPI": worst_name,
            "Dev %":     f"{meta['worst_dev_pct']:+.1f}%" if meta["worst_kpi"] else "—",
        })

    df = pd.DataFrame(rows).set_index("Rank")
    styled = df.style.map(
        lambda v: f"color: {_BADGE_COLORS.get(v, '#888')}; font-weight: 700",
        subset=["Health"],
    )
    st.dataframe(styled, use_container_width=True)


def _eh_render_profile(entity: str, meta: dict, loader) -> None:
    badge = meta["badge"]
    color = _BADGE_COLORS.get(badge, "#888")
    st.markdown(
        f'<span style="display:inline-block;padding:3px 12px;border-radius:12px;'
        f'background:{color};color:white;font-weight:700;font-size:0.80rem">{badge}</span>'
        f'&nbsp;&nbsp;<span style="opacity:0.75">{entity}</span>',
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Critical", meta["n_crit"])
    m2.metric("Warning",  meta["n_warn"])
    m3.metric("Watch",    meta["n_watch"])
    m4.metric("Healthy",  meta["n_ok"])

    assessment = _entity_assessment(meta["kpi_stats"], loader)
    st.markdown(
        f'<div style="background:rgba(128,128,128,0.07);border-radius:8px;'
        f'padding:12px 16px;margin:8px 0 14px 0;font-size:0.87rem">'
        f'{assessment}</div>',
        unsafe_allow_html=True,
    )

    for domain in ("Broking", "Wealth", "Clients"):
        domain_kpis = [
            (k, info)
            for k, info in meta["kpi_stats"].items()
            if loader.kpi_domain(k) == domain
        ]
        if not domain_kpis:
            continue
        st.markdown(f"**{domain}**")
        # worst first
        domain_kpis.sort(
            key=lambda x: (
                x[1]["deviation_pct"] if x[1]["direction"] == "higher_is_better"
                else -x[1]["deviation_pct"]
            )
        )
        for kpi, info in domain_kpis:
            dev   = info["deviation_pct"]
            sev   = info["severity"]
            color = _BADGE_COLORS.get(sev, "#2ca02c")
            bar_w = min(abs(dev) / 50 * 100, 100)
            sign  = "↓" if dev < 0 else "↑"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
                f'<div style="width:170px;font-size:0.79rem;opacity:0.85">'
                f'{loader.kpi_display(kpi)}</div>'
                f'<div style="flex:1;background:rgba(128,128,128,0.12);border-radius:3px;height:8px">'
                f'<div style="width:{bar_w:.0f}%;height:8px;background:{color};border-radius:3px">'
                f'</div></div>'
                f'<div style="min-width:52px;text-align:right;font-size:0.82rem;'
                f'font-weight:600;color:{color}">{sign}{abs(dev):.1f}%</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def page_entity_health(anomalies: list[Anomaly], domain_windows: dict | None = None):
    st.title("Team Scorecard")
    st.caption("Holistic KPI performance at Region · Branch · RM level.")

    loader = get_loader()
    dw = domain_windows or {
        "Broking": {"analysis": 5,  "baseline": 60},
        "Wealth":  {"analysis": 14, "baseline": 90},
        "Clients": {"analysis": 30, "baseline": 180},
    }

    ctrl1, ctrl2 = st.columns([2, 2])
    with ctrl1:
        level_label = st.radio(
            "Hierarchy level", ["Region", "Branch", "RM"],
            horizontal=True, key="eh_level",
        )
    level_key = {"Region": "region", "Branch": "branch", "RM": "rm_id"}[level_label]

    with ctrl2:
        if level_label != "RM":
            view = st.radio("View", ["Heat Map", "Leaderboard"], horizontal=True, key="eh_view")
        else:
            view = "Leaderboard"
            st.caption("Leaderboard view — 48 RMs, heat map not practical at this level")

    dw_tuple = tuple(
        (domain, v["analysis"], v["baseline"])
        for domain, v in sorted(dw.items())
    )

    with st.spinner("Computing entity health…"):
        entity_data = get_entity_health_data(id(loader), level_key, dw_tuple)

    if not entity_data:
        st.info("No data available for this level.")
        return

    # Build per-entity metadata
    entity_meta: dict[str, dict] = {}
    for entity, kpi_map in entity_data.items():
        kpi_stats: dict[str, dict] = {}
        severities: list[str]      = []
        worst_kpi:  str | None     = None
        worst_bad:  float          = 0.0
        worst_dev_pct: float       = 0.0

        for kpi, info in kpi_map.items():
            sev = _dev_severity(info["deviation_pct"], info["direction"])
            kpi_stats[kpi] = {**info, "severity": sev}
            severities.append(sev)
            bad = (
                -info["deviation_pct"] if info["direction"] == "higher_is_better"
                else info["deviation_pct"]
            )
            if bad > worst_bad:
                worst_bad     = bad
                worst_kpi     = kpi
                worst_dev_pct = info["deviation_pct"]

        badge = next(
            (s for s in ("Critical", "Warning", "Watch") if s in severities),
            "Healthy",
        )
        entity_meta[entity] = {
            "badge":         badge,
            "kpi_stats":     kpi_stats,
            "n_crit":        severities.count("Critical"),
            "n_warn":        severities.count("Warning"),
            "n_watch":       severities.count("Watch"),
            "n_ok":          severities.count("Healthy"),
            "worst_kpi":     worst_kpi,
            "worst_bad":     worst_bad,
            "worst_dev_pct": worst_dev_pct,
        }

    entity_order = sorted(
        entity_meta,
        key=lambda e: (_SEV_ORDER[entity_meta[e]["badge"]], -entity_meta[e]["worst_bad"]),
    )
    kpi_order = [
        k for grp in _EH_KPI_BY_DOMAIN.values() for k in grp
        if any(k in entity_data[e] for e in entity_data)
    ]

    if view == "Heat Map":
        st.subheader(f"KPI Heat Map — {level_label} level")
        st.caption(
            "**Red** = below baseline (bad for revenue/clients), **green** = above. "
            "Redemptions inverted so red = high redemptions = bad."
        )
        _eh_render_heatmap(entity_order, kpi_order, entity_data, loader)
    else:
        st.subheader(f"Performance Leaderboard — {level_label} level")
        st.caption("Sorted worst → best by Critical KPI count, then largest deviation.")
        _eh_render_leaderboard(entity_order, entity_meta, loader)

    st.divider()
    st.subheader("Entity Deep Dive")
    selected = st.selectbox(
        "Select entity to inspect",
        entity_order,
        key="eh_selected",
        format_func=lambda e: f"{e}  [{entity_meta[e]['badge']}]",
    )
    if selected:
        _eh_render_profile(selected, entity_meta[selected], loader)


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
# Contribution breakdown helpers  (Option A — scorecard, Option C — alerts)
# ─────────────────────────────────────────────────────────────────────────────

def _level_breakdown_rows(
    loader: DataLoader,
    kpi: str,
    level: str,
    filters: dict,
    analysis_start: date,
    baseline_start: date,
    baseline_end: date,
) -> list[dict]:
    """
    Per-dimension contribution rows at `level` (e.g. 'region').
    Each row: {dim, deviation_pct, contribution_pct, variance}.
    Sorted by |variance| descending so biggest contributor is first.
    """
    if level not in HIERARCHY:
        return []

    idx        = HIERARCHY.index(level)
    group_cols = HIERARCHY[: idx + 1]
    df         = loader.aggregate(group_by=group_cols)
    if kpi not in df.columns or df.empty:
        return []

    # Apply parent-dimension filters (e.g. restrict to South region only)
    for col, val in filters.items():
        if col in df.columns and val:
            df = df[df[col] == val]

    df_act  = df[df["date"] >= pd.Timestamp(analysis_start)]
    df_base = df[
        (df["date"] >= pd.Timestamp(baseline_start))
        & (df["date"] <= pd.Timestamp(baseline_end))
    ]

    if df_act.empty or df_base.empty:
        return []

    # Daily average per dimension value (mean normalises for different window lengths)
    act    = df_act.groupby(level)[kpi].mean()
    base   = df_base.groupby(level)[kpi].mean()
    common = act.index.intersection(base.index)
    if len(common) == 0:
        return []

    act, base = act[common], base[common]
    variance  = act - base

    direction = loader.kpi_direction(kpi)
    bad       = variance[variance < 0] if direction == "higher_is_better" else variance[variance > 0]
    total_bad = bad.abs().sum() if len(bad) > 0 else variance.abs().sum()

    rows: list[dict] = []
    for dim in common:
        dev_pct = (act[dim] - base[dim]) / abs(base[dim]) * 100 if base[dim] != 0 else 0.0
        contrib = abs(variance[dim]) / total_bad * 100 if total_bad != 0 else 0.0
        rows.append({
            "dim":              str(dim),
            "deviation_pct":   round(float(dev_pct),  1),
            "contribution_pct": round(float(contrib),  1),
            "variance":         float(variance[dim]),
        })

    rows.sort(key=lambda r: abs(r["variance"]), reverse=True)
    return rows


def _breakdown_rows_html(rows: list[dict], direction: str) -> str:
    """Render contribution rows as a compact HTML fragment (bars + deviation %)."""
    html = ""
    for r in rows:
        bar_w   = min(int(abs(r["contribution_pct"])), 100)
        is_bad  = (
            (r["deviation_pct"] < 0 and direction == "higher_is_better")
            or (r["deviation_pct"] > 0 and direction == "lower_is_better")
        )
        bar_col = (
            "#d62728" if is_bad and abs(r["deviation_pct"]) >= 20 else
            "#ff7f0e" if is_bad else
            "#2ca02c"
        )
        dev_col = "#d62728" if is_bad else "#2ca02c"
        sign    = "↓" if r["deviation_pct"] < 0 else "↑"
        html += (
            '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">'
            f'<div style="width:60px;font-size:0.71rem;opacity:0.80;overflow:hidden;'
            f'text-overflow:ellipsis;white-space:nowrap" title="{r["dim"]}">{r["dim"]}</div>'
            f'<div style="color:{dev_col};font-size:0.71rem;font-weight:600;'
            f'min-width:38px;text-align:right">{sign}{abs(r["deviation_pct"]):.0f}%</div>'
            '<div style="flex:1;background:rgba(128,128,128,0.18);border-radius:3px;'
            'height:5px;overflow:hidden">'
            f'<div style="width:{bar_w}%;height:5px;border-radius:3px;background:{bar_col}"></div>'
            '</div>'
            f'<div style="font-size:0.65rem;opacity:0.45;min-width:24px;text-align:right">'
            f'{r["contribution_pct"]:.0f}%</div>'
            '</div>'
        )
    return html


@st.cache_data(ttl=300)
def get_card_breakdown(_loader_id, kpi: str, aw: int, bw: int) -> list[dict]:
    """Region-level breakdown used by anomalous KPI cards (Option A). Cached 5 min."""
    loader  = get_loader()
    end     = loader.df["date"].max().date()
    a_start = end - timedelta(days=aw - 1)
    b_start = end - timedelta(days=bw + aw)
    b_end   = a_start - timedelta(days=1)
    return _level_breakdown_rows(loader, kpi, "region", {}, a_start, b_start, b_end)


@st.cache_data(ttl=300)
def get_alert_breakdown(
    _loader_id,
    kpi: str,
    aw: int,
    bw: int,
    anom_level: str,
    anom_dims_tuple: tuple,   # hashable: tuple(sorted(dimension_values.items()))
) -> tuple[list, list, str, str]:
    """
    Two-level ranked breakdown for an alert row (Option C).
    Returns (l1_rows[:3], l2_rows[:3], l1_label, l2_label).
    L1 = first level below the anomaly; L2 = sub-level of worst L1 contributor.
    """
    loader     = get_loader()
    dim_values = dict(anom_dims_tuple)
    end        = loader.df["date"].max().date()
    a_start    = end - timedelta(days=aw - 1)
    b_start    = end - timedelta(days=bw + aw)
    b_end      = a_start - timedelta(days=1)

    # Determine L1 level relative to where the anomaly was detected
    if anom_level == "firm" or anom_level not in HIERARCHY:
        l1_level   = "region"
        l1_filters: dict = {}
    elif anom_level == HIERARCHY[-1]:
        # Segment is the leaf level — nothing to drill into
        return [], [], "", ""
    else:
        h_idx      = HIERARCHY.index(anom_level)
        l1_level   = HIERARCHY[h_idx + 1]
        # Filters = all ancestors up to and including the anomaly's own level
        l1_filters = {k: v for k, v in dim_values.items() if k in HIERARCHY[: h_idx + 1]}

    l1_rows  = _level_breakdown_rows(loader, kpi, l1_level, l1_filters, a_start, b_start, b_end)
    l1_label = l1_level.replace("_", " ").title()

    # L2: sub-level of the worst L1 contributor
    l2_rows: list[dict] = []
    l2_label = ""
    if l1_rows:
        worst_dim = l1_rows[0]["dim"]
        l1_h_idx  = HIERARCHY.index(l1_level) if l1_level in HIERARCHY else -1
        if 0 <= l1_h_idx < len(HIERARCHY) - 1:
            l2_level   = HIERARCHY[l1_h_idx + 1]
            l2_filters = {**l1_filters, l1_level: worst_dim}
            l2_rows    = _level_breakdown_rows(loader, kpi, l2_level, l2_filters, a_start, b_start, b_end)
            l2_label   = f"{worst_dim} → {l2_level.replace('_', ' ').title()}"

    return l1_rows[:3], l2_rows[:3], l1_label, l2_label


# ─────────────────────────────────────────────────────────────────────────────
# PAGE 5 — Ask Claude (KPI Intelligence chat)
# ─────────────────────────────────────────────────────────────────────────────

def _build_kpi_context(anomalies: list, domain: str, domain_windows: dict | None = None) -> str:
    """Format pre-computed anomalies + trends as context for the system prompt."""
    today = date.today().isoformat()
    dw = domain_windows or {}
    # Use the dashboard's configured analysis window; fall back to 7 days
    analysis_days = dw.get(domain if domain != "All" else "Broking", {}).get("analysis", 7)
    filtered = [
        a for a in anomalies
        if domain == "All" or getattr(a, "domain", None) == domain
    ]

    lines = [f"## Live KPI Snapshot — {today} (analysis window: {analysis_days} days)"]

    try:
        loader = get_loader()
        targets = loader.config.get("targets", {})
    except Exception:
        loader = None
        targets = {}

    if not filtered:
        lines.append("\n### No anomalies detected in current window.")
    else:
        lines.append(f"\n### Anomalies detected ({len(filtered)} total, ranked by severity):")
        for a in filtered[:15]:
            dim = a.dimension_label()
            dim_str = f" [{dim}]" if dim and dim.lower() not in ("all", "firm") else ""
            t = targets.get(a.kpi, {})
            target_str = ""
            if t.get("monthly_growth_pct") is not None:
                target_str = f", target: {t['monthly_growth_pct']:+.0f}% monthly growth"
            lines.append(
                f"- **{a.kpi_name}**{dim_str} ({a.domain}): "
                f"{a.deviation_pct:+.1f}% vs baseline — {a.severity} "
                f"(actual {a.actual_value:.1f}, expected {a.expected_value:.1f}{target_str})"
            )

    if loader is None:
        lines.append("\nAnswer using anomaly data above.")
        return "\n".join(lines)

    try:
        start_dt, end_dt = loader.last_n_days(analysis_days)

        # Firm-level 7-day trend: all domain KPIs + correlates of anomalous ones
        domain_kpis = (
            loader.domain_kpis(domain) if domain != "All"
            else loader.domain_kpis("Broking") + loader.domain_kpis("Wealth") + loader.domain_kpis("Clients")
        )
        correlate_kpis = []
        for a in filtered[:8]:
            if getattr(a, "dimension_level", "firm") in ("firm", "all", ""):
                correlate_kpis.extend(loader.kpi_correlates(a.kpi))
        all_firm_kpis = list(dict.fromkeys(domain_kpis + correlate_kpis))

        if all_firm_kpis:
            df = loader.firm_daily(date_range=(start_dt, end_dt))
            available = [k for k in all_firm_kpis if k in df.columns]
            if available:
                # Week-over-week summary — pre-computed so Claude doesn't need to derive it
                first_row = df.iloc[0]
                last_row  = df.iloc[-1]
                improved, declined = [], []
                for k in available:
                    if first_row[k] == 0:
                        continue
                    chg = (last_row[k] - first_row[k]) / abs(first_row[k]) * 100
                    direction = loader.kpi_direction(k)
                    is_good = (chg > 0 and direction == "higher_is_better") or \
                              (chg < 0 and direction == "lower_is_better")
                    entry = f"{loader.kpi_display(k)} ({chg:+.1f}%)"
                    (improved if is_good else declined).append(entry)

                lines.append("\n### Week-to-date change (first vs last day of window):")
                lines.append("Improved:  " + (", ".join(improved)  if improved  else "none"))
                lines.append("Declined:  " + (", ".join(declined)  if declined  else "none"))

                lines.append("\n### Last 7 days — daily values (firm-wide):")
                lines.append("Date       | " + " | ".join(loader.kpi_display(k) for k in available))
                lines.append("-----------|" + "|".join("---------" for _ in available))
                for _, row in df.iterrows():
                    vals = " | ".join(f"{row[k]:>9.1f}" for k in available)
                    lines.append(f"{row['date'].date()} | {vals}")

        # Market returns — always include for "is it market-driven?" questions
        mkt = loader.market
        if not mkt.empty:
            mkt_recent = mkt[
                (mkt["date"] >= pd.Timestamp(start_dt)) &
                (mkt["date"] <= pd.Timestamp(end_dt))
            ].copy()
            if not mkt_recent.empty:
                lines.append("\n### Nifty daily returns (last 7 days):")
                for _, row in mkt_recent.iterrows():
                    lines.append(f"- {row['date'].date()}: {row['nifty_return']:+.2f}%")

        # Regional summary — all domain KPIs aggregated by region over the window
        # Answers "which region is highest/lowest?" without tool calls
        if domain_kpis:
            try:
                df_region = loader.aggregate(
                    group_by=["region"],
                    date_range=(start_dt, end_dt),
                )
                reg_available = [k for k in domain_kpis if k in df_region.columns]
                if reg_available and "region" in df_region.columns:
                    region_agg = (
                        df_region.groupby("region")[reg_available]
                        .mean()
                        .reset_index()
                        .sort_values("region")
                    )
                    lines.append(f"\n### Regional breakdown — {analysis_days}-day avg (all {domain} KPIs):")
                    lines.append("Region     | " + " | ".join(loader.kpi_display(k) for k in reg_available))
                    lines.append("-----------|" + "|".join("---------" for _ in reg_available))
                    for _, row in region_agg.iterrows():
                        vals = " | ".join(f"{row[k]:>9.1f}" for k in reg_available)
                        lines.append(f"{str(row['region']):<10} | {vals}")
            except Exception:
                pass

        # Targets summary
        if targets and domain_kpis:
            target_lines = []
            for k in domain_kpis:
                t = targets.get(k, {})
                if not t:
                    continue
                parts = []
                if t.get("monthly_growth_pct") is not None:
                    parts.append(f"monthly growth target: {t['monthly_growth_pct']:+.0f}%")
                for key in ("annual_target_lakhs", "annual_target_count", "annual_target_pct"):
                    if t.get(key) is not None:
                        label = key.replace("annual_target_", "annual target (")  + ")"
                        parts.append(f"{label}: {t[key]:,.0f}")
                if parts:
                    target_lines.append(f"- {loader.kpi_display(k)}: {'; '.join(parts)}")
            if target_lines:
                lines.append("\n### KPI targets (from leadership plan):")
                lines.extend(target_lines)

    except Exception:
        pass  # enrichment is best-effort; anomaly list still useful

    lines.append(
        "\nAnswer using this data directly. Only call tools if the user asks for "
        "branch-level or RM-level breakdowns not shown above."
    )
    return "\n".join(lines)


_CHAT_MODEL   = "claude-haiku-4-5"
_CHAT_BETA    = "mcp-client-2025-04-04"
_CHAT_MAX_TOK = 8096

_SUGGESTED_QUESTIONS = {
    "All": [
        "What's wrong today?",
        "Why are net flows down?",
        "Which KPIs improved this week?",
    ],
    "Broking": [
        "Why is equity volume down?",
        "How is brokerage revenue trending this month?",
        "Which branches are underperforming on Broking KPIs?",
    ],
    "Wealth": [
        "Why are net flows negative?",
        "Is AUM growing or declining?",
        "Which regions have the highest redemption rate?",
    ],
    "Clients": [
        "Why is the activation rate low?",
        "Which regions are opening the most new accounts?",
        "How is client acquisition trending vs baseline?",
    ],
}

_DOMAIN_ADDENDUM = {
    "Broking": "\nFocus this session on Broking KPIs: equity volume, derivatives volume, brokerage revenue, active clients.",
    "Wealth":  "\nFocus this session on Wealth KPIs: AUM, net flows, redemption rate, SIP book.",
    "Clients": "\nFocus this session on Client KPIs: new accounts, activation rate, churn rate.",
}

_CHAT_SYSTEM = (
    "You are a senior BI analyst at a broking and wealth management firm. "
    "You have access to live KPI data via tools. When the user asks about KPI performance, "
    "anomalies, or trends, always call the relevant tools to ground your answer in actual data. "
    "Keep responses concise and business-focused. Use INR crores for currency where relevant.\n\n"
    "IMPORTANT: Use a maximum of 3 tool calls per response. "
    "Retrieve the most relevant data first, then give your best answer immediately — "
    "do not chain further tool calls to investigate correlations or chase root causes. "
    "If you cannot fully explain the cause in 3 calls, state what the data shows and "
    "note what additional investigation would be needed."
)


def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, "") or os.environ.get(key, default)
    except Exception:
        return os.environ.get(key, default)


def _get_anthropic_client():
    return _anthropic.Anthropic(api_key=_get_secret("ANTHROPIC_API_KEY"))


def _mcp_reachable(mcp_url: str) -> bool:
    """Quick health check — cached in session state for the lifetime of the browser tab."""
    if "mcp_reachable" in st.session_state:
        return st.session_state.mcp_reachable
    try:
        import urllib.request
        health_url = mcp_url.replace("/mcp", "/health")
        urllib.request.urlopen(health_url, timeout=3)
        reachable = True
    except Exception:
        reachable = False
    st.session_state.mcp_reachable = reachable
    return reachable


def page_ask_claude(anomalies: list | None = None, domain_windows: dict | None = None):
    st.title("Ask Claude")
    st.caption("Chat with Claude over your live KPI data via MCP.")

    if not _ANTHROPIC_AVAILABLE:
        st.error("The `anthropic` package is not installed. Run `pip install anthropic` and restart.")
        return

    mcp_url = _get_secret("MCP_SERVER_URL")
    if not _get_secret("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY not set. Add it in the Render dashboard environment variables.")
        return

    # Domain filter
    domain = st.radio(
        "Domain focus",
        ["All", "Broking", "Wealth", "Clients"],
        horizontal=True,
        key="chat_domain",
    )

    # Suggested questions — update with domain
    st.markdown("**Suggested questions**")
    sq_cols = st.columns(3)
    for i, (col, q) in enumerate(zip(sq_cols, _SUGGESTED_QUESTIONS.get(domain, _SUGGESTED_QUESTIONS["All"]))):
        with col:
            if st.button(q, key=f"chat_sq_{domain}_{i}", use_container_width=True):
                st.session_state.chat_pending = q

    st.divider()

    # Session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "chat_pending" not in st.session_state:
        st.session_state.chat_pending = None

    # Display history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            if msg.get("tools"):
                pills = " &nbsp; ".join(
                    f'<span style="font-size:11px;padding:2px 10px;border-radius:20px;'
                    f'background:rgba(128,128,128,0.1);border:1px solid rgba(128,128,128,0.2)">'
                    f'⚙ {t}</span>'
                    for t in msg["tools"]
                )
                st.markdown(
                    f'<div style="margin-bottom:6px">{pills}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(msg["content"])

    user_input = st.chat_input("Ask about any KPI, region, or anomaly…", key="chat_input")
    if st.session_state.chat_pending:
        user_input = st.session_state.chat_pending
        st.session_state.chat_pending = None

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        kpi_context   = _build_kpi_context(anomalies or [], domain, domain_windows)
        _using_mcp    = bool(mcp_url) and _mcp_reachable(mcp_url)
        no_tools_note = (
            "\n\nNote: Live tool access is unavailable in this session. "
            "Answer using only the KPI snapshot above — do not attempt to call any tools."
            if not _using_mcp else ""
        )
        system_prompt = _CHAT_SYSTEM + _DOMAIN_ADDENDUM.get(domain, "") + "\n\n" + kpi_context + no_tools_note
        api_messages  = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.chat_history
        ]

        with st.chat_message("assistant"):
            spinner_slot = st.empty()
            tools_slot   = st.empty()
            text_slot    = st.empty()

            tool_names  = []
            reply_parts = []
            start       = _time.time()

            def _pill_html(names):
                pills = " &nbsp; ".join(
                    f'<span style="font-size:11px;padding:2px 10px;border-radius:20px;'
                    f'background:rgba(128,128,128,0.1);border:1px solid rgba(128,128,128,0.2)">'
                    f'⚙ {t}</span>'
                    for t in names
                )
                return f'<div style="margin-bottom:6px">{pills}</div>'

            def _stream_call(with_mcp: bool):
                kwargs = dict(
                    model=_CHAT_MODEL,
                    max_tokens=_CHAT_MAX_TOK,
                    system=system_prompt,
                    messages=api_messages,
                )
                if with_mcp:
                    kwargs["extra_headers"] = {"anthropic-beta": _CHAT_BETA}
                    kwargs["extra_body"] = {"mcp_servers": [{"type": "url", "url": mcp_url, "name": "kpi-monitor"}]}
                return client.messages.stream(**kwargs)

            def _run_stream(stream):
                for event in stream:
                    if event.type == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", None) == "tool_use":
                            tool_names.append(block.name)
                            tools_slot.markdown(_pill_html(tool_names), unsafe_allow_html=True)
                    elif event.type == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta and getattr(delta, "type", None) == "text_delta":
                            reply_parts.append(delta.text)
                            text_slot.markdown("".join(reply_parts) + "▌")

            try:
                client = _get_anthropic_client()
                with spinner_slot.status("Thinking…", expanded=False):
                    with _stream_call(with_mcp=_using_mcp) as stream:
                        _run_stream(stream)

                reply = "".join(reply_parts).strip()
                if not reply:
                    final = stream.get_final_message()
                    reply = " ".join(
                        b.text for b in final.content if b.type == "text"
                    ).strip() or "_No text returned._"

            except Exception as exc:
                err_str = str(exc).lower()
                if _using_mcp and "connection" in err_str:
                    tool_names = []
                    reply_parts = []
                    try:
                        with spinner_slot.status("MCP unavailable — answering from context…", expanded=False):
                            with _stream_call(with_mcp=False) as stream:
                                _run_stream(stream)
                        reply = "".join(reply_parts).strip() or "_No text returned._"
                    except Exception as exc2:
                        reply = f"⚠ Error: `{exc2}`"
                else:
                    tool_names = []
                    reply = f"⚠ Error: `{exc}`"

            elapsed = int(_time.time() - start)
            spinner_slot.empty()
            if tool_names:
                tools_slot.markdown(_pill_html(tool_names), unsafe_allow_html=True)
            else:
                tools_slot.empty()
            text_slot.markdown(reply)
            st.caption(f"_{elapsed}s_")

        st.session_state.chat_history.append({
            "role": "assistant",
            "content": reply,
            "tools": tool_names,
        })

    with st.sidebar:
        if st.button("Clear conversation", key="chat_clear"):
            st.session_state.chat_history = []
            st.session_state.pop("mcp_reachable", None)
            st.rerun()


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
        page_anomalies(anomalies, domain_windows)
    elif page == "Team Scorecard":
        page_entity_health(anomalies, domain_windows)
    elif page == "Investigate Anomaly":
        page_investigate(anomalies, domain_windows, regime)
    elif page == "Ask Claude":
        page_ask_claude(anomalies, domain_windows)
    elif page == "About":
        page_about()


if __name__ == "__main__":
    main()
