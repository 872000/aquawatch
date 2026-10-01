"""AquaWatch CLI.

Usage examples:
  python3 -m aquawatch.cli demo
  python3 -m aquawatch.cli alerts --db aquawatch.db
  python3 -m aquawatch.cli ingest-report --db aquawatch.db --station HW-01 \\
      --ph 7.1 --turbidity 1.3 --reporter "Ava"
"""

import argparse
import os
from datetime import datetime, timedelta, timezone

from . import alerts as alertmod
from . import charts as chartmod
from . import dashboard as dashmod
from . import db as dbmod
from . import detect as detectmod
from . import ingest as ingestmod
from . import synth as synthmod

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
DATA = os.path.join(PROJECT, "data")


def cmd_init_db(args):
    dbmod.init_db(args.db)
    n = ingestmod.load_stations_csv(dbmod.connect(args.db),
                                    os.path.join(DATA, "stations.csv"))
    print(f"initialized {args.db} with {n} stations")


def cmd_ingest_week(args):
    conn = dbmod.connect(args.db)
    events = ingestmod.load_events_json(os.path.join(DATA, "events.json"))
    start = synthmod.utc_week_start(args.hours)
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%dT%H:%M:%S")
    stations = [s["id"] for s in dbmod.get_stations(conn)]
    n = ingestmod.ingest_synth(conn, stations, start, args.hours, events=events)
    conn.close()
    print(f"ingested {n} synthetic sensor readings "
          f"({args.hours}h x {len(stations)} stations), {len(events)} scripted events")


def cmd_ingest_report(args):
    conn = dbmod.connect(args.db)
    ts = args.ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    rid = ingestmod.ingest_crowd_report(conn, args.station, ts, args.ph,
                                        args.turbidity, args.reporter)
    conn.close()
    print(f"stored crowd report #{rid} for {args.station} @ {ts}")


def cmd_detect(args):
    conn = dbmod.connect(args.db)
    anomalies = detectmod.detect_all(conn)
    conn.close()
    print(f"{len(anomalies)} anomalies detected")
    for a in anomalies[:25]:
        print(f"  {a['ts']} {a['station_id']} {a['metric']}={a['value']} "
              f"rules={','.join(a['rules'])} score={a['score']}")
    if len(anomalies) > 25:
        print(f"  ... and {len(anomalies) - 25} more")
    return anomalies


def cmd_analyze(args):
    conn = dbmod.connect(args.db)
    anomalies = detectmod.detect_all(conn)
    dbmod.clear_alerts(conn)
    new_alerts = alertmod.build_alerts(conn, anomalies)
    conn.close()
    print(f"analysis: {len(anomalies)} anomalies -> {len(new_alerts)} alerts")
    for a in new_alerts:
        alertmod.notify(a)
    return new_alerts


def cmd_alerts(args):
    conn = dbmod.connect(args.db)
    rows = alertmod.list_alerts(conn)
    conn.close()
    if not rows:
        print("no alerts stored (run `analyze` first)")
        return
    print(f"{len(rows)} alert(s):")
    for r in rows:
        print(f"  [#{r['id']}] {r['severity'].upper():8} {r['station_name']} "
              f"{r['start_ts']} -> {r['end_ts']}\n      {r['summary']}")


def cmd_chart(args):
    conn = dbmod.connect(args.db)
    stations = dbmod.get_stations(conn)
    targets = [s for s in stations if not args.station or s["id"] == args.station]
    os.makedirs(args.out, exist_ok=True)
    for s in targets:
        readings = dbmod.get_readings(conn, s["id"], source="sensor")
        anomalies = detectmod.detect_station(s["id"], readings)
        path = os.path.join(args.out, f"chart_{s['id']}.png")
        chartmod.station_chart(s, readings, anomalies, path)
        print(f"wrote {path}")
    conn.close()


def cmd_dashboard(args):
    conn = dbmod.connect(args.db)
    os.makedirs(args.out, exist_ok=True)
    chart_paths = {}
    for s in dbmod.get_stations(conn):
        readings = dbmod.get_readings(conn, s["id"], source="sensor")
        anomalies = detectmod.detect_station(s["id"], readings)
        tmp = os.path.join(args.out, f".chart_{s['id']}.png")
        chartmod.station_chart(s, readings, anomalies, tmp)
        chart_paths[s["id"]] = tmp
    page = dashmod.generate(conn, args.out, chart_paths)
    for tmp in chart_paths.values():
        os.remove(tmp)
    conn.close()
    print(f"dashboard written to {page}")


