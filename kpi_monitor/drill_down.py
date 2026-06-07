"""
Drill-Down Analyzer.

For anomalies detected at any hierarchy level, this module traces the
full path from Firm → Region → Branch → RM → Segment, confirming which
sub-dimension is the primary contributor at each step.

For firm-level anomalies: auto-discovers the root cause path.
For deep-level anomalies: follows the known dimension path top-down,
confirming the trace at each step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .data_loader import DataLoader, HIERARCHY
from .anomaly_detector import Anomaly


@dataclass
class DrillNode:
    level: str
    dimension_value: str
    dimension_path: dict[str, str]
    actual_avg: float
    expected_avg: float
    deviation_pct: float
    absolute_variance: float
    contribution_pct: float
    is_primary_contributor: bool


@dataclass
class DrillPath:
    kpi: str
    kpi_name: str
    unit: str
    anomaly_summary: str
    nodes: list[DrillNode]
    root_cause_label: str
    root_cause_path: dict[str, str]


class DrillDownAnalyzer:
    def __init__(self, loader: DataLoader):
        self.loader = loader

    def analyze(self, anomaly: Anomaly, baseline_window: int = 90) -> DrillPath:
        """
        Trace the full Firm → Region → Branch → RM → Segment path.

        Strategy:
        - For firm-level anomalies or anomalies without a known path: fully auto-discover
          (pick the highest-variance child at each step).
        - For deeper anomalies (region / branch / rm / segment): follow the known path
          for levels AT OR ABOVE the detected level, then auto-discover deeper — so a
          region-level anomaly still drills all the way to RM and Segment.
        """
        kpi            = anomaly.kpi
        analysis_start = anomaly.analysis_start
        analysis_end   = anomaly.analysis_end
        baseline_start = analysis_start - timedelta(days=baseline_window)
        baseline_end   = analysis_start - timedelta(days=1)

        anom_level = anomaly.dimension_level
        known_path = dict(anomaly.dimension_values)   # levels already identified

        firm_level_anom  = (anom_level == "firm" or not known_path)
        anom_h_idx       = (
            HIERARCHY.index(anom_level)
            if (not firm_level_anom and anom_level in HIERARCHY)
            else -1          # -1 means "auto-drill everything"
        )

        current_filters: dict[str, str] = {}
        path_nodes: list[DrillNode] = []

        for h_idx, level in enumerate(HIERARCHY):     # always traverse all 4 levels
            group_cols = HIERARCHY[: h_idx + 1]

            df_full = self.loader.aggregate(group_by=group_cols)
            if kpi not in df_full.columns:
                break

            nodes = self._decompose_level(
                df_full, kpi, level, group_cols,
                current_filters,
                analysis_start, analysis_end,
                baseline_start, baseline_end,
            )

            if not nodes:
                break

            follow_known = (not firm_level_anom) and (h_idx <= anom_h_idx)

            if follow_known:
                # This level is part of the known anomaly path — follow it
                known_val = known_path.get(level)
                matched   = False
                for n in nodes:
                    if known_val and n.dimension_value == known_val:
                        n.is_primary_contributor = True
                        matched = True
                        break
                if not matched:
                    # fallback: mark the largest contributor
                    max(nodes, key=lambda n: abs(n.absolute_variance)).is_primary_contributor = True

                primary_val = known_val if known_val else next(
                    n.dimension_value for n in nodes if n.is_primary_contributor
                )
                current_filters[level] = primary_val
            else:
                # Auto-discover: pick the child with the highest absolute variance
                primary = max(nodes, key=lambda n: abs(n.absolute_variance))
                primary.is_primary_contributor = True
                current_filters[level] = primary.dimension_value

            path_nodes.extend(nodes)

        # Build full root-cause label from the complete traversal path
        root_cause_label = " › ".join(
            f"{k.replace('_', ' ').title()}: {v}"
            for k, v in current_filters.items()
            if v
        )
        if not root_cause_label:
            root_cause_label = "Firm-wide — no single sub-dimension dominant"

        return DrillPath(
            kpi=kpi,
            kpi_name=self.loader.kpi_display(kpi),
            unit=self.loader.kpi_unit(kpi),
            anomaly_summary=anomaly.summary,
            nodes=path_nodes,
            root_cause_label=root_cause_label,
            root_cause_path=current_filters,
        )

    def _decompose_level(
        self,
        df: pd.DataFrame,
        kpi: str,
        level: str,
        group_cols: list[str],
        filters: dict,
        analysis_start: date,
        analysis_end: date,
        baseline_start: date,
        baseline_end: date,
    ) -> list[DrillNode]:
        # Apply parent dimension filters
        mask = pd.Series([True] * len(df), index=df.index)
        for col, val in filters.items():
            if col in df.columns and val:
                mask &= df[col] == val
        df_filtered = df[mask]

        analysis_data = df_filtered[
            (df_filtered["date"] >= pd.Timestamp(analysis_start))
            & (df_filtered["date"] <= pd.Timestamp(analysis_end))
        ]
        baseline_data = df_filtered[
            (df_filtered["date"] >= pd.Timestamp(baseline_start))
            & (df_filtered["date"] <= pd.Timestamp(baseline_end))
        ]

        if analysis_data.empty or baseline_data.empty or kpi not in df_filtered.columns:
            return []

        analysis_avg = analysis_data.groupby(level)[kpi].mean()
        baseline_avg = baseline_data.groupby(level)[kpi].mean()
        common_dims  = analysis_avg.index.intersection(baseline_avg.index)

        if len(common_dims) == 0:
            return []

        analysis_avg = analysis_avg[common_dims]
        baseline_avg = baseline_avg[common_dims]
        variance     = analysis_avg - baseline_avg

        total_abs_variance = variance.abs().sum()
        if total_abs_variance == 0:
            return []

        direction  = self.loader.kpi_direction(kpi)
        if direction == "higher_is_better":
            bad_mask = variance < 0
        else:
            bad_mask = variance > 0

        bad_total = variance[bad_mask].sum() if bad_mask.any() else variance.sum()
        if bad_total == 0:
            bad_total = variance.sum()

        nodes: list[DrillNode] = []
        for dim in common_dims:
            var  = variance[dim]
            act  = analysis_avg[dim]
            base = baseline_avg[dim]
            dev_pct     = (act - base) / abs(base) * 100 if base != 0 else 0
            contrib_pct = var / bad_total * 100 if bad_total != 0 else 0

            dim_path = {**filters, level: str(dim)}

            nodes.append(DrillNode(
                level=level,
                dimension_value=str(dim),
                dimension_path={k: str(v) for k, v in dim_path.items()},
                actual_avg=act,
                expected_avg=base,
                deviation_pct=dev_pct,
                absolute_variance=var,
                contribution_pct=contrib_pct,
                is_primary_contributor=False,
            ))

        return nodes

    def to_dataframe(self, path: DrillPath) -> pd.DataFrame:
        rows = []
        for n in path.nodes:
            rows.append({
                "Level":          n.level.replace("_", " ").title(),
                "Dimension":      n.dimension_value,
                "Path":           " › ".join(n.dimension_path.values()),
                "Actual":         round(n.actual_avg, 2),
                "Expected":       round(n.expected_avg, 2),
                "Variance":       round(n.absolute_variance, 2),
                "Deviation %":    round(n.deviation_pct, 1),
                "Contribution %": round(n.contribution_pct, 1),
                "Primary":        "Yes" if n.is_primary_contributor else "",
            })
        return pd.DataFrame(rows)
