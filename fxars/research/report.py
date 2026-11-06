"""گزارش‌های بک‌تست (Markdown/HTML) با نمودار SVG درون‌خطی."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fxars.domain.models import BacktestRun

LABELS = {
    "net_profit": "سود خالص (پس از هزینه)",
    "return_pct": "بازده درصدی",
    "profit_factor": "Profit Factor",
    "expectancy": "امید ریاضی هر معامله",
    "win_rate": "نرخ برد",
    "avg_win": "میانگین سود",
    "avg_loss": "میانگین زیان",
    "payoff_ratio": "نسبت سود به زیان",
    "max_drawdown": "بیشترین افت (مبلغ)",
    "max_drawdown_pct": "بیشترین افت (درصد)",
    "sharpe": "Sharpe",
    "sortino": "Sortino",
    "calmar": "Calmar",
    "trade_count": "تعداد معاملات",
    "exposure_pct": "درگیری سرمایه",
    "turnover": "گردش معاملات",
    "avg_r": "میانگین R",
    "annualized_return_pct": "بازده سالانه‌شده",
    "bars": "تعداد کندل",
}


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    if isinstance(value, float):
        return f"{value:,.6f}".rstrip("0").rstrip(".")
    return str(value)


# ---------------------------------------------------------------------------
# Regime section
# ---------------------------------------------------------------------------

def _regime_markdown_lines(metrics: dict) -> list[str]:
    rb = metrics.get("regime_breakdown")
    if not rb:
        return []
    lines = [
        "",
        "## تفکیک عملکرد بر اساس رژیم بازار",
        "| رژیم | تعداد | نرخ برد | میانگین PnL | مجموع PnL |",
        "|---|---|---|---|---|",
    ]
    for regime, data in sorted(rb.items()):
        count = int(data.get("count", 0))
        if count == 0:
            continue
        lines.append(
            "| {} | {} | {} | {} | {} |".format(
                regime, count,
                _fmt(data.get("win_rate")),
                _fmt(data.get("avg_pnl")),
                _fmt(data.get("total_pnl")),
            )
        )
    return lines


def _regime_html_card(metrics: dict) -> str:
    rb = metrics.get("regime_breakdown")
    if not rb:
        return ""
    rows = ""
    for regime, data in sorted(rb.items()):
        count = int(data.get("count", 0))
        if count == 0:
            continue
        rows += (
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                regime, count,
                _fmt(data.get("win_rate")),
                _fmt(data.get("avg_pnl")),
                _fmt(data.get("total_pnl")),
            )
        )
    if not rows:
        return ""
    return (
        '<div class="card">'
        "<h2>تفکیک عملکرد بر اساس رژیم بازار</h2>"
        "<table>"
        "<tr><th>رژیم</th><th>تعداد</th><th>نرخ برد</th>"
        "<th>میانگین PnL</th><th>مجموع PnL</th></tr>"
        + rows +
        "</table>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Calibration section
# ---------------------------------------------------------------------------

def _rebuild_calibration_report(cal: dict):
    """Reconstruct a CalibrationReport dataclass from its dict payload."""
    try:
        from fxars.research.calibration import CalibrationBin, CalibrationReport

        bins = [
            CalibrationBin(
                lower=float(b["lower"]),
                upper=float(b["upper"]),
                count=int(b["count"]),
                mean_probability=float(b["mean_probability"]),
                empirical_frequency=float(b["empirical_frequency"]),
            )
            for b in cal.get("bins", [])
        ]
        after = cal.get("after_calibration") or {}
        return CalibrationReport(
            n=int(cal.get("n", 0)),
            brier=float(cal.get("brier", 0.0)),
            log_loss=float(cal.get("log_loss", 0.0)),
            ece=float(cal.get("ece", 0.0)),
            mce=float(cal.get("mce", 0.0)),
            n_bins=int(cal.get("n_bins", 10)),
            bins=bins,
            temperature=cal.get("temperature"),
            brier_after=after.get("brier"),
            log_loss_after=after.get("log_loss"),
            ece_after=after.get("ece"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _calibration_markdown_lines(metrics: dict) -> list[str]:
    cal = metrics.get("calibration")
    if not cal:
        return []
    lines = [
        "",
        "## کالیبراسیون (AC-09)",
        "| شاخص | مقدار |",
        "|---|---|",
        f"| تعداد نمونه | {_fmt(cal.get('n'))} |",
        f"| ECE | {_fmt(cal.get('ece'))} |",
        f"| MCE | {_fmt(cal.get('mce'))} |",
        f"| Brier | {_fmt(cal.get('brier'))} |",
        f"| LogLoss | {_fmt(cal.get('log_loss'))} |",
        f"| Temperature (T) | {_fmt(cal.get('temperature'))} |",
    ]
    after = cal.get("after_calibration") or {}
    if after:
        lines += [
            "",
            "**پس از Temperature Scaling:**",
            f"- ECE: {_fmt(after.get('ece'))}",
            f"- Brier: {_fmt(after.get('brier'))}",
            f"- LogLoss: {_fmt(after.get('log_loss'))}",
        ]
    bins = cal.get("bins") or []
    if bins:
        lines += [
            "",
            "### توزیع binها",
            "| بازه | تعداد | میانگین احتمال | فراوانی تجربی | شکاف |",
            "|---|---|---|---|---|",
        ]
        for item in bins:
            lines.append(
                f"| [{item.get('lower'):.2f}, {item.get('upper'):.2f}) "
                f"| {item.get('count')} "
                f"| {item.get('mean_probability'):.4f} "
                f"| {item.get('empirical_frequency'):.4f} "
                f"| {item.get('gap'):+.4f} |"
            )
    ece_value = cal.get("ece")
    if isinstance(ece_value, int | float):
        verdict = "قابل قبول" if ece_value < 0.10 else "نیازمند بازبینی"
        lines.append(
            f"\n> معیار AC-09: ECE < 0.10 برای نمایش احتمال. "
            f"مقدار فعلی: {verdict}."
        )
    return lines


def _calibration_html_card(metrics: dict) -> str:
    cal = metrics.get("calibration")
    if not cal:
        return ""
    report = _rebuild_calibration_report(cal)
    if report is None:
        return ""
    try:
        from fxars.research.calibration import reliability_diagram_svg
        svg = reliability_diagram_svg(report, width=420, height=380)
    except Exception:
        svg = "<p>نمودار کالیبراسیون در دسترس نیست.</p>"

    after = cal.get("after_calibration") or {}
    after_rows = ""
    if after:
        after_rows = (
            "<h3>پس از Temperature Scaling</h3>"
            "<table>"
            f"<tr><th>ECE</th><td>{_fmt(after.get('ece'))}</td></tr>"
            f"<tr><th>Brier</th><td>{_fmt(after.get('brier'))}</td></tr>"
            f"<tr><th>LogLoss</th><td>{_fmt(after.get('log_loss'))}</td></tr>"
            "</table>"
        )

    bins = cal.get("bins") or []
    bin_rows = "".join(
        f"<tr><td>[{item.get('lower'):.2f}, {item.get('upper'):.2f})</td>"
        f"<td>{item.get('count')}</td>"
        f"<td>{item.get('mean_probability'):.4f}</td>"
        f"<td>{item.get('empirical_frequency'):.4f}</td>"
        f"<td>{item.get('gap'):+.4f}</td></tr>"
        for item in bins
    )
    ece_value = cal.get("ece", 1.0)
    verdict = "قابل قبول" if isinstance(ece_value, int | float) and ece_value < 0.10 else "نیازمند بازبینی"
    verdict_color = "#22c55e" if verdict == "قابل قبول" else "#f59e0b"

    return (
        '<div class="card">'
        "<h2>کالیبراسیون (AC-09)</h2>"
        "<table>"
        f"<tr><th>تعداد نمونه</th><td>{_fmt(cal.get('n'))}</td></tr>"
        f"<tr><th>ECE</th><td>{_fmt(cal.get('ece'))}</td></tr>"
        f"<tr><th>MCE</th><td>{_fmt(cal.get('mce'))}</td></tr>"
        f"<tr><th>Brier</th><td>{_fmt(cal.get('brier'))}</td></tr>"
        f"<tr><th>LogLoss</th><td>{_fmt(cal.get('log_loss'))}</td></tr>"
        f"<tr><th>Temperature</th><td>{_fmt(cal.get('temperature'))}</td></tr>"
        f"<tr><th>وضعیت</th><td style='color:{verdict_color}'>{verdict}</td></tr>"
        "</table>"
        f"{after_rows}"
        f"<div style='margin-top:12px'>{svg}</div>"
        "<h3>توزیع binها</h3>"
        "<table>"
        "<tr><th>بازه</th><th>تعداد</th><th>میانگین احتمال</th>"
        "<th>فراوانی تجربی</th><th>شکاف</th></tr>"
        f"{bin_rows}"
        "</table>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_markdown(run: BacktestRun) -> str:
    metrics = run.metrics
    lines = [
        f"# گزارش بک‌تست — {run.instrument_id} / {run.timeframe}",
        "",
        f"- شناسه اجرا: `{run.run_id}`",
        f"- بازه اعتبارسنجی: `{run.segment.value}`",
        f"- Snapshot داده: `{run.data_snapshot_id}`",
        f"- هش پیکربندی: `{run.config_hash}`",
        f"- نسخه کد: `{run.code_version}` — Seed: `{run.seed}`",
        f"- زمان اجرا: {run.started_at.isoformat()} تا {run.finished_at.isoformat()}",
        "",
        "## معیارهای عملکرد",
        "| شاخص | مقدار |",
        "|---|---|",
    ]
    for key, label in LABELS.items():
        if key in metrics:
            lines.append(f"| {label} | {_fmt(metrics[key])} |")
    if "deflated_sharpe" in metrics:
        dsr = metrics["deflated_sharpe"]
        lines += [
            "",
            "## کنترل بیش‌برازش",
            f"- Sharpe: {_fmt(dsr.get('sharpe'))} — SR0: {_fmt(dsr.get('sr0'))} — "
            f"DSR: {_fmt(dsr.get('dsr'))} — Trials: {_fmt(dsr.get('trials'))}",
            f"- Annualization factor: {_fmt(dsr.get('periods_per_year'))}",
        ]
    lines += _calibration_markdown_lines(metrics)
    lines += _regime_markdown_lines(metrics)
    costs = metrics.get("costs", {})
    lines += [
        "",
        "## تفکیک هزینه‌ها",
        "| نوع | مبلغ |",
        "|---|---|",
        f"| اسپرد | {_fmt(costs.get('spread'))} |",
        f"| کمیسیون | {_fmt(costs.get('commission'))} |",
        f"| سوآپ | {_fmt(costs.get('swap'))} |",
        f"| لغزش | {_fmt(costs.get('slippage'))} |",
        f"| **جمع** | **{_fmt(costs.get('total'))}** |",
        "",
        "## معاملات (حداکثر ۳۰ مورد)",
        "| # | جهت | ورود | خروج | حجم | PnL | R | دلیل خروج |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for index, trade in enumerate(run.trades[:30], start=1):
        lines.append(
            f"| {index} | {trade['direction']} | {trade['entry_time']} | "
            f"{trade['exit_time']} | {trade['volume']} | {_fmt(trade['pnl'])} | "
            f"{_fmt(trade['r_multiple'])} | {trade['exit_reason']} |"
        )
    if len(run.trades) > 30:
        lines.append(f"| … | | | | | | | {len(run.trades) - 30} معامله دیگر |")
    lines += [
        "",
        "> این گزارش خروجی یک سامانه پشتیبانی تصمیم است و تضمین سودآوری یا توصیه سرمایه‌گذاری نیست.",
        "",
    ]
    return "\n".join(lines)


def render_html(run: BacktestRun) -> str:
    metrics = run.metrics
    rows = "".join(
        f"<tr><th>{LABELS.get(key, key)}</th><td>{_fmt(metrics[key])}</td></tr>"
        for key in LABELS if key in metrics
    )
    costs = metrics.get("costs", {})
    cost_rows = "".join(
        f"<tr><th>{label}</th><td>{_fmt(costs.get(key))}</td></tr>"
        for key, label in (
            ("spread", "اسپرد"),
            ("commission", "کمیسیون"),
            ("swap", "سوآپ"),
            ("slippage", "لغزش"),
            ("total", "جمع"),
        )
    )
    trade_rows = "".join(
        f"<tr><td>{index}</td><td>{trade['direction']}</td>"
        f"<td>{trade['entry_time']}</td><td>{trade['exit_time']}</td>"
        f"<td>{trade['volume']}</td><td>{_fmt(trade['pnl'])}</td>"
        f"<td>{_fmt(trade['r_multiple'])}</td><td>{trade['exit_reason']}</td></tr>"
        for index, trade in enumerate(run.trades[:50], start=1)
    )
    chart = svg_equity_curve([(time, float(value)) for time, value in run.equity_curve])
    calibration_card = _calibration_html_card(metrics)
    regime_card = _regime_html_card(metrics)
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>گزارش بک‌تست {run.instrument_id}</title>
<style>
 body{{font-family:Tahoma,Segoe UI,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
 h1,h2{{color:#7dd3fc}} h3{{color:#93c5fd;font-size:14px;margin:12px 0 6px}}
 .card{{background:#111c33;border:1px solid #1e3a5f;border-radius:12px;padding:16px;margin:16px 0}}
 table{{width:100%;border-collapse:collapse}} th,td{{border-bottom:1px solid #1e3a5f;padding:6px 8px;text-align:right;font-size:13px}}
 th{{color:#93c5fd;font-weight:600}} .muted{{color:#94a3b8;font-size:12px}}
</style>
</head>
<body>
<h1>گزارش بک‌تست — {run.instrument_id} / {run.timeframe}</h1>
<p class="muted">شناسه: {run.run_id} — بازه: {run.segment.value} — Snapshot: {run.data_snapshot_id} — Config: {run.config_hash}</p>
<div class="card"><h2>نمودار سرمایه</h2>{chart}</div>
<div class="card"><h2>معیارهای عملکرد</h2><table>{rows}</table></div>
{calibration_card}
{regime_card}
<div class="card"><h2>تفکیک هزینه‌ها</h2><table>{cost_rows}</table></div>
<div class="card"><h2>معاملات</h2><table>
<tr><th>#</th><th>جهت</th><th>ورود</th><th>خروج</th><th>حجم</th><th>PnL</th><th>R</th><th>دلیل خروج</th></tr>
{trade_rows}</table></div>
<p class="muted">این گزارش خروجی سامانه پشتیبانی تصمیم است و تضمین سودآوری یا توصیه سرمایه‌گذاری نیست.</p>
</body></html>"""


