"""Static HTML dashboard: station grid, recent alerts, embedded charts."""

import html
import shutil
from pathlib import Path

from . import db as _db


def _card(station, latest, status):
    color = {"critical": "#d32f2f", "warning": "#f9a825", "ok": "#2e7d32"}[status]
    badge = {"critical": "CRITICAL", "warning": "WARNING", "ok": "OK"}[status]
    ph = f"{latest['ph']:.2f}" if latest and latest.get("ph") is not None else "—"
    tb = f"{latest['turbidity']:.1f}" if latest and latest.get("turbidity") is not None else "—"
    ts = latest["ts"] if latest else "—"
    return f"""
    <div class="card">
      <div class="card-head"><span>{html.escape(station['name'])}</span>
        <span class="badge" style="background:{color}">{badge}</span></div>
      <div class="card-body">
        <div class="metric"><span>pH</span><b>{ph}</b></div>
        <div class="metric"><span>Turbidity</span><b>{tb} NTU</b></div>
        <div class="meta">{html.escape(station['id'])} · {ts} UTC</div>
      </div>
      <img src="charts/chart_{html.escape(station['id'])}.png" alt="chart">
    </div>"""


def generate(conn, out_dir, chart_paths):
    """Write dashboard index.html into out_dir; copy charts into out_dir/charts."""
    out_dir = Path(out_dir)
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    for sid, src in chart_paths.items():
        shutil.copy(src, charts_dir / f"chart_{sid}.png")

    stations = _db.get_stations(conn)
    alerts = _db.get_alerts(conn)
    latest_alert_sev = {}
    for a in alerts:
        latest_alert_sev.setdefault(a["station_id"], a["severity"])

    cards = []
    for s in stations:
        readings = _db.get_readings(conn, s["id"], source="sensor")
        latest = readings[-1] if readings else None
        sev = latest_alert_sev.get(s["id"])
        status = "critical" if sev == "critical" else "warning" if sev == "warning" else "ok"
        cards.append(_card(s, latest, status))

    rows = []
    for a in alerts[:20]:
        rows.append(
            f"<tr><td>{html.escape(a['station_name'])}</td>"
            f"<td class='sev-{a['severity']}'>{a['severity'].upper()}</td>"
            f"<td>{a['start_ts']}</td><td>{a['end_ts']}</td>"
            f"<td>{html.escape(a['summary'] or '')}</td></tr>"
        )
    alerts_html = (
        "<table><tr><th>Station</th><th>Severity</th><th>Start</th><th>End</th>"
        "<th>Summary</th></tr>" + "".join(rows) + "</table>"
        if rows else "<p>No alerts. All stations nominal.</p>"
    )

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>AquaWatch Dashboard</title>
<style>
body{{font-family:system-ui,Arial,sans-serif;margin:0;background:#eef4f7;color:#123}}
header{{background:#01579b;color:#fff;padding:18px 28px}}
header h1{{margin:0;font-size:26px}} header p{{margin:4px 0 0;opacity:.85}}
main{{padding:20px 28px;max-width:1200px;margin:auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:18px}}
.card{{background:#fff;border-radius:10px;box-shadow:0 2px 6px #0002;overflow:hidden}}
.card-head{{display:flex;justify-content:space-between;align-items:center;
  padding:10px 14px;font-weight:700;background:#e1f0fa}}
.badge{{color:#fff;font-size:11px;padding:3px 10px;border-radius:20px}}
.card-body{{padding:10px 14px}} .metric{{display:flex;justify-content:space-between;
  padding:3px 0;font-size:15px}} .meta{{color:#567;font-size:12px;margin-top:4px}}
.card img{{width:100%;display:block}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px}}
th,td{{padding:8px 10px;border-bottom:1px solid #dde;text-align:left}}
.sev-critical{{color:#d32f2f;font-weight:700}} .sev-warning{{color:#b26a00;font-weight:700}}
footer{{padding:16px 28px;color:#567;font-size:12px}}
.note{{background:#fff8e1;border-left:4px solid #f9a825;padding:10px 14px;margin:16px 0;font-size:13px}}
</style></head>
<body>
<header><h1>🌊 AquaWatch</h1>
<p>Crowd-sourced water-quality monitoring · UN SDG 6: Clean Water &amp; Sanitation</p></header>
<main>
<div class="note"><b>Note:</b> the pH 6.5–8.5 reference band is a general guideline shown
for context only — <b>not medical advice</b>. Confirm water safety with your local utility.</div>
<h2>Monitoring stations</h2>
<div class="grid">{''.join(cards)}</div>
<h2>Recent alerts</h2>
{alerts_html}
</main>
<footer>AquaWatch v0.1.0 · synthetic demo data · offline, no API keys</footer>
</body></html>"""
    path = out_dir / "index.html"
    path.write_text(page, encoding="utf-8")
    return str(path)
