"""Metrics dashboard HTML renderer (P5-4)."""
from __future__ import annotations

from typing import Any


def _escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_counters(counters: list[dict[str, Any]]) -> str:
    if not counters:
        return "<p class='muted'>هیچ شمارنده‌ای ثبت نشده است.</p>"
    rows = []
    for item in counters:
        labels = ", ".join(f"{k}={v}" for k, v in item.get("labels", {}).items()) or "—"
        rows.append(
            "<tr>"
            f"<td>{_escape(item.get('name', ''))}</td>"
            f"<td dir='ltr'>{_escape(labels)}</td>"
            f"<td>{_escape(item.get('value', 0))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>نام</th><th>برچسب‌ها</th><th>مقدار</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _render_gauges(gauges: list[dict[str, Any]]) -> str:
    if not gauges:
        return "<p class='muted'>هیچ gauge‌ای ثبت نشده است.</p>"
    rows = []
    for item in gauges:
        labels = ", ".join(f"{k}={v}" for k, v in item.get("labels", {}).items()) or "—"
        rows.append(
            "<tr>"
            f"<td>{_escape(item.get('name', ''))}</td>"
            f"<td dir='ltr'>{_escape(labels)}</td>"
            f"<td>{_escape(item.get('value', 0))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<thead><tr><th>نام</th><th>برچسب‌ها</th><th>مقدار</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def _render_histograms(histograms: list[dict[str, Any]]) -> str:
    if not histograms:
        return "<p class='muted'>هیچ هیستوگرامی ثبت نشده است.</p>"
    parts = []
    for item in histograms:
        labels = ", ".join(f"{k}={v}" for k, v in item.get("labels", {}).items()) or "—"
        count = item.get("count", 0)
        total = item.get("sum", 0.0)
        mean = (total / count) if count else 0.0
        buckets = item.get("buckets", {})
        bucket_rows = "".join(
            f"<tr><td dir='ltr'>{_escape(k)}</td><td>{_escape(v)}</td></tr>"
            for k, v in sorted(
                buckets.items(),
                key=lambda kv: float(kv[0]) if kv[0] != "inf" else 1e18,
            )
        )
        parts.append(
            "<div class='histogram'>"
            f"<h3 dir='ltr'>{_escape(item.get('name', ''))}</h3>"
            f"<p class='muted'>labels: <code dir='ltr'>{_escape(labels)}</code></p>"
            f"<p>count: <b>{count}</b> — sum: <b>{total:.4f}</b> — mean: <b>{mean:.4f}</b></p>"
            "<table><thead><tr><th>le</th><th>count</th></tr></thead>"
            f"<tbody>{bucket_rows}</tbody></table>"
            "</div>"
        )
    return "".join(parts)


def render_metrics_dashboard(snapshot: dict[str, Any], *, prometheus_text: str = "") -> str:
    """Render the metrics snapshot as HTML."""
    uptime = snapshot.get("uptime_seconds", 0)
    counters = snapshot.get("counters", [])
    gauges = snapshot.get("gauges", [])
    histograms = snapshot.get("histograms", [])

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>FX-ARS — Metrics Dashboard</title>
<style>
 body{{font-family:Tahoma,Segoe UI,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
 h1,h2{{color:#7dd3fc}}
 h3{{color:#93c5fd;font-size:14px;margin:12px 0 6px}}
 .card{{background:#111c33;border:1px solid #1e3a5f;border-radius:12px;padding:16px;margin:16px 0}}
 table{{width:100%;border-collapse:collapse;margin-top:8px}}
 th,td{{border-bottom:1px solid #1e3a5f;padding:6px 8px;text-align:right;font-size:13px}}
 th{{color:#93c5fd;font-weight:600}}
 .muted{{color:#94a3b8;font-size:12px}}
 code{{background:#0a1428;padding:2px 6px;border-radius:6px;font-size:12px}}
 .histogram{{margin-bottom:16px;padding-bottom:12px;border-bottom:1px dashed #1e3a5f}}
 .summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}
 .summary .box{{background:#0a1428;padding:12px;border-radius:10px;border:1px solid #1e3a5f}}
 .summary .box .label{{color:#94a3b8;font-size:12px}}
 .summary .box .value{{font-size:24px;color:#7dd3fc;font-weight:bold}}
 pre{{white-space:pre-wrap;background:#0a1428;padding:12px;border-radius:8px;font-size:12px;max-height:400px;overflow:auto}}
</style>
</head>
<body>
<h1>FX-ARS — Metrics Dashboard</h1>
<p class="muted">Snapshot از MetricsRegistry — برای Prometheus در <a href="/api/v1/metrics" style="color:#7dd3fc">/api/v1/metrics</a></p>

<div class="card">
  <h2>خلاصه</h2>
  <div class="summary">
    <div class="box"><div class="label">Uptime (seconds)</div><div class="value">{uptime:.1f}</div></div>
    <div class="box"><div class="label">Counters</div><div class="value">{len(counters)}</div></div>
    <div class="box"><div class="label">Gauges</div><div class="value">{len(gauges)}</div></div>
    <div class="box"><div class="label">Histograms</div><div class="value">{len(histograms)}</div></div>
  </div>
</div>

<div class="card">
  <h2>Counters</h2>
  {_render_counters(counters)}
</div>

<div class="card">
  <h2>Gauges</h2>
  {_render_gauges(gauges)}
</div>

<div class="card">
  <h2>Histograms</h2>
  {_render_histograms(histograms)}
</div>

<div class="card">
  <h2>Prometheus Text (خام)</h2>
  <pre>{_escape(prometheus_text[:5000]) if prometheus_text else '(داده‌ای موجود نیست)'}</pre>
</div>

<p class="muted">این صفحه در حالت MVP-1 فقط‌خواندنی است. برای integration با Prometheus/Grafana از <code>/api/v1/metrics</code> استفاده کنید.</p>
</body>
</html>"""