def svg_equity_curve(points: list[tuple[str, float]], *, width: int = 860, height: int = 260) -> str:
    if len(points) < 2:
        return "<p>داده کافی برای نمودار موجود نیست.</p>"
    values = [value for _, value in points]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    pad = 24
    usable_w = width - pad * 2
    usable_h = height - pad * 2
    coords = []
    for index, value in enumerate(values):
        x = pad + usable_w * index / (len(values) - 1)
        y = pad + usable_h * (1 - (value - low) / span)
        coords.append(f"{x:.1f},{y:.1f}")
    color = "#22c55e" if values[-1] >= values[0] else "#ef4444"
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#0b1220"/>'
        f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="2"/>'
        f'<text x="{pad}" y="{pad - 6}" fill="#94a3b8" font-size="12">peak {high:,.2f}</text>'
        f'<text x="{pad}" y="{height - 8}" fill="#94a3b8" font-size="12">trough {low:,.2f}</text>'
        f"</svg>"
    )


def write_report(run: BacktestRun, directory: str | Path, *, formats: tuple[str, ...] = ("md", "html")) -> dict[str, str]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    if "md" in formats:
        path = target / f"backtest_{run.run_id}.md"
        path.write_text(render_markdown(run), encoding="utf-8")
        outputs["markdown"] = str(path)
    if "html" in formats:
        path = target / f"backtest_{run.run_id}.html"
        path.write_text(render_html(run), encoding="utf-8")
        outputs["html"] = str(path)
    return outputs