def cmd_demo(args):
    """End-to-end demo: synthetic week + 2 scripted events -> alerts -> dashboard."""
    if os.path.exists(args.db):
        os.remove(args.db)
    dbmod.init_db(args.db)
    conn = dbmod.connect(args.db)
    ingestmod.load_stations_csv(conn, os.path.join(DATA, "stations.csv"))
    events = ingestmod.load_events_json(os.path.join(DATA, "events.json"))

    start = synthmod.utc_week_start(168)
    stations = [s["id"] for s in dbmod.get_stations(conn)]
    n = ingestmod.ingest_synth(conn, stations, start, 168, events=events)
    print(f"[demo] ingested {n} sensor readings across {len(stations)} stations")
    for e in events:
        print(f"[demo] scripted event: {e['label']} @ {e['station_id']} "
              f"(hour {e['start_hour']}, {e['duration_h']}h)")

    # A few crowd-sourced reports, including one corroborating the turbidity event.
    evt_ts = (start + timedelta(hours=events[0]["start_hour"] + 2)).strftime(
        "%Y-%m-%dT%H:%M:%S")
    ok_ts = (start + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S")
    ingestmod.ingest_crowd_report(conn, events[0]["station_id"], evt_ts,
                                  ph=7.0, turbidity=52.0, reporter="sam_riverkeeper")
    ingestmod.ingest_crowd_report(conn, "HW-04", ok_ts, ph=7.3, turbidity=1.1,
                                  reporter="ava_hikes")
    ingestmod.ingest_crowd_report(conn, "HW-02", ok_ts, ph=7.1, turbidity=0.8,
                                  reporter="marcus_fishes")
    crowd = [r for r in dbmod.get_readings(conn, events[0]["station_id"], source="crowd")]
    print(f"[demo] ingested 3 crowd reports (1 corroborates the turbidity event)")

    anomalies = detectmod.detect_all(conn)
    print(f"[demo] detectors flagged {len(anomalies)} anomalies")
    dbmod.clear_alerts(conn)
    new_alerts = alertmod.build_alerts(conn, anomalies)
    print(f"[demo] alert engine raised {len(new_alerts)} alerts:")
    for a in new_alerts:
        alertmod.notify(a)
    conn.close()

    out = os.path.abspath(args.out)
    cmd_dashboard(argparse.Namespace(db=args.db, out=out))
    print(f"[demo] done — open {os.path.join(out, 'index.html')}")
    return {"readings": n, "anomalies": len(anomalies), "alerts": len(new_alerts)}


def build_parser():
    p = argparse.ArgumentParser(prog="aquawatch", description="AquaWatch water-quality monitor")
    p.add_argument("--db", default="aquawatch.db", help="SQLite database path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create DB and load stations")
    w = sub.add_parser("ingest-week", help="ingest a synthetic week of sensor data")
    w.add_argument("--hours", type=int, default=168)
    w.add_argument("--start", help="week start, %%Y-%%m-%%dT%%H:%%M:%%S (default: 7d ago)")
    r = sub.add_parser("ingest-report", help="submit a crowd-sourced report")
    r.add_argument("--station", required=True)
    r.add_argument("--ph", type=float, default=None)
    r.add_argument("--turbidity", type=float, default=None)
    r.add_argument("--reporter", default="anonymous")
    r.add_argument("--ts", default=None)
    sub.add_parser("detect", help="run anomaly detectors and print results")
    sub.add_parser("analyze", help="detect + raise alerts + simulated notifications")
    sub.add_parser("alerts", help="list stored alerts")
    c = sub.add_parser("chart", help="render station chart(s)")
    c.add_argument("--station", default=None)
    c.add_argument("--out", default="charts")
    d = sub.add_parser("dashboard", help="generate the HTML dashboard")
    d.add_argument("--out", default="dashboard")
    m = sub.add_parser("demo", help="full end-to-end demo")
    m.add_argument("--out", default="demo_output")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return {
        "init-db": cmd_init_db, "ingest-week": cmd_ingest_week,
        "ingest-report": cmd_ingest_report, "detect": cmd_detect,
        "analyze": cmd_analyze, "alerts": cmd_alerts, "chart": cmd_chart,
        "dashboard": cmd_dashboard, "demo": cmd_demo,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
