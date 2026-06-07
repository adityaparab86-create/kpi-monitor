"""
Anomaly detection engine.

Three complementary detection methods are applied:
  1. Rolling Z-score  — statistical deviation from 90-day baseline
  2. Target breach    — deviation beyond configured % from rolling target
  3. Trend reversal   — 7-day slope sign-flip vs. 30-day trend

Results are ranked by severity and returned as a list of Anomaly objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .data_loader import DataLoader, HIERARCHY, ALL_METRICS

MONITORABLE_KPIS = [
    "brokerage_revenue", "equity_volume", "derivatives_volume",
    "active_clients", "new_accounts", "aum", "sip_inflows",
    "lumpsum_inflows", "redemptions", "net_flows", "client_count",
    "activation_rate",
]

SEVERITY_LABELS = {3: "Critical", 2: "Warning", 1: "Watch"}
SEVERITY_COLORS = {"Critical": "#d62728", "Warning": "#ff7f0e", "Watch": "#bcbd22"}
METHOD_LABELS   = {
    "zscore":         "z-score — statistically unusual drop for this KPI",
    "target_breach":  "target breach",
    "trend_reversal": "trend reversal in last 7 days",
}


@dataclass
class Anomaly:
    kpi: str
    kpi_name: str
    domain: str
    detection_method: str          # zscore | target_breach | trend_reversal
    severity: str                  # Critical | Warning | Watch
    severity_score: int            # 3 / 2 / 1
    dimension_level: str           # firm | region | branch | rm_id | segment
    dimension_values: dict[str, str]
    analysis_start: date
    analysis_end: date
    actual_value: float
    expected_value: float
    deviation_pct: float
    z_score: float
    direction: str                 # higher_is_better | lower_is_better
    unit: str
    summary: str

    def dimension_label(self) -> str:
        if not self.dimension_values:
            return "Firm-wide"
        return " › ".join(self.dimension_values.values())


class AnomalyDetector:
    def __init__(self, loader: DataLoader):
        self.loader = loader

    # ─── Public API ────────────────────────────────────────────────────────────

    def detect_all(
        self,
        analysis_window: int = 14,
        baseline_window: int = 90,
        levels: list[str] | None = None,
        kpi_list: list[str] | None = None,
        zscore_multiplier: float = 1.0,
    ) -> list[Anomaly]:
        """
        Run detection across all KPIs and hierarchy levels.
        kpi_list restricts detection to a subset of KPIs (used for per-domain runs).
        zscore_multiplier scales all thresholds — >1.0 reduces sensitivity in volatile markets.
        Returns anomalies sorted by severity (Critical first).
        """
        detect_levels    = levels or (["firm"] + HIERARCHY)
        kpis_to_detect   = kpi_list if kpi_list is not None else MONITORABLE_KPIS
        anomalies: list[Anomaly] = []

        end_date = self.loader.df["date"].max().date()
        analysis_start = end_date - timedelta(days=analysis_window - 1)
        baseline_start = end_date - timedelta(days=baseline_window + analysis_window)
        baseline_end   = analysis_start - timedelta(days=1)

        for kpi in kpis_to_detect:
            for level in detect_levels:
                anomalies.extend(
                    self._detect_for_level(
                        kpi, level,
                        analysis_start, end_date,
                        baseline_start, baseline_end,
                        zscore_multiplier=zscore_multiplier,
                    )
                )

        # Deduplicate: if the same KPI/dimension is flagged by multiple methods,
        # keep only the most severe instance
        anomalies = self._deduplicate(anomalies)
        # Primary sort: severity (Critical first).
        # Tiebreaker: absolute revenue impact — the dimension with the largest
        # monetary/volume gap from baseline surfaces first, so a high-volume RM
        # with the same %-deviation as a smaller peer is correctly ranked higher.
        anomalies.sort(key=lambda a: (-a.severity_score, -abs(a.actual_value - a.expected_value)))
        return anomalies

    def detect_for_kpi(
        self,
        kpi: str,
        analysis_window: int = 14,
        baseline_window: int = 90,
    ) -> list[Anomaly]:
        end_date = self.loader.df["date"].max().date()
        analysis_start = end_date - timedelta(days=analysis_window - 1)
        baseline_start = end_date - timedelta(days=baseline_window + analysis_window)
        baseline_end   = analysis_start - timedelta(days=1)

        anomalies: list[Anomaly] = []
        for level in ["firm"] + HIERARCHY:
            anomalies.extend(
                self._detect_for_level(
                    kpi, level,
                    analysis_start, end_date,
                    baseline_start, baseline_end,
                )
            )
        return sorted(anomalies, key=lambda a: (-a.severity_score, -abs(a.actual_value - a.expected_value)))

    # ─── Internal methods ──────────────────────────────────────────────────────

    def _detect_for_level(
        self,
        kpi: str,
        level: str,
        analysis_start: date,
        analysis_end: date,
        baseline_start: date,
        baseline_end: date,
        zscore_multiplier: float = 1.0,
    ) -> list[Anomaly]:
        if level == "firm":
            df_agg = self.loader.firm_daily()
            group_cols: list[str] = []
        else:
            idx = HIERARCHY.index(level)
            group_cols = HIERARCHY[: idx + 1]
            df_agg = self.loader.aggregate(group_by=group_cols)

        if kpi not in df_agg.columns:
            return []

        anomalies = []
        dimension_groups = (
            [{}] if level == "firm"
            else [
                dict(zip(group_cols, vals))
                for vals in df_agg[group_cols].drop_duplicates().values
            ]
        )

        for dim_vals in dimension_groups:
            if dim_vals:
                mask = pd.Series([True] * len(df_agg))
                for col, val in dim_vals.items():
                    mask &= df_agg[col] == val
                slice_df = df_agg[mask].copy()
            else:
                slice_df = df_agg.copy()

            slice_df = slice_df.sort_values("date")
            series = slice_df.set_index("date")[kpi]

            baseline = series[
                (series.index >= pd.Timestamp(baseline_start))
                & (series.index <= pd.Timestamp(baseline_end))
            ]
            analysis = series[
                (series.index >= pd.Timestamp(analysis_start))
                & (series.index <= pd.Timestamp(analysis_end))
            ]

            if len(baseline) < 10 or len(analysis) < 1:
                continue

            anom = self._apply_detection(
                kpi, series, baseline, analysis,
                level, dim_vals,
                analysis_start, analysis_end,
                zscore_multiplier=zscore_multiplier,
            )
            if anom:
                anomalies.append(anom)

        return anomalies

    def _apply_detection(
        self,
        kpi: str,
        full_series: pd.Series,
        baseline: pd.Series,
        analysis: pd.Series,
        level: str,
        dim_vals: dict,
        analysis_start: date,
        analysis_end: date,
        zscore_multiplier: float = 1.0,
    ) -> Anomaly | None:
        baseline_mean = baseline.mean()
        baseline_std  = baseline.std()
        actual_mean   = analysis.mean()
        direction     = self.loader.kpi_direction(kpi)
        # Scale thresholds by regime multiplier: >1.0 = fewer alerts in volatile markets
        threshold         = self.loader.zscore_threshold(kpi) * zscore_multiplier
        target_breach_pct = self.loader.target_breach_pct(kpi) * zscore_multiplier

        if baseline_std == 0 or baseline_mean == 0:
            return None

        z = (actual_mean - baseline_mean) / baseline_std
        deviation_pct = (actual_mean - baseline_mean) / abs(baseline_mean) * 100

        # ── Method 1: Z-score ─────────────────────────────────────────────────
        triggered = False
        method = "zscore"

        if direction == "higher_is_better":
            triggered = z < -threshold
        else:
            triggered = z > threshold

        # ── Method 2: Target breach ───────────────────────────────────────────
        if not triggered:
            if direction == "higher_is_better" and deviation_pct < -target_breach_pct:
                triggered = True
                method = "target_breach"
            elif direction == "lower_is_better" and deviation_pct > target_breach_pct:
                triggered = True
                method = "target_breach"

        # ── Method 3: Trend reversal ──────────────────────────────────────────
        if not triggered and len(full_series) >= 30:
            recent_30 = full_series.tail(30).values
            recent_7  = full_series.tail(7).values
            x30 = np.arange(len(recent_30))
            x7  = np.arange(len(recent_7))
            slope_30 = np.polyfit(x30, recent_30, 1)[0] if len(x30) > 1 else 0
            slope_7  = np.polyfit(x7,  recent_7,  1)[0] if len(x7)  > 1 else 0
            # Trend reversal: 7-day slope flipped direction from 30-day slope
            if (
                abs(slope_30) > baseline_std * 0.01
                and np.sign(slope_30) != np.sign(slope_7)
                and abs(slope_7) > abs(slope_30) * 0.5
            ):
                bad_reversal = (
                    (direction == "higher_is_better" and slope_7 < 0)
                    or (direction == "lower_is_better" and slope_7 > 0)
                )
                if bad_reversal:
                    triggered = True
                    method = "trend_reversal"

        if not triggered:
            return None

        # ── Severity scoring ──────────────────────────────────────────────────
        abs_z = abs(z)
        if abs_z >= 3.0 or abs(deviation_pct) >= 35:
            severity_score = 3
        elif abs_z >= 2.5 or abs(deviation_pct) >= 20:
            severity_score = 2
        else:
            severity_score = 1

        # Trend reversals start at Watch unless the z-score is high
        if method == "trend_reversal" and severity_score > 1 and abs_z < 2.0:
            severity_score = 1

        severity = SEVERITY_LABELS[severity_score]

        summary = (
            f"{self.loader.kpi_display(kpi)} is "
            f"{'down' if deviation_pct < 0 else 'up'} "
            f"{abs(deviation_pct):.1f}% vs baseline"
            f" ({severity.lower()} — {METHOD_LABELS.get(method, method)})"
        )

        return Anomaly(
            kpi=kpi,
            kpi_name=self.loader.kpi_display(kpi),
            domain=self.loader.kpi_domain(kpi),
            detection_method=method,
            severity=severity,
            severity_score=severity_score,
            dimension_level=level,
            dimension_values=dim_vals,
            analysis_start=analysis_start,
            analysis_end=analysis_end,
            actual_value=actual_mean,
            expected_value=baseline_mean,
            deviation_pct=deviation_pct,
            z_score=z,
            direction=direction,
            unit=self.loader.kpi_unit(kpi),
            summary=summary,
        )

    def _deduplicate(self, anomalies: list[Anomaly]) -> list[Anomaly]:
        seen: dict[str, Anomaly] = {}
        for a in anomalies:
            key = f"{a.kpi}|{a.dimension_level}|{a.dimension_label()}"
            if key not in seen or a.severity_score > seen[key].severity_score:
                seen[key] = a
        return list(seen.values())
