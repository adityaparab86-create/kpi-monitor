"""
Data loading and caching layer.
Provides a single DataLoader class that reads Parquet files, loads the KPI
config, and exposes query helpers used by the anomaly detector and dashboard.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from functools import lru_cache
from datetime import date, timedelta

import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "kpi_config.yaml"

HIERARCHY = ["region", "branch", "rm_id", "segment"]
FLOW_METRICS = [
    "brokerage_revenue", "equity_volume", "derivatives_volume",
    "active_clients", "new_accounts", "sip_inflows", "lumpsum_inflows",
    "redemptions", "net_flows", "activation_rate",
]
STOCK_METRICS = ["aum", "client_count"]
ALL_METRICS = FLOW_METRICS + STOCK_METRICS


class DataLoader:
    def __init__(self):
        with open(CONFIG_PATH) as f:
            self.config = yaml.safe_load(f)
        self.kpis = self.config["kpis"]
        self._df: pd.DataFrame | None = None
        self._market: pd.DataFrame | None = None

    # ── Raw data ──────────────────────────────────────────────────────────────

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            path = DATA_DIR / "kpi_data.parquet"
            if not path.exists():
                raise FileNotFoundError(
                    "Data not generated yet. Run: python generate_data.py"
                )
            self._df = pd.read_parquet(path)
            self._df["date"] = pd.to_datetime(self._df["date"])
        return self._df

    @property
    def market(self) -> pd.DataFrame:
        if self._market is None:
            path = DATA_DIR / "market_data.parquet"
            if not path.exists():
                return pd.DataFrame(columns=["date", "nifty_return"])
            self._market = pd.read_parquet(path)
            self._market["date"] = pd.to_datetime(self._market["date"])
        return self._market

    # ── Aggregation helpers ───────────────────────────────────────────────────

    def aggregate(
        self,
        group_by: list[str] | None = None,
        date_range: tuple[date, date] | None = None,
        filters: dict | None = None,
    ) -> pd.DataFrame:
        """Return a time-series DataFrame aggregated to the requested dimensions."""
        df = self.df.copy()

        if date_range:
            df = df[
                (df["date"] >= pd.Timestamp(date_range[0]))
                & (df["date"] <= pd.Timestamp(date_range[1]))
            ]

        if filters:
            for col, val in filters.items():
                if val and val != "All":
                    df = df[df[col] == val]

        group = ["date"] + (group_by or [])
        agg_cols = {m: "sum" for m in ALL_METRICS}
        # activation_rate should be averaged, not summed
        agg_cols["activation_rate"] = "mean"

        result = df.groupby(group).agg(agg_cols).reset_index()
        return result

    def firm_daily(self, date_range: tuple[date, date] | None = None) -> pd.DataFrame:
        """Firm-wide daily aggregation (no dimension breakdown)."""
        return self.aggregate(date_range=date_range)

    def by_level(
        self,
        level: str,
        date_range: tuple[date, date] | None = None,
        filters: dict | None = None,
    ) -> pd.DataFrame:
        """Aggregate by a single hierarchy level."""
        if level not in HIERARCHY:
            raise ValueError(f"Unknown level: {level}")
        # Include all parent levels so the result is navigable
        idx = HIERARCHY.index(level)
        group = HIERARCHY[: idx + 1]
        return self.aggregate(group_by=group, date_range=date_range, filters=filters)

    # ── Convenience date ranges ───────────────────────────────────────────────

    def last_n_days(self, n: int) -> tuple[date, date]:
        end = self.df["date"].max().date()
        return (end - timedelta(days=n - 1), end)

    def prior_n_days(self, n: int, offset: int | None = None) -> tuple[date, date]:
        end = self.df["date"].max().date()
        if offset is None:
            offset = n
        period_end = end - timedelta(days=offset)
        return (period_end - timedelta(days=n - 1), period_end)

    # ── KPI metadata helpers ──────────────────────────────────────────────────

    def kpi_direction(self, kpi: str) -> str:
        return self.kpis.get(kpi, {}).get("direction", "higher_is_better")

    def kpi_unit(self, kpi: str) -> str:
        return self.kpis.get(kpi, {}).get("unit", "")

    def kpi_display(self, kpi: str) -> str:
        return self.kpis.get(kpi, {}).get("display_name", kpi)

    def kpi_domain(self, kpi: str) -> str:
        return self.kpis.get(kpi, {}).get("domain", "Other")

    def kpi_correlates(self, kpi: str) -> list[str]:
        return self.kpis.get(kpi, {}).get("correlates", [])

    def zscore_threshold(self, kpi: str) -> float:
        return self.kpis.get(kpi, {}).get("zscore_threshold", 2.0)

    def target_breach_pct(self, kpi: str) -> float:
        return self.kpis.get(kpi, {}).get("target_breach_pct", 15.0)

    def kpi_is_stock(self, kpi: str) -> bool:
        return bool(self.kpis.get(kpi, {}).get("stock_metric", False))

    def firm_kpis(self) -> list[str]:
        return [k for k in self.kpis if k != "nifty_return"]

    def domain_kpis(self, domain: str) -> list[str]:
        return [k for k, v in self.kpis.items() if v.get("domain") == domain and k != "nifty_return"]
