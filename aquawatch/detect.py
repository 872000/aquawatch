"""Anomaly detection for AquaWatch.

Three detectors run per station per metric over the sensor stream:

* RollingZScoreDetector — flags a reading whose z-score against the trailing
  ``window`` of prior readings exceeds ``z_thresh`` (causal: no look-ahead).
* IQROutlierDetector — flags a reading outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
  of the trailing window (Tukey fences).
* PHBandGuard — flags any pH outside the 6.5-8.5 guideline band. This band is
  a WHO-style *guideline for context only, not medical advice*.

Each anomaly is a dict: station_id, ts, metric, value, rules, score.
"""

import statistics

PH_BAND = (6.5, 8.5)  # guideline band for context only — not medical advice.
METRICS = ("ph", "turbidity")


def _quartiles(values):
    q1, _median, q3 = statistics.quantiles(values, n=4)
    return q1, q3


def detect_station(station_id, readings, window=24, z_thresh=3.0, min_window=12):
    """Detect anomalies in a station's readings (list of dicts, sorted by ts)."""
    anomalies = []
    for metric in METRICS:
        series = [(r["ts"], r[metric]) for r in readings if r.get(metric) is not None]
        for i, (ts, value) in enumerate(series):
            rules, score = [], 0.0
            if metric == "ph" and (value < PH_BAND[0] or value > PH_BAND[1]):
                rules.append("ph_band")
                score = max(score, abs(value - 7.5))
            hist = [v for _, v in series[max(0, i - window):i]]
            if len(hist) >= min_window:
                mean = statistics.fmean(hist)
                sd = statistics.pstdev(hist)
                if sd > 1e-9:
                    z = (value - mean) / sd
                    if abs(z) >= z_thresh:
                        rules.append("zscore")
                        score = max(score, abs(z))
                q1, q3 = _quartiles(hist)
                iqr = q3 - q1
                lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                if value < lo or value > hi:
                    rules.append("iqr")
                    span = max(hi - lo, 1e-9)
                    score = max(score, abs(value - (lo + hi) / 2) / span)
            if rules:
                anomalies.append(
                    {
                        "station_id": station_id,
                        "ts": ts,
                        "metric": metric,
                        "value": value,
                        "rules": rules,
                        "score": round(score, 3),
                    }
                )
    anomalies.sort(key=lambda a: (a["ts"], a["metric"]))
    return anomalies


def detect_all(conn, window=24, z_thresh=3.0, source="sensor"):
    """Run detection over every station's sensor stream in the DB."""
    from . import db as _db

    out = []
    for station in _db.get_stations(conn):
        readings = _db.get_readings(conn, station["id"], source=source)
        out.extend(detect_station(station["id"], readings, window=window, z_thresh=z_thresh))
    return out
