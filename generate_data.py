"""
Generates realistic synthetic KPI data for the monitoring system.
Creates ~2 years of daily trading data with built-in seasonal patterns,
YoY growth, and 4 injected anomalies for demonstration.

Run: python generate_data.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import date, timedelta

np.random.seed(42)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=730)

REGIONS = ["North", "South", "East", "West"]
BRANCHES = {
    "North": ["Delhi", "Chandigarh", "Jaipur"],
    "South": ["Chennai", "Bangalore", "Hyderabad"],
    "East":  ["Kolkata", "Bhubaneswar", "Patna"],
    "West":  ["Mumbai", "Pune", "Ahmedabad"],
}
RMS_PER_BRANCH = 4
SEGMENTS = ["Retail", "HNI", "Ultra_HNI"]

# Base daily metrics per RM per segment (INR Lakhs for money, Count for clients)
BASE = {
    "Retail": {
        "brokerage_revenue": 2.8,
        "equity_volume": 520.0,
        "derivatives_volume": 180.0,
        "active_clients": 13.0,
        "new_accounts": 0.45,
        "aum": 820.0,
        "sip_inflows": 4.8,
        "lumpsum_inflows": 9.0,
        "redemptions": 3.8,
        "client_count": 48.0,
        "activation_rate": 0.65,
    },
    "HNI": {
        "brokerage_revenue": 9.5,
        "equity_volume": 1900.0,
        "derivatives_volume": 950.0,
        "active_clients": 7.5,
        "new_accounts": 0.18,
        "aum": 3400.0,
        "sip_inflows": 24.0,
        "lumpsum_inflows": 95.0,
        "redemptions": 19.0,
        "client_count": 22.0,
        "activation_rate": 0.72,
    },
    "Ultra_HNI": {
        "brokerage_revenue": 30.0,
        "equity_volume": 6000.0,
        "derivatives_volume": 3500.0,
        "active_clients": 2.5,
        "new_accounts": 0.04,
        "aum": 18000.0,
        "sip_inflows": 70.0,
        "lumpsum_inflows": 450.0,
        "redemptions": 60.0,
        "client_count": 5.5,
        "activation_rate": 0.80,
    },
}

# Branch market-size multipliers (bigger cities = larger base)
BRANCH_MULT = {
    "Delhi": 2.1, "Mumbai": 2.3, "Bangalore": 1.9,
    "Chennai": 1.4, "Kolkata": 1.3, "Hyderabad": 1.5,
    "Pune": 1.2, "Ahmedabad": 1.1, "Chandigarh": 0.85,
    "Jaipur": 0.75, "Bhubaneswar": 0.65, "Patna": 0.55,
}

# RM-level performance spread (some RMs outperform base)
RM_PERFORMANCE_SEED = 99


def make_rm_multipliers(rms):
    rng = np.random.default_rng(RM_PERFORMANCE_SEED)
    return {rm: rng.lognormal(0, 0.25) for rm in rms}


def seasonal_factor(d: date) -> float:
    """Month-end effect + quarter-end spike + day-of-week smoothing."""
    dom = d.day
    month_days = 30
    # Last 3 days of month: +20%
    if dom >= month_days - 2:
        base_s = 1.20
    # First 3 days of month: slightly lower
    elif dom <= 3:
        base_s = 0.90
    else:
        base_s = 1.00

    # Quarter-end last 5 trading days: additional +15%
    if d.month in (3, 6, 9, 12) and dom >= 25:
        base_s *= 1.15

    # Mild day-of-week effect (Mon/Fri lower, Tue-Thu higher)
    dow = d.weekday()  # 0=Mon, 4=Fri
    dow_factor = [0.95, 1.03, 1.05, 1.03, 0.94][dow]

    return base_s * dow_factor


def yoy_growth_factor(d: date, annual_rate: float = 0.16) -> float:
    """Compound daily growth from START_DATE."""
    days_elapsed = (d - START_DATE).days
    return (1 + annual_rate) ** (days_elapsed / 365.0)


def generate_nifty_series(dates: pd.DatetimeIndex) -> pd.Series:
    """Simulate Nifty 50 daily returns with mean reversion and volatility clusters."""
    rng = np.random.default_rng(7)
    n = len(dates)
    returns = np.zeros(n)
    vol = 0.01
    for i in range(1, n):
        vol = 0.85 * vol + 0.15 * abs(rng.normal(0, 0.01))
        vol = np.clip(vol, 0.003, 0.025)
        returns[i] = rng.normal(0.0003, vol)  # slight positive drift
    return pd.Series(returns, index=dates, name="nifty_return")


# ── Anomaly definitions ────────────────────────────────────────────────────────
# Each anomaly multiplies specific metrics for a dimension slice over a date window

ANOMALIES = [
    {
        "name": "South HNI brokerage collapse",
        "region": "South",
        "branch": None,        # applies to all South branches
        "segment": "HNI",
        "metrics": ["brokerage_revenue", "active_clients"],
        "days_back": 18,
        "factor": 0.52,        # -48%
    },
    {
        "name": "East Kolkata redemption surge",
        "region": "East",
        "branch": "Kolkata",
        "segment": None,       # all segments
        "metrics": ["redemptions"],
        "days_back": 10,
        "factor": 2.4,         # +140%
    },
    {
        "name": "North Delhi new account freeze",
        "region": "North",
        "branch": "Delhi",
        "segment": "Retail",
        "metrics": ["new_accounts"],
        "days_back": 8,
        "factor": 0.04,        # near zero
    },
    {
        "name": "West Mumbai Ultra_HNI AUM drawdown",
        "region": "West",
        "branch": "Mumbai",
        "segment": "Ultra_HNI",
        "metrics": ["aum", "net_flows"],
        "days_back": 14,
        "factor": 0.68,        # -32%
    },
]


def anomaly_factor(d: date, region: str, branch: str, segment: str,
                   metric: str) -> float:
    """Returns the combined anomaly multiplier for this (date, dim, metric)."""
    factor = 1.0
    for anom in ANOMALIES:
        cutoff = END_DATE - timedelta(days=anom["days_back"])
        if d < cutoff:
            continue
        if anom["region"] and region != anom["region"]:
            continue
        if anom["branch"] and branch != anom["branch"]:
            continue
        if anom["segment"] and segment != anom["segment"]:
            continue
        if metric in anom["metrics"]:
            factor *= anom["factor"]
    return factor


def build_skeleton() -> list[dict]:
    rms = []
    for region in REGIONS:
        for branch in BRANCHES[region]:
            for i in range(RMS_PER_BRANCH):
                rms.append({
                    "region": region,
                    "branch": branch,
                    "rm_id": f"{branch[:3].upper()}_RM{i+1:02d}",
                })
    return rms


def generate():
    print("Generating KPI data …")
    rms = build_skeleton()
    rm_ids = [r["rm_id"] for r in rms]
    rm_mults = make_rm_multipliers(rm_ids)

    trading_dates = pd.bdate_range(START_DATE.isoformat(), END_DATE.isoformat())
    nifty = generate_nifty_series(trading_dates)

    records = []
    rng = np.random.default_rng(42)

    for rm_info in rms:
        region = rm_info["region"]
        branch = rm_info["branch"]
        rm_id  = rm_info["rm_id"]
        bm     = BRANCH_MULT[branch]
        rpm    = rm_mults[rm_id]

        for seg in SEGMENTS:
            base = BASE[seg]

            for dt in trading_dates:
                d = dt.date()
                sf  = seasonal_factor(d)
                gf  = yoy_growth_factor(d)
                # Nifty correlation for market-sensitive metrics
                nret = nifty[dt]

                row = {
                    "date": d,
                    "region": region,
                    "branch": branch,
                    "rm_id": rm_id,
                    "segment": seg,
                }

                for metric, base_val in base.items():
                    # Market sensitivity: volumes correlate ~0.4 with Nifty
                    mkt_boost = 1.0
                    if metric in ("equity_volume", "derivatives_volume"):
                        mkt_boost = 1 + 0.35 * nret / 0.01  # scale nret
                        mkt_boost = np.clip(mkt_boost, 0.5, 1.5)
                    if metric in ("lumpsum_inflows",):
                        mkt_boost = 1 + 0.2 * nret / 0.01
                        mkt_boost = np.clip(mkt_boost, 0.6, 1.4)

                    # AUM is a stock — apply slower growth and less daily noise
                    if metric == "aum":
                        noise = rng.normal(1.0, 0.015)
                        val = base_val * bm * rpm * gf * noise
                    elif metric == "client_count":
                        noise = rng.normal(1.0, 0.02)
                        val = base_val * bm * rpm * gf * noise
                    elif metric == "activation_rate":
                        # Rate (0–1): must NOT scale with branch size or growth.
                        # Only mild RM-quality effect and noise.
                        noise = rng.normal(1.0, 0.04)
                        rm_quality = 0.85 + 0.15 * min(rpm, 2.0)
                        val = base_val * rm_quality * noise
                        val = float(np.clip(val, 0.0, 1.0))
                    else:
                        noise = rng.normal(1.0, 0.10)
                        val = base_val * bm * rpm * sf * gf * mkt_boost * noise
                        val = max(val, 0)

                    # Apply anomaly multiplier
                    af = anomaly_factor(d, region, branch, seg, metric)
                    val *= af

                    row[metric] = round(val, 4)

                # Derived: net_flows (not in BASE, computed then anomaly-adjusted)
                raw_net = row["sip_inflows"] + row["lumpsum_inflows"] - row["redemptions"]
                nf_af = anomaly_factor(d, region, branch, seg, "net_flows")
                row["net_flows"] = round(raw_net * nf_af, 4)

                records.append(row)

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    out = DATA_DIR / "kpi_data.parquet"
    df.to_parquet(out, index=False)
    print(f"  Saved {len(df):,} rows → {out}")

    # Save Nifty separately
    nifty_df = nifty.reset_index()
    nifty_df.columns = ["date", "nifty_return"]
    nifty_df["date"] = pd.to_datetime(nifty_df["date"])
    nifty_out = DATA_DIR / "market_data.parquet"
    nifty_df.to_parquet(nifty_out, index=False)
    print(f"  Saved {len(nifty_df):,} rows → {nifty_out}")

    # Save anomaly metadata for the dashboard
    anom_meta = []
    for a in ANOMALIES:
        anom_meta.append({
            "name": a["name"],
            "region": a["region"] or "All",
            "branch": a["branch"] or "All",
            "segment": a["segment"] or "All",
            "metrics": ", ".join(a["metrics"]),
            "days_back": a["days_back"],
            "factor": a["factor"],
            "start_date": END_DATE - timedelta(days=a["days_back"]),
        })
    anom_df = pd.DataFrame(anom_meta)
    anom_df.to_parquet(DATA_DIR / "injected_anomalies.parquet", index=False)
    print(f"  Saved anomaly metadata → data/injected_anomalies.parquet")
    print("Done.")


if __name__ == "__main__":
    generate()
