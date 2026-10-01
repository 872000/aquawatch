"""Alert engine for AquaWatch.

ConsecutiveAnomalyAlerter: groups a station's anomalies into clusters of
temporally adjacent anomalous timestamps. A cluster becomes an alert only when
it contains at least ``min_consecutive`` anomalous timestamps within
``max_gap_h`` hours of each other — isolated blips never page anyone.

Severity:
  critical — turbidity peak >= 20 NTU, or pH < 6.0 / > 9.0 inside the cluster
  warning  — a sustained cluster that does not meet critical thresholds
"""

from datetime import datetime

from . import db as _db
from .detect import PH_BAND

TS_FMT = "%Y-%m-%dT%H:%M:%S"
CRITICAL_TURBIDITY_NTU = 20.0


def _parse(ts):
    return datetime.strptime(ts, TS_FMT)


def build_alerts(conn, anomalies, min_consecutive=3, max_gap_h=2):
    """Cluster anomalies -> alerts. Stores alerts, returns alert dicts."""
    by_station = {}
    for a in anomalies:
        by_station.setdefault(a["station_id"], []).append(a)

    stations = {s["id"]: s["name"] for s in _db.get_stations(conn)}
    alerts = []
    for station_id, items in sorted(by_station.items()):
        # One entry per anomalous timestamp (a ts may flag both metrics).
        by_ts = {}
        for a in items:
            by_ts.setdefault(a["ts"], []).append(a)
        times = sorted(by_ts)

        clusters, current = [], []
        for ts in times:
            if current and (_parse(ts) - _parse(current[-1])).total_seconds() / 3600 > max_gap_h:
                clusters.append(current)
                current = []
            current.append(ts)
        if current:
            clusters.append(current)

        for cluster in clusters:
            if len(cluster) < min_consecutive:
                continue  # isolated blips do not raise alerts
            member = [a for ts in cluster for a in by_ts[ts]]
            turbs = [a["value"] for a in member if a["metric"] == "turbidity"]
            phs = [a["value"] for a in member if a["metric"] == "ph"]
            peak_turb = max(turbs) if turbs else 0.0
            worst_ph = min(phs, key=lambda v: abs(v - 7.5)) if phs else 7.5
            critical = (
                peak_turb >= CRITICAL_TURBIDITY_NTU
                or worst_ph < 6.0
                or worst_ph > 9.0
            )
            severity = "critical" if critical else "warning"
            metrics = sorted({a["metric"] for a in member})
            summary = (
                f"{'/'.join(metrics)} anomaly at {stations.get(station_id, station_id)}: "
                f"{len(cluster)} consecutive anomalous readings "
                f"(peak turbidity {peak_turb:.1f} NTU, worst pH {worst_ph:.2f}; "
                f"pH {PH_BAND[0]}-{PH_BAND[1]} is a guideline band, not medical advice)"
            )
            aid = _db.add_alert(conn, station_id, cluster[0], cluster[-1], severity, summary)
            alerts.append(
                {
                    "id": aid,
                    "station_id": station_id,
                    "station_name": stations.get(station_id, station_id),
                    "start_ts": cluster[0],
                    "end_ts": cluster[-1],
                    "severity": severity,
                    "summary": summary,
                    "n_points": len(cluster),
                }
            )
    conn.commit()
    return alerts


def notify(alert):
    """Simulated notification (console). Returns the message string."""
    icon = "🚨" if alert["severity"] == "critical" else "⚠️"
    msg = (
        f"{icon} [SIMULATED ALERT — no real message sent]\n"
        f"  Severity : {alert['severity'].upper()}\n"
        f"  Station  : {alert['station_name']} ({alert['station_id']})\n"
        f"  Window   : {alert['start_ts']} → {alert['end_ts']}\n"
        f"  Details  : {alert['summary']}"
    )
    print(msg)
    return msg


def list_alerts(conn):
    return _db.get_alerts(conn)
