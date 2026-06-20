"""
KPI Monitor MCP Server

Exposes the KPI monitoring system to Claude as Tools, Resources, and Prompts
via the Model Context Protocol (stdio transport).

Run directly:   python mcp_server.py
Register in Claude Code: add to .claude/settings.json (see bottom of file)
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

# Ensure project root is on the path when launched from any directory
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from kpi_monitor.data_loader import DataLoader, HIERARCHY
from kpi_monitor.anomaly_detector import AnomalyDetector, MONITORABLE_KPIS, Anomaly

# ── Singleton data objects (loaded once, reused across requests) ───────────────
_loader: DataLoader | None = None
_detector: AnomalyDetector | None = None


def _get_loader() -> DataLoader:
    global _loader
    if _loader is None:
        _loader = DataLoader()
    return _loader


def _get_detector() -> AnomalyDetector:
    global _detector
    if _detector is None:
        _detector = AnomalyDetector(_get_loader())
    return _detector


# ── Helpers ───────────────────────────────────────────────────────────────────

def _anomaly_to_dict(a: Anomaly) -> dict:
    return {
        "kpi": a.kpi,
        "kpi_name": a.kpi_name,
        "domain": a.domain,
        "severity": a.severity,
        "severity_score": a.severity_score,
        "detection_method": a.detection_method,
        "dimension_level": a.dimension_level,
        "dimension_label": a.dimension_label(),
        "dimension_values": a.dimension_values,
        "analysis_period": f"{a.analysis_start} → {a.analysis_end}",
        "actual_value": round(a.actual_value, 2),
        "expected_value": round(a.expected_value, 2),
        "deviation_pct": round(a.deviation_pct, 1),
        "z_score": round(a.z_score, 2),
        "direction": a.direction,
        "unit": a.unit,
        "summary": a.summary,
    }


def _fmt_json(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


# ── Server setup ──────────────────────────────────────────────────────────────
app = Server("kpi-monitor")


# ═══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="detect_anomalies",
            description=(
                "Run anomaly detection across firm KPIs. Applies three methods: "
                "rolling z-score (statistical deviation), target breach, and trend reversal. "
                "Returns anomalies sorted by severity (Critical first). "
                "Optionally filter by KPI names, hierarchy levels, or number of analysis days."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kpi_list": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "KPI keys to check. If omitted, all monitorable KPIs are checked. "
                            f"Valid values: {MONITORABLE_KPIS}"
                        ),
                    },
                    "levels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Hierarchy levels to check. Defaults to ['firm','region','branch','rm_id']. "
                            "Valid values: firm, region, branch, rm_id, segment"
                        ),
                    },
                    "analysis_window": {
                        "type": "integer",
                        "default": 14,
                        "description": "Number of recent days to treat as the analysis window.",
                    },
                    "baseline_window": {
                        "type": "integer",
                        "default": 90,
                        "description": "Number of historical days used to compute the baseline.",
                    },
                    "severity_filter": {
                        "type": "string",
                        "enum": ["Critical", "Warning", "Watch", "all"],
                        "default": "all",
                        "description": "Return only anomalies at or above this severity level.",
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 20,
                        "description": "Maximum number of anomalies to return.",
                    },
                },
            },
        ),
        types.Tool(
            name="get_kpi_data",
            description=(
                "Query time-series KPI data for a specific KPI, optionally filtered by "
                "hierarchy dimension (region, branch, rm_id, segment). "
                "Returns daily values as a JSON array."
            ),
            inputSchema={
                "type": "object",
                "required": ["kpi"],
                "properties": {
                    "kpi": {
                        "type": "string",
                        "description": (
                            "KPI key to query. "
                            f"Valid values: {MONITORABLE_KPIS + ['nifty_return']}"
                        ),
                    },
                    "days": {
                        "type": "integer",
                        "default": 30,
                        "description": "Number of recent days to return.",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": ["firm", "region", "branch", "rm_id", "segment"],
                        "default": "firm",
                        "description": "Dimension to aggregate by.",
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "Optional dimension filters, e.g. {\"region\": \"South\", \"branch\": \"Chennai\"}. "
                            "Valid filter keys: region, branch, rm_id, segment."
                        ),
                    },
                },
            },
        ),
        types.Tool(
            name="get_kpi_summary",
            description=(
                "Get a statistical summary for one or more KPIs in a SINGLE call: recent "
                "average, baseline average, deviation %, trend direction, and metadata. "
                "PREFER this over multiple get_kpi_data calls when asked how a segment or "
                "region is doing 'across all KPIs' — pass `filters` (e.g. "
                "{\"segment\": \"HNI\"}) to summarise every KPI for that slice at once."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "kpis": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "KPI keys to summarise. If omitted, returns summary for all firm KPIs."
                        ),
                    },
                    "filters": {
                        "type": "object",
                        "description": (
                            "Optional dimension filter to scope the summary to a slice, e.g. "
                            "{\"segment\": \"HNI\"}, {\"region\": \"South\"}, {\"branch\": \"...\"}. "
                            "Returns all requested KPIs for that slice in one call. Valid keys: "
                            "region, branch, rm_id, segment."
                        ),
                    },
                    "recent_days": {
                        "type": "integer",
                        "default": 14,
                        "description": "Number of recent days to use as the 'current' window.",
                    },
                    "baseline_days": {
                        "type": "integer",
                        "default": 90,
                        "description": "Number of prior days to use as the baseline.",
                    },
                },
            },
        ),
        types.Tool(
            name="list_kpis",
            description=(
                "List all available KPIs with their metadata: display name, domain, unit, "
                "direction (higher_is_better / lower_is_better), and correlated KPIs. "
                "Use this to discover valid KPI keys before calling other tools."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "enum": ["Broking", "Wealth", "Clients", "Market", "all"],
                        "default": "all",
                        "description": "Filter KPIs by domain.",
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "detect_anomalies":
            result = _tool_detect_anomalies(arguments)
        elif name == "get_kpi_data":
            result = _tool_get_kpi_data(arguments)
        elif name == "get_kpi_summary":
            result = _tool_get_kpi_summary(arguments)
        elif name == "list_kpis":
            result = _tool_list_kpis(arguments)
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        result = {"error": str(exc)}

    return [types.TextContent(type="text", text=_fmt_json(result))]


# ── Tool implementations ───────────────────────────────────────────────────────

def _tool_detect_anomalies(args: dict) -> dict:
    detector = _get_detector()

    kpi_list = args.get("kpi_list") or None
    levels   = args.get("levels") or None
    analysis_window = int(args.get("analysis_window", 14))
    baseline_window = int(args.get("baseline_window", 90))
    severity_filter = args.get("severity_filter", "all")
    max_results     = int(args.get("max_results", 20))

    anomalies = detector.detect_all(
        analysis_window=analysis_window,
        baseline_window=baseline_window,
        levels=levels,
        kpi_list=kpi_list,
    )

    severity_rank = {"Critical": 3, "Warning": 2, "Watch": 1}
    if severity_filter != "all":
        min_score = severity_rank.get(severity_filter, 1)
        anomalies = [a for a in anomalies if a.severity_score >= min_score]

    anomalies = anomalies[:max_results]

    loader = _get_loader()
    data_end = loader.df["date"].max().date()

    return {
        "data_as_of": str(data_end),
        "analysis_window_days": analysis_window,
        "baseline_window_days": baseline_window,
        "total_anomalies_found": len(anomalies),
        "severity_breakdown": {
            "Critical": sum(1 for a in anomalies if a.severity == "Critical"),
            "Warning":  sum(1 for a in anomalies if a.severity == "Warning"),
            "Watch":    sum(1 for a in anomalies if a.severity == "Watch"),
        },
        "anomalies": [_anomaly_to_dict(a) for a in anomalies],
    }


# Cap rows returned to the model so a fine-grained query can't blow the
# context window (segment/RM breakdowns can be tens of thousands of daily rows).
_MAX_DATA_ROWS = 400


def _tool_get_kpi_data(args: dict) -> dict:
    kpi      = args["kpi"]
    days     = int(args.get("days", 30))
    group_by = args.get("group_by", "firm")
    filters  = args.get("filters") or {}

    loader = _get_loader()
    date_range = loader.last_n_days(days)

    if group_by == "firm":
        df = loader.firm_daily(date_range=date_range)
        cols = ["date", kpi]
    else:
        # Group by ONLY the requested dimension (not the full hierarchy path),
        # so "by segment" returns a clean per-segment rollup. Use `filters` to
        # scope to a parent first (e.g. filters={"region": "South"}, group_by="branch").
        df   = loader.aggregate(group_by=[group_by], date_range=date_range, filters=filters)
        cols = ["date", group_by, kpi]

    if kpi not in df.columns:
        return {"error": f"KPI '{kpi}' not found in data. Valid KPIs: {list(loader.kpis.keys())}"}

    df = df[cols].sort_values("date")

    # If the daily breakdown is too large, collapse the date axis to a
    # period-average per dimension value — bounded and still answers
    # "which segment / region / branch is worst" questions.
    note = None
    aggregated = False
    if len(df) > _MAX_DATA_ROWS and group_by != "firm":
        agg_fn = "mean" if kpi == "activation_rate" else "mean"
        df = (
            df.groupby(group_by, as_index=False)[kpi].agg(agg_fn)
              .sort_values(kpi, ascending=False)
        )
        df.insert(0, "period", f"{date_range[0]} to {date_range[1]} (daily avg)")
        aggregated = True
        note = (
            f"Daily breakdown exceeded {_MAX_DATA_ROWS} rows; returning the "
            f"per-{group_by} daily-average over the period instead."
        )

    # Final safety cap even after aggregation (e.g. very many RMs)
    truncated = len(df) > _MAX_DATA_ROWS
    if truncated:
        df = df.head(_MAX_DATA_ROWS)

    if "date" in df.columns:
        df["date"] = df["date"].astype(str)

    kpi_meta = loader.kpis.get(kpi, {})
    return {
        "kpi": kpi,
        "kpi_name": kpi_meta.get("display_name", kpi),
        "domain": kpi_meta.get("domain", ""),
        "unit": kpi_meta.get("unit", ""),
        "direction": kpi_meta.get("direction", "higher_is_better"),
        "date_range": {"from": str(date_range[0]), "to": str(date_range[1])},
        "group_by": group_by,
        "filters": filters,
        "aggregated_over_period": aggregated,
        "row_count": len(df),
        "truncated": truncated,
        "note": note,
        "rows": df.to_dict(orient="records"),
    }


def _tool_get_kpi_summary(args: dict) -> dict:
    loader = _get_loader()

    kpis         = args.get("kpis") or loader.firm_kpis()
    recent_days  = int(args.get("recent_days", 14))
    baseline_days = int(args.get("baseline_days", 90))
    filters      = args.get("filters") or {}

    recent_range   = loader.last_n_days(recent_days)
    baseline_range = loader.prior_n_days(baseline_days, offset=recent_days)

    # When a filter is supplied (e.g. {"segment": "HNI"} or {"region": "South"}),
    # summarise that slice across ALL requested KPIs in a single call — avoids
    # fanning out into one get_kpi_data call per KPI.
    if filters:
        df_recent   = loader.aggregate(date_range=recent_range,   filters=filters)
        df_baseline = loader.aggregate(date_range=baseline_range, filters=filters)
    else:
        df_recent   = loader.firm_daily(date_range=recent_range)
        df_baseline = loader.firm_daily(date_range=baseline_range)

    summaries = []
    for kpi in kpis:
        if kpi not in df_recent.columns:
            continue
        meta = loader.kpis.get(kpi, {})
        recent_avg   = float(df_recent[kpi].mean())
        baseline_avg = float(df_baseline[kpi].mean()) if kpi in df_baseline.columns else None
        dev_pct = (
            (recent_avg - baseline_avg) / abs(baseline_avg) * 100
            if baseline_avg else None
        )
        direction = meta.get("direction", "higher_is_better")
        if dev_pct is not None:
            status = (
                "improving" if (dev_pct > 0 and direction == "higher_is_better") or
                               (dev_pct < 0 and direction == "lower_is_better")
                else "declining"
            )
        else:
            status = "unknown"

        summaries.append({
            "kpi": kpi,
            "kpi_name": meta.get("display_name", kpi),
            "domain": meta.get("domain", ""),
            "unit": meta.get("unit", ""),
            "direction": direction,
            "recent_avg": round(recent_avg, 2),
            "baseline_avg": round(baseline_avg, 2) if baseline_avg is not None else None,
            "deviation_pct": round(dev_pct, 1) if dev_pct is not None else None,
            "status": status,
            "correlates": meta.get("correlates", []),
        })

    return {
        "recent_window": f"Last {recent_days} days ({recent_range[0]} → {recent_range[1]})",
        "baseline_window": f"Prior {baseline_days} days ({baseline_range[0]} → {baseline_range[1]})",
        "filters": filters,
        "scope": "firm-wide" if not filters else ", ".join(f"{k}={v}" for k, v in filters.items()),
        "kpi_count": len(summaries),
        "summaries": summaries,
    }


def _tool_list_kpis(args: dict) -> dict:
    loader = _get_loader()
    domain_filter = args.get("domain", "all")

    kpi_list = []
    for key, meta in loader.kpis.items():
        if domain_filter != "all" and meta.get("domain") != domain_filter:
            continue
        kpi_list.append({
            "key": key,
            "display_name": meta.get("display_name", key),
            "domain": meta.get("domain", ""),
            "unit": meta.get("unit", ""),
            "direction": meta.get("direction", ""),
            "description": meta.get("description", ""),
            "correlates": meta.get("correlates", []),
            "monitorable": key in MONITORABLE_KPIS,
        })

    domains = sorted({k["domain"] for k in kpi_list})
    return {
        "total": len(kpi_list),
        "domains": domains,
        "hierarchy_levels": HIERARCHY,
        "kpis": kpi_list,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RESOURCES
# ═══════════════════════════════════════════════════════════════════════════════

@app.list_resources()
async def list_resources() -> list[types.Resource]:
    return [
        types.Resource(
            uri="kpi://config",
            name="KPI Configuration",
            description=(
                "Full KPI registry: all KPI definitions, domains, thresholds, targets, "
                "hierarchy levels, and regional dimensions from kpi_config.yaml."
            ),
            mimeType="application/yaml",
        ),
        types.Resource(
            uri="kpi://kpis",
            name="KPI Metadata (JSON)",
            description=(
                "All KPI keys with display names, domains, units, directions, "
                "and correlations — machine-readable JSON."
            ),
            mimeType="application/json",
        ),
        types.Resource(
            uri="kpi://anomalies/recent",
            name="Recent Anomalies",
            description=(
                "Live anomaly detection results for the last 14-day window across all "
                "firm KPIs and hierarchy levels (Critical + Warning only). "
                "Refreshed on every read."
            ),
            mimeType="application/json",
        ),
        types.Resource(
            uri="kpi://data/latest",
            name="Latest KPI Snapshot",
            description=(
                "Firm-wide daily KPI values for the last 30 days — all KPIs in one table."
            ),
            mimeType="application/json",
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    if uri == "kpi://config":
        config_path = ROOT / "kpi_config.yaml"
        return config_path.read_text()

    elif uri == "kpi://kpis":
        loader = _get_loader()
        result = _tool_list_kpis({"domain": "all"})
        return _fmt_json(result)

    elif uri == "kpi://anomalies/recent":
        result = _tool_detect_anomalies({
            "analysis_window": 14,
            "baseline_window": 90,
            "severity_filter": "Warning",
            "max_results": 50,
        })
        return _fmt_json(result)

    elif uri == "kpi://data/latest":
        loader = _get_loader()
        date_range = loader.last_n_days(30)
        df = loader.firm_daily(date_range=date_range)
        df["date"] = df["date"].astype(str)
        return _fmt_json({
            "date_range": {"from": str(date_range[0]), "to": str(date_range[1])},
            "rows": df.to_dict(orient="records"),
        })

    else:
        raise ValueError(f"Unknown resource URI: {uri}")


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.list_prompts()
async def list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="daily_kpi_briefing",
            description=(
                "Generate a concise daily KPI briefing for the head of BI at a broking/wealth firm. "
                "Runs anomaly detection and summarises what needs attention today."
            ),
            arguments=[
                types.PromptArgument(
                    name="focus_domain",
                    description="Optional: focus on one domain — Broking, Wealth, or Clients. Leave blank for firm-wide.",
                    required=False,
                ),
                types.PromptArgument(
                    name="severity_threshold",
                    description="Minimum severity to include: Critical, Warning, or Watch. Default: Warning.",
                    required=False,
                ),
            ],
        ),
        types.Prompt(
            name="investigate_anomaly",
            description=(
                "Deep-dive investigation prompt for a specific KPI anomaly. "
                "Provides structured analysis: root-cause hypotheses, correlated KPIs to check, "
                "and recommended actions."
            ),
            arguments=[
                types.PromptArgument(
                    name="kpi",
                    description="KPI key to investigate (e.g. brokerage_revenue, aum, net_flows).",
                    required=True,
                ),
                types.PromptArgument(
                    name="dimension",
                    description="Optional dimension context, e.g. 'South region' or 'Chennai branch'.",
                    required=False,
                ),
                types.PromptArgument(
                    name="anomaly_description",
                    description="Brief description of the anomaly observed (e.g. 'down 22% vs baseline, Critical z-score').",
                    required=False,
                ),
            ],
        ),
        types.Prompt(
            name="kpi_performance_review",
            description=(
                "Structured performance review prompt for a set of KPIs over a period. "
                "Suitable for weekly/monthly management review preparation."
            ),
            arguments=[
                types.PromptArgument(
                    name="domain",
                    description="Domain to review: Broking, Wealth, Clients, or all.",
                    required=False,
                ),
                types.PromptArgument(
                    name="period",
                    description="Review period description, e.g. 'last 30 days' or 'June 2025'.",
                    required=False,
                ),
            ],
        ),
    ]


@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
    args = arguments or {}

    if name == "daily_kpi_briefing":
        focus_domain      = args.get("focus_domain", "all domains")
        severity_threshold = args.get("severity_threshold", "Warning")

        loader   = _get_loader()
        data_end = loader.df["date"].max().date()
        detector = _get_detector()

        kpi_list = None
        if focus_domain and focus_domain not in ("all", "all domains"):
            kpi_list = loader.domain_kpis(focus_domain)

        anomalies = detector.detect_all(
            analysis_window=14,
            kpi_list=kpi_list,
        )
        sev_rank = {"Critical": 3, "Warning": 2, "Watch": 1}
        min_score = sev_rank.get(severity_threshold, 2)
        anomalies = [a for a in anomalies if a.severity_score >= min_score]

        anomaly_json = _fmt_json([_anomaly_to_dict(a) for a in anomalies[:30]])
        domain_note  = f"Focus: **{focus_domain}**" if focus_domain not in ("all", "all domains") else "Firm-wide view"

        prompt_text = f"""You are a senior BI analyst at a broking and wealth management firm. Today is {data_end}.

