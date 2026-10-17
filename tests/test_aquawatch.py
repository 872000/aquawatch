"""Real behavioral tests for AquaWatch.

Conventions: every synthetic stream is seeded (see aquawatch.synth), so the
"clean" fixtures below are deterministic — verified zero-anomaly streams.
"""

from datetime import datetime, timedelta

import pytest

from aquawatch import alerts as alertmod
from aquawatch import db as dbmod
from aquawatch import detect as detectmod
from aquawatch import ingest as ingestmod
from aquawatch import synth as synthmod
from aquawatch.cli import main as cli_main

TS_FMT = "%Y-%m-%dT%H:%M:%S"
WEEK_START = datetime(2026, 9, 24, 0, 0, 0)

STATION = ("HW-01", "Harbourfront Intake", 43.2707, -79.8671, "sensor")


def make_db(path):
    dbmod.init_db(str(path))
    conn = dbmod.connect(str(path))
    dbmod.add_station(conn, *STATION)
    conn.commit()
    return conn


def store_series(conn, station_id, series, source="sensor"):
    for p in series:
        dbmod.add_reading(conn, station_id, p["ts"], p["ph"], p["turbidity"],
                          source=source)
    conn.commit()


def test_zscore_and_iqr_flag_injected_turbidity_spike(tmp_path):
    """An injected turbidity spike must be flagged by the statistical detectors."""
    conn = make_db(tmp_path / "t.db")
    series = synthmod.generate_series(STATION[0], WEEK_START, 72)
    spike_ts = (WEEK_START + timedelta(hours=50)).strftime(TS_FMT)
    series[50] = {"ts": spike_ts, "ph": 7.2, "turbidity": 45.0, "event_label": None}
    store_series(conn, STATION[0], series)
    readings = dbmod.get_readings(conn, STATION[0])
    anomalies = detectmod.detect_station(STATION[0], readings)
    flagged = [a for a in anomalies if a["ts"] == spike_ts and a["metric"] == "turbidity"]
    assert flagged, "injected turbidity spike was not flagged"
    rules = flagged[0]["rules"]
    assert "zscore" in rules and "iqr" in rules
    conn.close()


def test_clean_stream_produces_no_anomalies(tmp_path):
    """A normal seeded stream (no events) must not raise any anomaly.

    "ST-07" is a fixed seed whose 72h stream was verified anomaly-free;
    the generator is deterministic so this is stable, not luck.
    """
    conn = make_db(tmp_path / "t.db")
    dbmod.add_station(conn, "ST-07", "Clean Fixture", 0.0, 0.0, "sensor")
    conn.commit()
    series = synthmod.generate_series("ST-07", WEEK_START, 72)
    store_series(conn, "ST-07", series)
    readings = dbmod.get_readings(conn, "ST-07")
    anomalies = detectmod.detect_station("ST-07", readings)
    assert anomalies == []
    # And the alert engine stays silent on normal data too.
    assert alertmod.build_alerts(conn, anomalies) == []
    conn.close()


def test_ph_band_guard_flags_out_of_band_ph(tmp_path):
    """pH outside 6.5-8.5 must be flagged as a ph_band violation."""
    conn = make_db(tmp_path / "t.db")
    series = synthmod.generate_series(STATION[0], WEEK_START, 48)
    bad_ts = (WEEK_START + timedelta(hours=30)).strftime(TS_FMT)
    series[30] = {"ts": bad_ts, "ph": 5.0, "turbidity": 1.0, "event_label": None}
    store_series(conn, STATION[0], series)
    readings = dbmod.get_readings(conn, STATION[0])
    anomalies = detectmod.detect_station(STATION[0], readings)
    flagged = [a for a in anomalies if a["ts"] == bad_ts and a["metric"] == "ph"]
    assert flagged and "ph_band" in flagged[0]["rules"]
    # ...while an in-band reading is never a ph_band violation
    in_band = [a for a in anomalies
               if a["metric"] == "ph" and "ph_band" in a["rules"]]
    assert all(a["ts"] == bad_ts for a in in_band)
    conn.close()


