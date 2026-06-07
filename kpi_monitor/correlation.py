"""
Cross-KPI Correlation Validator.

When an anomaly is detected, this module checks the KPI's declared correlates
to determine whether the anomaly is:
  - Market-driven   (external factor, e.g. Nifty dropped → volumes fell)
  - Systemic issue  (multiple correlated KPIs are also anomalous)
  - Isolated        (correlates are healthy → points to specific root cause)

Produces a set of hypotheses ranked by confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .data_loader import DataLoader
from .anomaly_detector import Anomaly, AnomalyDetector, MONITORABLE_KPIS


@dataclass
class Hypothesis:
    hypothesis: str
    confidence: float            # 0–1
    evidence: str
    verdict: str                 # "Genuine Issue" | "Market-Driven" | "False Alarm" | "Unclear"
    supporting_kpis: list[str]
    contradicting_kpis: list[str]


@dataclass
class CorrelationReport:
    primary_anomaly: Anomaly
    primary_firm_status: dict | None       # primary KPI checked at firm level (None if anomaly is already firm-level)
    correlate_status: list[dict]          # {kpi, status, deviation_pct, note}
    hypotheses: list[Hypothesis]
    overall_verdict: str
    verdict_confidence: float


class CorrelationValidator:
    def __init__(self, loader: DataLoader):
        self.loader = loader
        self.detector = AnomalyDetector(loader)

    def validate(
        self,
        anomaly: Anomaly,
        baseline_window: int = 90,
    ) -> CorrelationReport:
        """
        Check whether correlated KPIs are also anomalous, then generate hypotheses.
        """
        correlates = self.loader.kpi_correlates(anomaly.kpi)
        correlate_status = []

        for corr_kpi in correlates:
            if corr_kpi not in MONITORABLE_KPIS and corr_kpi != "nifty_return":
                continue
            status = self._check_correlate(corr_kpi, anomaly, baseline_window)
            correlate_status.append(status)

        # Also check Nifty for market context if not already in correlates
        if "nifty_return" not in correlates:
            nifty_status = self._check_nifty(anomaly, baseline_window)
            if nifty_status:
                correlate_status.append(nifty_status)

        # Check the primary KPI itself at firm level — only meaningful if the anomaly
        # is at a sub-firm dimension (region/branch/rm/segment).
        # A healthy firm-level reading confirms the issue is truly isolated to this
        # dimension; an anomalous firm-level reading means a broader decline exists.
        primary_firm_status: dict | None = None
        if anomaly.dimension_level != "firm":
            primary_firm_status = self._check_correlate(anomaly.kpi, anomaly, baseline_window)

        hypotheses = self._generate_hypotheses(anomaly, correlate_status, primary_firm_status)
        hypotheses.sort(key=lambda h: -h.confidence)

        overall_verdict, confidence = self._overall_verdict(hypotheses)

        return CorrelationReport(
            primary_anomaly=anomaly,
            primary_firm_status=primary_firm_status,
            correlate_status=correlate_status,
            hypotheses=hypotheses,
            overall_verdict=overall_verdict,
            verdict_confidence=confidence,
        )

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _check_correlate(
        self,
        kpi: str,
        anomaly: Anomaly,
        baseline_window: int,
    ) -> dict:
        baseline_start = anomaly.analysis_start - timedelta(days=baseline_window)
        baseline_end   = anomaly.analysis_start - timedelta(days=1)

        # Aggregate firm-level for the same analysis window
        df = self.loader.firm_daily()
        if kpi not in df.columns:
            return {"kpi": kpi, "kpi_name": self.loader.kpi_display(kpi),
                    "status": "No Data", "deviation_pct": 0, "anomalous": False, "note": ""}

        df = df.sort_values("date").set_index("date")[kpi]
        baseline = df[
            (df.index >= pd.Timestamp(baseline_start))
            & (df.index <= pd.Timestamp(baseline_end))
        ]
        analysis = df[
            (df.index >= pd.Timestamp(anomaly.analysis_start))
            & (df.index <= pd.Timestamp(anomaly.analysis_end))
        ]

        if baseline.empty or analysis.empty:
            return {"kpi": kpi, "kpi_name": self.loader.kpi_display(kpi),
                    "status": "No Data", "deviation_pct": 0, "anomalous": False, "note": ""}

        base_mean = baseline.mean()
        act_mean  = analysis.mean()
        base_std  = baseline.std()
        deviation_pct = (act_mean - base_mean) / abs(base_mean) * 100 if base_mean else 0
        z = (act_mean - base_mean) / base_std if base_std else 0
        threshold = self.loader.zscore_threshold(kpi)
        direction = self.loader.kpi_direction(kpi)

        is_anomalous = (
            (direction == "higher_is_better" and z < -threshold)
            or (direction == "lower_is_better" and z > threshold)
        )
        status = "Anomalous" if is_anomalous else "Normal"
        note = f"z={z:.2f}, deviation={deviation_pct:+.1f}%"

        return {
            "kpi": kpi,
            "kpi_name": self.loader.kpi_display(kpi),
            "status": status,
            "deviation_pct": round(deviation_pct, 1),
            "anomalous": is_anomalous,
            "z_score": round(z, 2),
            "note": note,
        }

    def _check_nifty(self, anomaly: Anomaly, baseline_window: int = 90) -> dict | None:
        mkt = self.loader.market
        if mkt.empty:
            return None
        mkt = mkt.sort_values("date").set_index("date")["nifty_return"]

        analysis = mkt[
            (mkt.index >= pd.Timestamp(anomaly.analysis_start))
            & (mkt.index <= pd.Timestamp(anomaly.analysis_end))
        ]
        baseline = mkt[
            mkt.index < pd.Timestamp(anomaly.analysis_start)
        ].tail(baseline_window)

        if analysis.empty or baseline.empty:
            return None

        act_mean  = analysis.mean()
        base_mean = baseline.mean()
        base_std  = baseline.std()
        deviation_pct = (act_mean - base_mean) / (abs(base_std) + 1e-9) * 100
        z = (act_mean - base_mean) / base_std if base_std else 0

        # Nifty is anomalous if z < -1.5 (lower threshold as it's external)
        is_anomalous = z < -1.5 or act_mean < -0.005  # persistent negative days

        return {
            "kpi": "nifty_return",
            "kpi_name": "Nifty 50 Return",
            "status": "Market Stress" if is_anomalous else "Normal",
            "deviation_pct": round(deviation_pct, 1),
            "anomalous": is_anomalous,
            "z_score": round(z, 2),
            "note": f"Avg daily return: {act_mean*100:.3f}%",
        }

    def _generate_hypotheses(
        self,
        anomaly: Anomaly,
        correlate_status: list[dict],
        primary_firm_status: dict | None = None,
    ) -> list[Hypothesis]:
        hypotheses: list[Hypothesis] = []
        direction   = anomaly.direction
        is_bad      = (
            (direction == "higher_is_better" and anomaly.deviation_pct < 0)
            or (direction == "lower_is_better" and anomaly.deviation_pct > 0)
        )

        nifty_status = next(
            (c for c in correlate_status if c["kpi"] == "nifty_return"), None
        )
        anomalous_corrs  = [c for c in correlate_status if c.get("anomalous") and c["kpi"] != "nifty_return"]
        healthy_corrs    = [c for c in correlate_status if not c.get("anomalous") and c["kpi"] != "nifty_return"]
        market_stressed  = nifty_status and nifty_status.get("anomalous", False)

        # ── Hypothesis 1: Market-driven ───────────────────────────────────────
        if market_stressed and is_bad:
            mkt_correlation_kpis = [
                c["kpi"] for c in anomalous_corrs
                if c["kpi"] in ("equity_volume", "derivatives_volume", "lumpsum_inflows")
            ]
            conf = 0.80 if len(mkt_correlation_kpis) >= 1 else 0.55
            hypotheses.append(Hypothesis(
                hypothesis="Market-driven downturn (Nifty stress)",
                confidence=conf,
                evidence=(
                    f"Nifty is showing stress ({nifty_status['note']}) during the anomaly window. "
                    f"Market-sensitive KPIs ({', '.join(mkt_correlation_kpis) or 'none'}) also impacted."
                ),
                verdict="Market-Driven",
                supporting_kpis=[c["kpi"] for c in anomalous_corrs],
                contradicting_kpis=[c["kpi"] for c in healthy_corrs],
            ))

        # ── Hypothesis 2: Client attrition / engagement drop ──────────────────
        client_kpis = [c for c in anomalous_corrs if c["kpi"] in ("active_clients", "client_count")]
        if client_kpis and is_bad:
            hypotheses.append(Hypothesis(
                hypothesis="Client attrition or engagement decline",
                confidence=0.85,
                evidence=(
                    f"Active clients / total clients are also declining: "
                    + ", ".join(f"{c['kpi_name']} {c['deviation_pct']:+.1f}%" for c in client_kpis)
                ),
                verdict="Genuine Issue",
                supporting_kpis=[c["kpi"] for c in client_kpis],
                contradicting_kpis=[],
            ))

        # ── Hypothesis 3: Systemic operational / sales issue ──────────────────
        if len(anomalous_corrs) >= 2 and is_bad:
            conf = min(0.90, 0.6 + 0.1 * len(anomalous_corrs))
            hypotheses.append(Hypothesis(
                hypothesis="Systemic issue affecting multiple KPIs",
                confidence=conf,
                evidence=(
                    f"{len(anomalous_corrs)} correlated KPIs are also anomalous: "
                    + ", ".join(f"{c['kpi_name']}" for c in anomalous_corrs[:4])
                ),
                verdict="Genuine Issue",
                supporting_kpis=[c["kpi"] for c in anomalous_corrs],
                contradicting_kpis=[],
            ))

        # ── Hypothesis 3b: Primary KPI is also declining at firm level ───────────
        if primary_firm_status and primary_firm_status.get("anomalous") and is_bad:
            firm_dev = primary_firm_status["deviation_pct"]
            hypotheses.append(Hypothesis(
                hypothesis=f"Firm-wide decline in {anomaly.kpi_name} — this dimension is worst-hit",
                confidence=0.85,
                evidence=(
                    f"{anomaly.kpi_name} is also anomalous at firm level "
                    f"({firm_dev:+.1f}% vs baseline). "
                    f"The detected dimension ({anomaly.dimension_label()}) is likely the largest "
                    f"contributor to a broader firm-wide problem, not an isolated outlier."
                ),
                verdict="Genuine Issue",
                supporting_kpis=[anomaly.kpi],
                contradicting_kpis=[],
            ))

        # ── Hypothesis 4: Isolated dimension issue vs. firm-wide false alarm ────
        if len(healthy_corrs) >= 2 and len(anomalous_corrs) == 0 and not market_stressed:
            # High z-score → anomaly is real, just confined to this dimension
            # Low/borderline z-score → could be statistical noise
            high_z = abs(anomaly.z_score) >= 2.5 or abs(anomaly.deviation_pct) >= 25
            dim_label = anomaly.dimension_label()
            is_sub_dim = anomaly.dimension_level not in ("firm",)

            if is_sub_dim and high_z:
                # If primary KPI is also healthy at firm level, we have direct
                # confirmation that the issue is contained to this dimension.
                firm_healthy = (
                    primary_firm_status is not None
                    and not primary_firm_status.get("anomalous")
                )
                firm_note = (
                    f" {anomaly.kpi_name} is flat at firm level "
                    f"({primary_firm_status['deviation_pct']:+.1f}%), "
                    f"confirming the issue is contained to {dim_label}."
                    if firm_healthy else ""
                )
                confidence = 0.90 if firm_healthy else 0.80
                hypotheses.append(Hypothesis(
                    hypothesis=f"Genuine issue isolated to {dim_label}",
                    confidence=confidence,
                    evidence=(
                        f"Correlated KPIs are healthy at firm level "
                        f"({', '.join(c['kpi_name'] for c in healthy_corrs[:3])}), "
                        f"but the anomaly ({anomaly.deviation_pct:+.1f}%, z={anomaly.z_score:.2f}) "
                        f"is statistically significant — pointing to a dimension-specific cause."
                        f"{firm_note}"
                    ),
                    verdict="Genuine Issue",
                    supporting_kpis=[],
                    contradicting_kpis=[c["kpi"] for c in healthy_corrs],
                ))
            else:
                hypotheses.append(Hypothesis(
                    hypothesis="Possibly statistical noise — correlates healthy",
                    confidence=0.65,
                    evidence=(
                        f"All {len(healthy_corrs)} correlated KPIs are within normal range: "
                        + ", ".join(c["kpi_name"] for c in healthy_corrs[:4])
                        + ". Anomaly may reflect short-term volatility."
                    ),
                    verdict="False Alarm",
                    supporting_kpis=[],
                    contradicting_kpis=[c["kpi"] for c in healthy_corrs],
                ))

        # ── Hypothesis 5: AUM / wealth flow mismatch ─────────────────────────
        if anomaly.kpi == "aum":
            net_flow_stat = next(
                (c for c in correlate_status if c["kpi"] == "net_flows"), None
            )
            if net_flow_stat and net_flow_stat.get("anomalous"):
                hypotheses.append(Hypothesis(
                    hypothesis="Net flow deterioration driving AUM decline",
                    confidence=0.90,
                    evidence=(
                        f"Net flows are also anomalous at "
                        f"{net_flow_stat['deviation_pct']:+.1f}% — redemptions likely exceeding inflows."
                    ),
                    verdict="Genuine Issue",
                    supporting_kpis=["net_flows"],
                    contradicting_kpis=[],
                ))

        if not hypotheses:
            hypotheses.append(Hypothesis(
                hypothesis="Root cause unclear — further investigation required",
                confidence=0.40,
                evidence="No correlated KPIs confirm or deny the anomaly conclusively.",
                verdict="Unclear",
                supporting_kpis=[],
                contradicting_kpis=[],
            ))

        return hypotheses

    def _overall_verdict(self, hypotheses: list[Hypothesis]) -> tuple[str, float]:
        if not hypotheses:
            return "Unclear", 0.0
        top = hypotheses[0]
        return top.verdict, top.confidence