{domain_note}. Below are the anomalies detected in the last 14 days (severity ≥ {severity_threshold}).

<anomalies>
{anomaly_json}
</anomalies>

Please produce a concise **Daily KPI Briefing** in the following structure:

## 1. Executive Summary (3–4 sentences)
What's the overall picture? Any systemic pattern across domains?

## 2. Critical Issues (if any)
For each Critical anomaly: what happened, where (firm/region/branch), and why it matters.

## 3. Warnings to Monitor
Brief bullets for Warning-level items that need tracking but not immediate action.

## 4. Positive Signals
Any KPIs performing above baseline? Note green shoots.

## 5. Recommended Actions
Top 3 concrete actions the business should take today.

Keep the tone professional and direct — this goes to the MD and domain heads."""

        return types.GetPromptResult(
            description=f"Daily KPI briefing as of {data_end}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=prompt_text),
                )
            ],
        )

    elif name == "investigate_anomaly":
        kpi          = args.get("kpi", "")
        dimension    = args.get("dimension", "firm-wide")
        anomaly_desc = args.get("anomaly_description", "anomalous behaviour detected")

        loader  = _get_loader()
        kpi_meta = loader.kpis.get(kpi, {})
        correlates = kpi_meta.get("correlates", [])
        kpi_name   = kpi_meta.get("display_name", kpi)
        domain     = kpi_meta.get("domain", "")
        unit       = kpi_meta.get("unit", "")
        direction  = kpi_meta.get("direction", "higher_is_better")
        description = kpi_meta.get("description", "")

        corr_info = ""
        if correlates:
            corr_names = [loader.kpis.get(c, {}).get("display_name", c) for c in correlates]
            corr_info  = f"Correlated KPIs: {', '.join(corr_names)} ({', '.join(correlates)})"

        prompt_text = f"""You are a senior BI analyst investigating a KPI anomaly.

