"""Matplotlib time-series charts with anomaly markers and threshold bands."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from datetime import datetime

from .detect import PH_BAND

TS_FMT = "%Y-%m-%dT%H:%M:%S"
ELEVATED_TURBIDITY_NTU = 5.0


def _parse(ts):
    return datetime.strptime(ts, TS_FMT)


def station_chart(station, readings, anomalies, out_path):
    """Render pH + turbidity time series with anomaly markers. Saves PNG."""
    times = [_parse(r["ts"]) for r in readings]
    ph = [r["ph"] for r in readings]
    tb = [r["turbidity"] for r in readings]

    anom_ph = {_parse(a["ts"]) for a in anomalies if a["metric"] == "ph"}
    anom_tb = {_parse(a["ts"]) for a in anomalies if a["metric"] == "turbidity"}

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    fig.suptitle(f"AquaWatch — {station['name']} ({station['id']})", fontsize=13,
                 fontweight="bold")

    ax1.plot(times, ph, color="#1f77b4", lw=1.2, label="pH")
    ax1.axhspan(PH_BAND[0], PH_BAND[1], color="green", alpha=0.12,
                label=f"Guideline band {PH_BAND[0]}–{PH_BAND[1]} (not medical advice)")
    ax1.set_ylabel("pH")
    ax1.set_ylim(4.5, 9.5)
    for t in sorted(anom_ph):
        ax1.axvline(t, color="red", alpha=0.35, lw=1)
    if anom_ph:
        ax1.plot([], [], "x", color="red", ms=8, label="Anomaly")
        for t in sorted(anom_ph):
            v = ph[times.index(t)]
            ax1.plot(t, v, "x", color="red", ms=8, zorder=5)
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(alpha=0.3)

    ax2.plot(times, tb, color="#8c564b", lw=1.2, label="Turbidity (NTU)")
    ax2.axhline(ELEVATED_TURBIDITY_NTU, color="orange", ls="--", lw=1,
                label=f"Elevated ≥ {ELEVATED_TURBIDITY_NTU} NTU")
    ax2.set_ylabel("Turbidity (NTU)")
    ax2.set_xlabel("Time (UTC)")
    for t in sorted(anom_tb):
        ax2.axvline(t, color="red", alpha=0.35, lw=1)
    if anom_tb:
        ax2.plot([], [], "x", color="red", ms=8, label="Anomaly")
        for t in sorted(anom_tb):
            v = tb[times.index(t)]
            ax2.plot(t, v, "x", color="red", ms=8, zorder=5)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate(rotation=25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path
