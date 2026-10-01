"""Seeded synthetic sensor stream for AquaWatch.

Generates plausible hourly sensor data per monitoring station. A stable hash of
the station id seeds the RNG, so the stream is deterministic and reproducible.
Scripted "contamination events" can be overlaid to simulate incidents.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np

TS_FMT = "%Y-%m-%dT%H:%M:%S"


def _rng(seed_str):
    digest = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:16]
    return np.random.default_rng(int(digest, 16) % (2 ** 63))


def generate_series(station_id, start, hours, events=(), seed_salt="aquawatch-v1"):
    """Generate ``hours`` hourly readings starting at ``start`` (datetime).

    events: iterable of dicts with keys:
        station_id, start_hour (offset from start), duration_h, metric
        ("turbidity" or "ph"), level (target value during the event),
        label (optional description).
    Returns a list of dicts: {"ts", "ph", "turbidity"}.
    """
    rng = _rng(f"{seed_salt}:{station_id}")
    events = [e for e in events if e.get("station_id") == station_id]

    series = []
    for h in range(hours):
        ts = start + timedelta(hours=h)
        # Baseline: gentle diurnal wobble + sensor noise.
        ph = 7.2 + 0.05 * np.sin(2 * np.pi * h / 24.0) + rng.normal(0, 0.10)
        turbidity = abs(rng.normal(0.9, 0.30))
        label = None
        for e in events:
            if e["start_hour"] <= h < e["start_hour"] + e["duration_h"]:
                if e["metric"] == "turbidity":
                    turbidity = abs(e["level"] + rng.normal(0, 2.0))
                elif e["metric"] == "ph":
                    ph = e["level"] + rng.normal(0, 0.08)
                label = e.get("label")
        series.append(
            {
                "ts": ts.strftime(TS_FMT),
                "ph": round(float(ph), 2),
                "turbidity": round(float(turbidity), 2),
                "event_label": label,
            }
        )
    return series


def utc_week_start(hours=168):
    """Start timestamp for a synthetic week ending at the current hour (UTC)."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return (now - timedelta(hours=hours)).replace(tzinfo=None)