**KPI Under Investigation:** {kpi_name} (`{kpi}`)
**Domain:** {domain}
**Unit:** {unit}
**Direction:** {direction}
**Description:** {description}
**Scope:** {dimension}
**Observation:** {anomaly_desc}
{corr_info}

Please structure your investigation as follows:

## 1. Anomaly Summary
Restate what was observed and why it is statistically significant.

## 2. Root-Cause Hypotheses
List 3–5 plausible explanations, ranked by likelihood. For each:
- Hypothesis
- Supporting evidence to look for
- How to confirm or rule it out

## 3. Correlated KPIs to Check
For each correlated KPI, explain what pattern would confirm vs. contradict the hypothesis.

## 4. Dimensional Drill-Down
Which hierarchy levels (region → branch → RM → segment) should be examined first, and why?

## 5. Recommended Actions
- Immediate (next 24 hours)
- Short-term (this week)
- Escalation path if the anomaly is confirmed

Be specific to the broking/wealth context — reference typical business drivers like market conditions, RM activity, seasonal patterns, or product campaigns."""

        return types.GetPromptResult(
            description=f"Anomaly investigation for {kpi_name}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=prompt_text),
                )
            ],
        )

    elif name == "kpi_performance_review":
        domain  = args.get("domain", "all")
        period  = args.get("period", "last 30 days")

        loader   = _get_loader()
        data_end = loader.df["date"].max().date()

        kpis = loader.domain_kpis(domain) if domain not in ("all", "") else loader.firm_kpis()
        summary = _tool_get_kpi_summary({"kpis": kpis, "recent_days": 30, "baseline_days": 90})
        summary_json = _fmt_json(summary)

        domain_label = domain if domain not in ("all", "") else "All Domains"

        prompt_text = f"""You are preparing a KPI performance review for senior management.