def _anom(station_id, hour, metric, value):
    ts = (WEEK_START + timedelta(hours=hour)).strftime(TS_FMT)
    return {"station_id": station_id, "ts": ts, "metric": metric,
            "value": value, "rules": ["zscore"], "score": 4.0}


def test_alert_fires_only_on_consecutive_anomalies(tmp_path):
    """Isolated blips must not raise alerts; 3-in-a-row must."""
    conn = make_db(tmp_path / "t.db")
    # Two isolated anomalies 10h apart -> no alert.
    isolated = [_anom(STATION[0], 10, "turbidity", 6.0),
                _anom(STATION[0], 20, "turbidity", 6.5)]
    assert alertmod.build_alerts(conn, isolated) == []
    assert alertmod.list_alerts(conn) == []
    # Three consecutive hourly anomalies -> exactly one warning alert.
    consecutive = [_anom(STATION[0], 30, "turbidity", 6.0),
                   _anom(STATION[0], 31, "turbidity", 6.2),
                   _anom(STATION[0], 32, "turbidity", 6.1)]
    raised = alertmod.build_alerts(conn, consecutive)
    assert len(raised) == 1
    assert raised[0]["severity"] == "warning"
    assert raised[0]["n_points"] == 3
    conn.close()


def test_alert_severity_critical_for_large_spike(tmp_path):
    """A sustained turbidity spike >= 20 NTU must be critical."""
    conn = make_db(tmp_path / "t.db")
    big = [_anom(STATION[0], h, "turbidity", 45.0 + h) for h in (40, 41, 42, 43)]
    raised = alertmod.build_alerts(conn, big)
    assert len(raised) == 1
    assert raised[0]["severity"] == "critical"
    conn.close()


def test_crowd_report_validation(tmp_path):
    """Invalid crowd reports are rejected; valid ones are stored."""
    conn = make_db(tmp_path / "t.db")
    ts = WEEK_START.strftime(TS_FMT)
    with pytest.raises(ValueError):
        ingestmod.ingest_crowd_report(conn, STATION[0], ts, ph=15.0, reporter="x")
    with pytest.raises(ValueError):
        ingestmod.ingest_crowd_report(conn, STATION[0], ts, turbidity=-2.0, reporter="x")
    with pytest.raises(ValueError):
        ingestmod.ingest_crowd_report(conn, "NOPE", ts, ph=7.0, reporter="x")
    rid = ingestmod.ingest_crowd_report(conn, STATION[0], ts, ph=7.1,
                                        turbidity=1.2, reporter="ava")
    assert rid
    rows = dbmod.get_readings(conn, STATION[0], source="crowd")
    assert len(rows) == 1 and rows[0]["reporter"] == "ava"
    conn.close()


def test_cli_demo_end_to_end(tmp_path):
    """Full demo: 2 scripted events -> 2 critical alerts + charts + dashboard."""
    db_path = tmp_path / "demo.db"
    out = tmp_path / "dash"
    result = cli_main(["--db", str(db_path), "demo", "--out", str(out)])
    assert result["alerts"] == 2, f"expected 2 alerts, got {result['alerts']}"
    assert result["anomalies"] > 10
    conn = dbmod.connect(str(db_path))
    stored = alertmod.list_alerts(conn)
    conn.close()
    assert len(stored) == 2
    assert {a["severity"] for a in stored} == {"critical"}
    assert (out / "index.html").exists()
    for sid in ("HW-01", "HW-02", "HW-03", "HW-04", "HW-05"):
        assert (out / "charts" / f"chart_{sid}.png").exists()


def test_ph_band_guard_flags_out_of_band_reading():
    """A pH reading outside 6.5-8.5 must be flagged by the PH band guard."""
    readings = [
        {"ts": (WEEK_START + timedelta(hours=h)).strftime(TS_FMT),
         "ph": 7.2, "turbidity": 1.0}
        for h in range(24)
    ]
    readings.append({"ts": (WEEK_START + timedelta(hours=24)).strftime(TS_FMT),
                     "ph": 4.1, "turbidity": 1.0})
    anomalies = detectmod.detect_station(STATION[0], readings)
    flagged = [a for a in anomalies if a["metric"] == "ph"]
    assert flagged, "out-of-band pH reading was not flagged"
    assert "ph_band" in flagged[0]["rules"]
