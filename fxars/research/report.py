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
            f"- Sharpe: {_fmt(dsr.get('sharpe'))} — SR0: {_fmt(dsr.get('sr0'))} — DSR: {_fmt(dsr.get('dsr'))} — Trials: {_fmt(dsr.get('trials'))}",
        ]
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
            f"| {index} | {trade['direction']} | {trade['entry_time']} | {trade['exit_time']} | "
            f"{trade['volume']} | {_fmt(trade['pnl'])} | {_fmt(trade['r_multiple'])} | {trade['exit_reason']} |"
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
    cost_rows = "".join(f"<tr><th>{label}</th><td>{_fmt(costs.get(key))}</td></tr>"
                        for key, label in (("spread", "اسپرد"), ("commission", "کمیسیون"),
                                           ("swap", "سوآپ"), ("slippage", "لغزش"), ("total", "جمع")))
    trade_rows = "".join(
        f"<tr><td>{index}</td><td>{trade['direction']}</td><td>{trade['entry_time']}</td>"
        f"<td>{trade['exit_time']}</td><td>{trade['volume']}</td><td>{_fmt(trade['pnl'])}</td>"
        f"<td>{_fmt(trade['r_multiple'])}</td><td>{trade['exit_reason']}</td></tr>"
        for index, trade in enumerate(run.trades[:50], start=1)
    )
    chart = svg_equity_curve([(time, float(value)) for time, value in run.equity_curve])
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>گزارش بک‌تست {run.instrument_id}</title>
<style>
 body{{font-family:Tahoma,Segoe UI,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}}
 h1,h2{{color:#7dd3fc}} .card{{background:#111c33;border:1px solid #1e3a5f;border-radius:12px;padding:16px;margin:16px 0}}
 table{{width:100%;border-collapse:collapse}} th,td{{border-bottom:1px solid #1e3a5f;padding:6px 8px;text-align:right;font-size:13px}}
 th{{color:#93c5fd;font-weight:600}} .muted{{color:#94a3b8;font-size:12px}}
</style>
</head>
<body>
<h1>گزارش بک‌تست — {run.instrument_id} / {run.timeframe}</h1>
<p class="muted">شناسه: {run.run_id} — بازه: {run.segment.value} — Snapshot: {run.data_snapshot_id} — Config: {run.config_hash}</p>
<div class="card"><h2>نمودار سرمایه</h2>{chart}</div>
<div class="card"><h2>معیارهای عملکرد</h2><table>{rows}</table></div>
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