**Period:** {period} (data as of {data_end})
**Scope:** {domain_label}

Below is the KPI summary comparing recent performance vs. the 90-day baseline:

<kpi_summary>
{summary_json}
</kpi_summary>

Please produce a structured **Performance Review** in the following format:

## 1. Period Overview
2–3 sentences on the overall performance trend.

## 2. KPI Scorecard
A concise table or bullet list grouping KPIs as:
- **Outperforming** (positive deviation, on-target or better)
- **In-line** (within ±5% of baseline)
- **Underperforming** (negative deviation beyond threshold)

## 3. Domain Highlights
For each domain (Broking / Wealth / Clients), one paragraph on what drove performance.

## 4. Risks & Concerns
KPIs to watch and why — connect leading indicators to lagging ones where relevant.

## 5. Outlook & Recommendations
What levers can the business pull to improve the underperformers next period?

Use precise numbers from the data. Keep the narrative business-focused, not technical."""

        return types.GetPromptResult(
            description=f"KPI performance review — {domain_label} — {period}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(type="text", text=prompt_text),
                )
            ],
        )

    else:
        raise ValueError(f"Unknown prompt: {name}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())


# ─── Claude Code registration ─────────────────────────────────────────────────
# Add the following to /Users/adityaparab/.claude/settings.json (mcpServers key):
#
# "kpi-monitor": {
#   "command": "python",
#   "args": ["/Users/adityaparab/Desktop/KPI monitoring/mcp_server.py"],
#   "env": {}
# }
