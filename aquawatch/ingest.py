"""Report ingestion: crowd-sourced reports + synthetic sensor streams."""

import csv
import json

from . import db
from . import synth


def load_stations_csv(conn, path):
    """Load monitoring stations from a CSV with columns: id,name,lat,lon,kind."""
    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db.add_station(
                conn,
                row["id"].strip(),
                row["name"].strip(),
                float(row["lat"]) if row.get("lat") else None,
                float(row["lon"]) if row.get("lon") else None,
                (row.get("kind") or "sensor").strip(),
            )
            count += 1
    conn.commit()
    return count


def load_events_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ingest_synth(conn, station_ids, start, hours, events=()):
    """Generate and store a seeded synthetic sensor stream for each station."""
    total = 0
    for sid in station_ids:
        for point in synth.generate_series(sid, start, hours, events=events):
            db.add_reading(conn, sid, point["ts"], point["ph"], point["turbidity"],
                           source="sensor")
            total += 1
    conn.commit()
    return total


def ingest_crowd_report(conn, station_id, ts, ph=None, turbidity=None, reporter="anonymous"):
    """Validate and store one crowd-sourced water-quality report.

    Raises ValueError on invalid values or unknown station.
    """
    stations = {s["id"] for s in db.get_stations(conn)}
    if station_id not in stations:
        raise ValueError(f"unknown station_id: {station_id!r}")
    if ph is not None and not (0.0 <= ph <= 14.0):
        raise ValueError(f"pH must be within 0-14, got {ph}")
    if turbidity is not None and turbidity < 0:
        raise ValueError(f"turbidity must be >= 0 NTU, got {turbidity}")
    if ph is None and turbidity is None:
        raise ValueError("report must include pH and/or turbidity")
    rid = db.add_reading(conn, station_id, ts, ph, turbidity,
                         source="crowd", reporter=reporter)
    conn.commit()
    return rid


def load_crowd_csv(conn, path):
    """Load sample crowd reports from CSV: station_id,ts,ph,turbidity,reporter."""
    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ph = float(row["ph"]) if row.get("ph") else None
            tb = float(row["turbidity"]) if row.get("turbidity") else None
            ingest_crowd_report(
                conn, row["station_id"].strip(), row["ts"].strip(),
                ph, tb, (row.get("reporter") or "anonymous").strip(),
            )
            count += 1
    return count
