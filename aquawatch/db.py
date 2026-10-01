"""SQLite storage layer for AquaWatch.

Tables:
  stations  - monitoring stations (id, name, lat, lon, kind)
  readings  - time-stamped water-quality readings (station_id, ts, ph, turbidity, source, reporter)
  alerts    - contamination alerts raised by the alert engine
"""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat  REAL,
    lon  REAL,
    kind TEXT NOT NULL DEFAULT 'sensor'
);
CREATE TABLE IF NOT EXISTS readings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL REFERENCES stations(id),
    ts         TEXT NOT NULL,
    ph         REAL,
    turbidity  REAL,
    source     TEXT NOT NULL DEFAULT 'sensor',
    reporter   TEXT,
    UNIQUE (station_id, ts, source)
);
CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL REFERENCES stations(id),
    start_ts   TEXT NOT NULL,
    end_ts     TEXT NOT NULL,
    severity   TEXT NOT NULL,
    summary    TEXT,
    status     TEXT NOT NULL DEFAULT 'open'
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def add_station(conn, station_id, name, lat=None, lon=None, kind="sensor"):
    conn.execute(
        "INSERT OR REPLACE INTO stations (id, name, lat, lon, kind) VALUES (?, ?, ?, ?, ?)",
        (station_id, name, lat, lon, kind),
    )


def add_reading(conn, station_id, ts, ph=None, turbidity=None, source="sensor", reporter=None):
    cur = conn.execute(
        """INSERT OR IGNORE INTO readings
           (station_id, ts, ph, turbidity, source, reporter)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (station_id, ts, ph, turbidity, source, reporter),
    )
    return cur.lastrowid


def get_stations(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM stations ORDER BY id")]


def get_readings(conn, station_id, source=None):
    q = "SELECT * FROM readings WHERE station_id = ?"
    params = [station_id]
    if source:
        q += " AND source = ?"
        params.append(source)
    q += " ORDER BY ts"
    return [dict(r) for r in conn.execute(q, params)]


def add_alert(conn, station_id, start_ts, end_ts, severity, summary, status="open"):
    cur = conn.execute(
        """INSERT INTO alerts (station_id, start_ts, end_ts, severity, summary, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (station_id, start_ts, end_ts, severity, summary, status),
    )
    return cur.lastrowid


def get_alerts(conn, status=None):
    q = """SELECT a.*, s.name AS station_name FROM alerts a
           JOIN stations s ON s.id = a.station_id"""
    params = []
    if status:
        q += " WHERE a.status = ?"
        params.append(status)
    q += " ORDER BY a.start_ts DESC"
    return [dict(r) for r in conn.execute(q, params)]


def clear_alerts(conn):
    conn.execute("DELETE FROM alerts")
