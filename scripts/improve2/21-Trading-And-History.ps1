# scripts/improve2/21-Trading-And-History.ps1
#Requires -Version 7.0
<#
.SYNOPSIS
    گام ۲۱: افزودن تب معاملات + تب دانلود هیستوری به داشبورد.
.DESCRIPTION
    1) ساخت fxars/api/trading.py
    2) patch server.py (register trading routes)
    3) بازنویسی dashboard.py با ۹ تب
    4) patch cli/main.py (download command)
    5) gitignore data/history
    6) py_compile + تست
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\project\FX',
    [switch]$DryRun,
    [switch]$NoPause
)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# fallback برای $PSScriptRoot
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

# helperهای محلی (بدون وابستگی به _common.ps1)
function Write-Ok    ($m) { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Warn2 ($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Err   ($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Write-Skip  ($m) { Write-Host "  [SKIP] $m" -ForegroundColor DarkGray }
function Pause-IfNeeded {
    param([switch]$NoPause)
    if ($NoPause) { return }
    if ([Console]::IsInputRedirected) { return }
    Write-Host "`nبرای بستن پنجره Enter بزنید..." -ForegroundColor DarkGray
    try { Read-Host | Out-Null } catch { }
}

# اگر _common.ps1 موجود بود، آن را import کن
$CommonPath = Join-Path $ScriptDir '_common.ps1'
if (Test-Path $CommonPath) {
    . $CommonPath
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $ProjectRoot ".fix-backups\improve2\trading-history-$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null

function Backup-File {
    param([string]$RelPath)
    $full = Join-Path $ProjectRoot $RelPath
    if (-not (Test-Path $full)) { return }
    $dst = Join-Path $backup $RelPath
    New-Item -ItemType Directory -Path (Split-Path $dst -Parent) -Force | Out-Null
    Copy-Item $full $dst -Force
    Write-Ok "backup: $RelPath"
}

function Restore-File {
    param([string]$RelPath)
    $full = Join-Path $ProjectRoot $RelPath
    $src = Join-Path $backup $RelPath
    if (-not (Test-Path $src)) { Write-Err "backup پیدا نشد: $RelPath"; return $false }
    Copy-Item $src $full -Force
    Write-Warn2 "rollback: $RelPath"
    return $true
}

function Read-TextFile {
    param([string]$RelPath)
    return [System.IO.File]::ReadAllText((Join-Path $ProjectRoot $RelPath), [System.Text.Encoding]::UTF8)
}

function Write-TextFile {
    param([string]$RelPath, [string]$Content)
    $full = Join-Path $ProjectRoot $RelPath
    $dir = Split-Path $full -Parent
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($full, $Content, $utf8NoBom)
}

function Test-PyCompile {
    param([string]$RelPath)
    $full = Join-Path $ProjectRoot $RelPath
    $out = & python -m py_compile $full 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "py_compile ناموفق: $RelPath"
        $out | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        return $false
    }
    return $true
}

try {
    Write-Host "`n===[ گام ۲۱: معاملات + دانلود هیستوری ]===" -ForegroundColor Cyan
    Write-Host "ProjectRoot : $ProjectRoot"
    Write-Host "BackupDir   : $backup"
    if ($DryRun) { Write-Host "Mode        : DRY-RUN" -ForegroundColor Yellow }

    # =====================================================================
    # 1) ساخت fxars/api/trading.py
    # =====================================================================
    Write-Host "`n--- [1/6] fxars/api/trading.py ---" -ForegroundColor Yellow

    $tradingPy = @'
"""API endpoints برای معاملات (Trading) و دانلود هیستوری.

FIX-21-TRADING-HISTORY:
- GET  /api/v1/trading/status         → وضعیت بروکر/MT5
- GET  /api/v1/orders                 → فهرست سفارشات
- GET  /api/v1/orders/{id}            → جزئیات سفارش
- POST /api/v1/orders                 → ارسال سفارش (فاز غیر READ_ONLY)
- POST /api/v1/trading/reconcile      → تطبیق سفارش‌های UNKNOWN
- POST /api/v1/history/download       → دانلود هیستوری از MT5
- POST /api/v1/history/ingest         → ingest فایل‌های CSV دانلودشده
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from fxars.core.errors import NotFoundError, PhaseViolationError, ValidationError
from fxars.domain.enums import OrderStatus


# نگاشت تایم‌فریم به MT5 constant برای symbol_info
_TF_MAP = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1",
}


def _pip_size_for(si: Any) -> Decimal:
    """محاسبه pip_size از symbol_info بر اساس digits."""
    point = Decimal(str(si.point))
    if si.digits in (3, 5):
        return point * 10
    return point


def register_trading_routes(app: Any) -> None:
    """ثبت مسیرهای معاملات در ApiApp."""

    def _broker_status(request, params, user):
        broker = app.platform.execution.broker
        if broker is None:
            return app._json(200, {
                "connected": False,
                "reason": "broker not configured",
                "phase": app.settings.phase.value,
            })
        try:
            from fxars.live.mt5_feed import MT5Feed
            feed = MT5Feed(source_id="api_check")
            info = feed.account_info()
            feed.shutdown()
            return app._json(200, {
                "connected": True,
                "account": info,
                "phase": app.settings.phase.value,
                "broker": getattr(broker, "name", "unknown"),
            })
        except Exception as exc:
            return app._json(200, {
                "connected": False,
                "reason": str(exc),
                "phase": app.settings.phase.value,
            })

    def _orders_list(request, params, user):
        status_str = request.one("status")
        limit = request.integer("limit", 50, maximum=500)
        if status_str:
            try:
                status = OrderStatus(status_str.upper())
            except ValueError:
                raise ValidationError(f"status نامعتبر: {status_str}")
            intents = app.platform.orders.list_intents_by_status(status, limit=limit)
        else:
            intents = []
            for st in OrderStatus:
                intents.extend(app.platform.orders.list_intents_by_status(st, limit=limit))
            intents.sort(key=lambda x: x.created_at, reverse=True)
            intents = intents[:limit]
        return app._json(200, {
            "items": [i.to_dict() for i in intents],
            "count": len(intents),
        })

    def _orders_get(request, params, user):
        intent = app.platform.orders.get_intent(params["intent_id"])
        if intent is None:
            raise NotFoundError(f"سفارش {params['intent_id']} یافت نشد")
        return app._json(200, {"intent": intent.to_dict()})

    def _orders_submit(request, params, user):
        body = request.json()
        scenario_id = body.get("scenario_id")
        if not scenario_id:
            raise ValidationError("scenario_id الزامی است")
        try:
            intent = app.platform.execution.create_intent(scenario_id, actor=user.username)
        except PhaseViolationError as exc:
            return app._json(403, exc.to_dict())

        # دریافت قیمت لحظه‌ای
        try:
            from fxars.live.mt5_feed import MT5Feed
            feed = MT5Feed(source_id="api_submit")
            tick = feed._mt5.symbol_info_tick(intent.instrument_id)
            if tick is None:
                raise ValidationError(f"قیمت برای {intent.instrument_id} موجود نیست")
            price = Decimal(str(tick.ask if intent.side.value == "BUY" else tick.bid))
            si = feed._mt5.symbol_info(intent.instrument_id)
            pip_size = _pip_size_for(si)
            feed.shutdown()
        except Exception as exc:
            return app._json(503, {
                "error": {"code": "BROKER_UNAVAILABLE", "message": str(exc)},
            })

        try:
            result = app.platform.execution.submit(
                intent.intent_id, price=price, pip_size=pip_size, actor=user.username,
            )
        except Exception as exc:
            return app._json(422, {
                "error": {"code": "SUBMIT_FAILED", "message": str(exc)},
            })
        return app._json(200, {"intent": result.to_dict()})

    def _reconcile(request, params, user):
        from fxars.execution.reconciliation import ReconciliationService
        svc = ReconciliationService(
            orders=app.platform.orders,
            broker=app.platform.execution.broker,
            audit=app.platform.audit,
            outbox=app.platform.outbox,
            clock=app.platform.clock,
        )
        results = svc.reconcile_all(actor=user.username)
        payload = [
            {
                "intent_id": r.intent_id,
                "from_status": r.from_status.value,
                "to_status": r.to_status.value,
                "reason": r.reason,
            }
            for r in results
        ]
        return app._json(200, {"reconciled": payload, "count": len(payload)})

    def _history_download(request, params, user):
        body = request.json()
        instruments = body.get("instruments") or []
        timeframes = body.get("timeframes") or []
        bars = int(body.get("bars", 5000))
        if not instruments:
            raise ValidationError("instruments الزامی است")
        if not timeframes:
            raise ValidationError("timeframes الزامی است")
        if bars < 1 or bars > 200000:
            raise ValidationError("bars باید بین ۱ و ۲۰۰۰۰۰ باشد")

        from fxars.live.history import download_history
        output_dir = str(Path(app.settings.data_dir) / "history")
        try:
            result = download_history(
                symbols=instruments,
                timeframes=timeframes,
                bars=bars,
                output_dir=output_dir,
                platform=None,
            )
        except Exception as exc:
            return app._json(503, {
                "error": {"code": "DOWNLOAD_FAILED", "message": str(exc)},
            })
        return app._json(200, result)

    def _history_ingest(request, params, user):
        body = request.json()
        files = body.get("files") or []
        if not files:
            raise ValidationError("files الزامی است")
        results = []
        for f in files:
            try:
                path = Path(f)
                if not path.is_absolute():
                    path = Path(app.settings.data_dir) / "history" / path
                if not path.exists():
                    results.append({"file": str(path), "error": "file not found"})
                    continue
                parts = path.stem.split("_")
                symbol = parts[0]
                tf = parts[1] if len(parts) > 1 else "H1"
                r = app.platform.ingest_csv(path, instrument_id=symbol, timeframe=tf, source_id="mt5")
                results.append({
                    "file": str(path),
                    "accepted": r.accepted,
                    "quarantined": r.quarantined,
                })
            except Exception as exc:
                results.append({"file": f, "error": str(exc)})
        return app._json(200, {"results": results})

    def _history_files(request, params, user):
        """فهرست فایل‌های موجود در data/history/."""
        history_dir = Path(app.settings.data_dir) / "history"
        if not history_dir.exists():
            return app._json(200, {"files": [], "count": 0, "dir": str(history_dir)})
        files = []
        for p in sorted(history_dir.glob("*.csv")):
            stat = p.stat()
            files.append({
                "name": p.name,
                "path": str(p),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        return app._json(200, {"files": files, "count": len(files), "dir": str(history_dir)})

    # ثبت مسیرها
    app.routes.extend([
        ("GET",  re.compile(r"^/api/v1/trading/status$"),                       _broker_status,    None, False),
        ("GET",  re.compile(r"^/api/v1/orders$"),                               _orders_list,      None, False),
        ("GET",  re.compile(r"^/api/v1/orders/(?P<intent_id>[A-Za-z0-9_\-]+)$"), _orders_get,       None, False),
        ("POST", re.compile(r"^/api/v1/orders$"),                               _orders_submit,    None, False),
        ("POST", re.compile(r"^/api/v1/trading/reconcile$"),                    _reconcile,        None, False),
        ("POST", re.compile(r"^/api/v1/history/download$"),                     _history_download, None, False),
        ("POST", re.compile(r"^/api/v1/history/ingest$"),                       _history_ingest,   None, False),
        ("GET",  re.compile(r"^/api/v1/history/files$"),                        _history_files,    None, False),
    ])
'@

    if ($DryRun) {
        Write-Warn2 "DRY-RUN: trading.py نوشته نشد"
    } else {
        Write-TextFile -RelPath 'fxars\api\trading.py' -Content $tradingPy
        Write-Ok "fxars/api/trading.py ساخته شد"
        if (-not (Test-PyCompile -RelPath 'fxars\api\trading.py')) {
            Write-Err "syntax خطا — متوقف"
            return
        }
    }

    # =====================================================================
    # 2) patch server.py — register trading routes
    # =====================================================================
    Write-Host "`n--- [2/6] patch server.py ---" -ForegroundColor Yellow

    $serverText = Read-TextFile -RelPath 'fxars\api\server.py'
    if ($serverText -match 'FIX-21-TRADING-HISTORY') {
        Write-Skip "server.py از قبل patch شده"
    } else {
        # anchor: آخرین add() در _register
        $anchor = '        add("GET", r"^/api/v1/live/signals$", self._live_signals, Permission.SCENARIO_READ)'
        $replacement = @'
        add("GET", r"^/api/v1/live/signals$", self._live_signals, Permission.SCENARIO_READ)

        # FIX-21-TRADING-HISTORY: مسیرهای معاملات و دانلود
        from fxars.api.trading import register_trading_routes
        register_trading_routes(self)
'@

        if (-not $serverText.Contains($anchor)) {
            Write-Err "anchor پیدا نشد در server.py"
            Write-Host "  دنبال آخرین add() در _register بگردید و دستی اضافه کنید:" -ForegroundColor Yellow
            Write-Host '    from fxars.api.trading import register_trading_routes' -ForegroundColor DarkGray
            Write-Host '    register_trading_routes(self)' -ForegroundColor DarkGray
        } elseif ($DryRun) {
            Write-Warn2 "DRY-RUN: server.py patch نشد"
        } else {
            Backup-File -RelPath 'fxars\api\server.py'
            $patched = $serverText.Replace($anchor, $replacement.TrimEnd())
            $patched = $patched.TrimEnd() + "`n`n# FIX-21-TRADING-HISTORY`n"
            Write-TextFile -RelPath 'fxars\api\server.py' -Content $patched
            if (Test-PyCompile -RelPath 'fxars\api\server.py') {
                Write-Ok "server.py patch شد"
            } else {
                Restore-File -RelPath 'fxars\api\server.py' | Out-Null
            }
        }
    }

    # =====================================================================
    # 3) بازنویسی dashboard.py با ۹ تب
    # =====================================================================
    Write-Host "`n--- [3/6] dashboard.py (۹ تب) ---" -ForegroundColor Yellow

    $dashboardText = @'
"""داشبورد تک‌صفحه‌ای فارسی (RTL) با ۹ تب — FIX-21-TRADING-HISTORY."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FX-ARS — سامانه تحلیل و پشتیبانی تصمیم</title>
<style>
:root{--bg:#0b1220;--panel:#111c33;--panel2:#0e1830;--border:#1e3a5f;--text:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444}
*{box-sizing:border-box}
body{margin:0;font-family:Tahoma,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);font-size:14px}
header{display:flex;gap:10px;align-items:center;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:10;flex-wrap:wrap}
header h1{font-size:17px;margin:0;color:var(--accent);white-space:nowrap}
header .spacer{flex:1}
.badge{padding:3px 10px;border-radius:999px;font-size:12px;border:1px solid var(--border);background:var(--panel2)}
.badge.ok{color:var(--ok);border-color:#14532d}.badge.bad{color:var(--bad);border-color:#7f1d1d}.badge.warn{color:var(--warn);border-color:#78350f}
.tabs{display:flex;gap:2px;background:var(--panel2);border-bottom:1px solid var(--border);padding:0 18px;overflow-x:auto;position:sticky;top:57px;z-index:9}
.tab{padding:12px 18px;background:transparent;border:none;color:var(--muted);cursor:pointer;font-family:inherit;font-size:13px;border-bottom:3px solid transparent;transition:.15s;white-space:nowrap}
.tab:hover{color:var(--text);background:rgba(255,255,255,.03)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);background:rgba(56,189,248,.06)}
main{padding:20px;max-width:1400px;margin:0 auto}
.tab-panel{display:none}
.tab-panel.active{display:block}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px;color:#93c5fd;display:flex;justify-content:space-between;align-items:center;gap:8px}
.grid-2{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}
.grid-3{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.stat{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:14px}
.stat .label{color:var(--muted);font-size:12px;margin-bottom:6px}
.stat .value{font-size:22px;color:var(--accent);font-weight:bold}
.stat .value.pos{color:var(--ok)}.stat .value.neg{color:var(--bad)}
label{display:block;color:var(--muted);font-size:12px;margin:10px 0 4px}
input,select,button,textarea{font-family:inherit;font-size:13px}
input,select,textarea{width:100%;padding:9px;border-radius:9px;border:1px solid var(--border);background:#0a1428;color:var(--text)}
input:focus,select:focus{outline:2px solid #0369a1;outline-offset:1px}
button{padding:9px 14px;border-radius:9px;border:1px solid #0369a1;background:#0c4a6e;color:#e0f2fe;cursor:pointer;white-space:nowrap}
button:hover{background:#075985}button:disabled{opacity:.55;cursor:not-allowed}
button.danger{border-color:#991b1b;background:#7f1d1d}
button.ghost{background:transparent;border-color:var(--border);color:var(--muted)}
button.ghost:hover{background:rgba(255,255,255,.05)}
.row{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap}.row>*{flex:1;min-width:140px}.row button{flex:0 0 auto}
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{padding:8px;border-bottom:1px solid var(--border);text-align:right;font-size:12px;vertical-align:top}
th{color:#93c5fd;font-weight:600}
tr.scenario-row{cursor:pointer}tr.scenario-row:hover{background:#0a1428}
pre{white-space:pre-wrap;background:#0a1428;border:1px solid var(--border);border-radius:10px;padding:10px;max-height:400px;overflow:auto;font-size:12px;direction:ltr;text-align:left}
.muted{color:var(--muted);font-size:12px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:12px;margin-top:8px}
.kv b{color:var(--muted);font-weight:500}
.hidden{display:none!important}
.pos{color:var(--ok)}.neg{color:var(--bad)}
#toast{position:fixed;bottom:16px;left:16px;background:#0c4a6e;border:1px solid #0369a1;padding:10px 16px;border-radius:10px;opacity:0;transition:.3s;z-index:100;max-width:70vw;color:#e0f2fe}
#toast.show{opacity:1}
.login{max-width:440px;margin:7vh auto;background:var(--panel);border:1px solid var(--border);border-radius:18px;padding:26px;box-shadow:0 20px 50px #0008}
.login h1{color:var(--accent);font-size:20px;margin:0 0 4px}
.login .sub{color:var(--muted);font-size:12px;margin-bottom:14px}
#loginError{color:#f87171;min-height:18px;font-size:12px;margin-top:10px}
.help{margin-top:12px;padding-top:10px;border-top:1px dashed var(--border);font-size:12px;color:var(--muted);line-height:1.9}
.help code{background:#0a1428;padding:2px 6px;border-radius:6px;direction:ltr;display:inline-block}
#chartContainer{height:420px;background:#0a1428;border-radius:10px;border:1px solid var(--border)}
#rsiContainer{height:140px;background:#0a1428;border-radius:10px;border:1px solid var(--border);margin-top:8px}
.chart-toolbar{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px}
.chart-toolbar>div{flex:0 0 auto;min-width:130px}
.chart-toolbar label{margin:0;display:inline-flex;align-items:center;gap:4px;color:var(--muted);font-size:12px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:10px}
.legend span::before{content:"";display:inline-block;width:10px;height:10px;margin-left:4px;border-radius:2px;vertical-align:middle}
.legend .ema20::before{background:#fbbf24}.legend .ema50::before{background:#f472b6}.legend .ema200::before{background:#a78bfa}
.legend .entry::before{background:#22c55e}.legend .stop::before{background:#ef4444}.legend .target::before{background:#38bdf8}
</style>
<script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script>
</head>
<body>

<div id="loginView" class="login">
  <h1>ورود به FX-ARS</h1>
  <div class="sub">سامانه تحلیل و پشتیبانی تصمیم — فاز MVP-1</div>
  <form id="loginForm" onsubmit="login(event)">
    <label for="username">نام کاربری</label>
    <input id="username" autocomplete="username" value="analyst" autofocus>
    <label for="password">رمز عبور</label>
    <input id="password" type="password" autocomplete="current-password">
    <div style="margin-top:6px">
      <input type="checkbox" id="showPassword" onchange="togglePassword()" style="width:auto">
      <label for="showPassword" style="display:inline;margin:0">نمایش رمز</label>
    </div>
    <label for="totp">کد MFA (برای نقش‌های مدیریتی)</label>
    <div class="row">
      <input id="totp" inputmode="numeric" autocomplete="one-time-code" placeholder="۶ رقم" maxlength="6">
      <button type="button" class="ghost" onclick="fetchDemoCode()">کد دمو</button>
    </div>
    <div style="margin-top:16px"><button id="loginButton" type="submit" style="width:100%">ورود</button></div>
  </form>
  <div class="row" style="margin-top:10px">
    <button type="button" class="ghost" onclick="quickDemo()">ورود سریع دمو</button>
  </div>
  <div id="loginError" role="alert"></div>
  <div class="help">
    <b>راهنمای دمو:</b><br>
    تحلیل‌گر: <code>analyst</code> / <code>&lt;رمز دمو&gt;</code><br>
    مدیر: <code>admin</code> / <code>&lt;رمز دمو&gt;</code> + کد ۶ رقمی
  </div>
</div>

<div id="appView" class="hidden">
  <header id="appHeader">
    <h1>FX-ARS</h1>
    <span class="badge" id="phaseBadge">فاز: —</span>
    <span class="badge" id="killBadge">Kill Switch: —</span>
    <span class="badge" id="configBadge" title="config hash">—</span>
    <div class="spacer"></div>
    <span class="muted" id="userLabel"></span>
    <button class="ghost" onclick="loadAll()">🔄</button>
    <button class="danger" onclick="logout()">خروج</button>
  </header>

  <nav class="tabs" role="tablist">
    <button class="tab active" data-tab="summary" role="tab">📊 خلاصه</button>
    <button class="tab" data-tab="chart" role="tab">📈 نمودار</button>
    <button class="tab" data-tab="analysis" role="tab">🎯 تحلیل</button>
    <button class="tab" data-tab="scenarios" role="tab">📋 سناریوها</button>
    <button class="tab" data-tab="risk" role="tab">🛡️ ریسک</button>
    <button class="tab" data-tab="backtest" role="tab">📊 بک‌تست</button>
    <button class="tab" data-tab="trading" role="tab">💼 معاملات</button>
    <button class="tab" data-tab="history" role="tab">⬇️ دانلود</button>
    <button class="tab" data-tab="ops" role="tab">⚙️ عملیات</button>
  </nav>

  <main>
    <section class="tab-panel active" data-panel="summary">
      <div class="grid-3">
        <div class="stat"><div class="label">وضعیت سرویس</div><div class="value" id="statHealth">—</div></div>
        <div class="stat"><div class="label">فاز</div><div class="value" id="statPhase">—</div></div>
        <div class="stat"><div class="label">Kill Switch</div><div class="value" id="statKill">—</div></div>
        <div class="stat"><div class="label">آخرین تصمیم</div><div class="value" id="statLastDecision">—</div></div>
        <div class="stat"><div class="label">سناریو فعال</div><div class="value" id="statScenarioCount">—</div></div>
        <div class="stat"><div class="label">Outbox</div><div class="value" id="statOutbox">—</div></div>
      </div>
      <div class="grid-2">
        <div class="card"><h2>📌 آخرین تحلیل</h2><div id="summaryLastAnalysis" class="muted">—</div></div>
        <div class="card"><h2>📋 سناریوهای فعال</h2><div id="summaryScenarios" class="muted">—</div></div>
      </div>
    </section>

    <section class="tab-panel" data-panel="chart">
      <div class="card">
        <h2>📈 نمودار زنده <span class="muted" id="chartStatus"></span></h2>
        <div class="chart-toolbar">
          <div><label>نماد</label><select id="chartInstrument"></select></div>
          <div><label>تایم‌فریم</label><select id="chartTimeframe"><option>M5</option><option>M15</option><option>M30</option><option selected>H1</option><option>H4</option><option>D1</option></select></div>
          <div><label>تعداد</label><select id="chartLimit"><option>50</option><option selected>100</option><option>200</option></select></div>
          <button onclick="loadChart()">بارگذاری</button>
          <label><input type="checkbox" id="chartAutoRefresh" checked style="width:auto"> خودکار</label>
        </div>
        <div id="chartContainer"></div>
        <div id="rsiContainer"></div>
        <div id="chartInfo" class="muted" style="margin-top:10px"></div>
      </div>
    </section>

    <section class="tab-panel" data-panel="analysis">
      <div class="card">
        <h2>🎯 اجرای تحلیل</h2>
        <div class="row">
          <div><label>نماد</label><select id="instrument"></select></div>
          <div><label>تایم‌فریم</label><select id="timeframe"><option>H1</option><option>M15</option><option>H4</option><option>D1</option></select></div>
          <button onclick="runAnalysis()">اجرای تحلیل</button>
        </div>
        <div class="kv" id="marketSummary" style="margin-top:12px"></div>
      </div>
      <div class="card">
        <h2>📊 نتیجه <span class="muted" id="analysisStatus"></span></h2>
        <div id="analysisResult" class="muted">—</div>
        <pre id="decisionBox" class="hidden"></pre>
      </div>
    </section>

    <section class="tab-panel" data-panel="scenarios">
      <div class="card">
        <h2>📋 سناریوها <span class="muted" id="scenarioCount"></span></h2>
        <table><thead><tr><th>شناسه</th><th>نماد</th><th>جهت</th><th>وضعیت</th><th>انقضا</th></tr></thead><tbody id="scenarioRows"></tbody></table>
        <div id="scenarioDetail" class="muted" style="margin-top:12px">—</div>
      </div>
    </section>

    <section class="tab-panel" data-panel="risk">
      <div class="card">
        <h2>🛡️ ارزیابی ریسک</h2>
        <label>Equity</label><input id="equity" value="10000">
        <label>سناریو</label><select id="riskScenario"></select>
        <div style="margin-top:12px"><button onclick="evaluateRisk()">ارزیابی</button></div>
        <div id="riskResult" style="margin-top:12px"></div>
      </div>
    </section>

    <section class="tab-panel" data-panel="backtest">
      <div class="card">
        <h2>📊 بک‌تست</h2>
        <div class="row">
          <div><label>نماد</label><select id="btInstrument"></select></div>
          <div><label>بازه</label><select id="btSegment"><option>ALL</option><option>TRAIN</option><option>VALIDATION</option><option>LOCKED_TEST</option></select></div>
          <button onclick="runBacktest()">اجرا</button>
        </div>
        <div id="btResult" style="margin-top:12px" class="muted">—</div>
      </div>
    </section>

    <section class="tab-panel" data-panel="trading">
      <div class="grid-2">
        <div class="card">
          <h2>📡 وضعیت بروکر</h2>
          <div id="brokerStatus" class="muted">—</div>
          <button onclick="loadBrokerStatus()" style="margin-top:8px">بروزرسانی</button>
        </div>
        <div class="card">
          <h2>🔧 تنظیمات</h2>
          <div class="kv">
            <b>فاز</b><span id="tradingPhase">—</span>
            <b>اجرای سفارش</b><span id="tradingEnabled">—</span>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>✋ ارسال سفارش دستی</h2>
        <div class="row">
          <div><label>سناریو</label><select id="tradeScenario"></select></div>
          <button onclick="submitOrder()" class="danger">تأیید و ارسال</button>
        </div>
        <div id="tradeResult" style="margin-top:12px" class="muted">—</div>
      </div>
      <div class="card">
        <h2>📋 سفارش‌ها <button class="ghost" onclick="loadOrders()">بروزرسانی</button></h2>
        <table><thead><tr><th>شناسه</th><th>نماد</th><th>جهت</th><th>حجم</th><th>وضعیت</th><th>زمان</th></tr></thead><tbody id="ordersRows"><tr><td colspan="6" class="muted">—</td></tr></tbody></table>
        <div style="margin-top:12px"><button class="ghost" onclick="reconcile()">تطبیق UNKNOWN</button></div>
      </div>
    </section>

    <section class="tab-panel" data-panel="history">
      <div class="card">
        <h2>⬇️ دانلود از MT5</h2>
        <div class="grid-2">
          <div>
            <label>نمادها (با کاما)</label>
            <input id="histInstruments" placeholder="EURUSD,GBPUSD,XAUUSD" value="EURUSD">
            <label>تایم‌فریم‌ها</label>
            <input id="histTimeframes" placeholder="M15,H1,H4,D1" value="H1">
            <label>تعداد کندل</label>
            <input id="histBars" type="number" value="5000">
          </div>
          <div>
            <label>Ingest فایل‌های موجود</label>
            <button onclick="loadHistoryFiles()" class="ghost">بارگذاری فهرست</button>
            <div id="historyFiles" class="muted" style="margin-top:8px">—</div>
          </div>
        </div>
        <div class="row" style="margin-top:12px">
          <button onclick="downloadHistory()">⬇️ دانلود</button>
          <button class="ghost" onclick="ingestHistory()">📥 Ingest همه</button>
        </div>
        <div id="historyResult" style="margin-top:12px" class="muted">—</div>
      </div>
    </section>

    <section class="tab-panel" data-panel="ops">
      <div class="grid-2">
        <div class="card"><h2>🔍 سلامت</h2><div class="kv" id="healthBox"></div></div>
        <div class="card">
          <h2>🚨 Kill Switch</h2>
          <div class="row">
            <input id="killReason" placeholder="دلیل">
            <button class="danger" onclick="toggleKill(true)">فعال</button>
            <button class="ghost" onclick="toggleKill(false)">غیرفعال</button>
          </div>
        </div>
      </div>
      <div class="card"><h2>📜 ممیزی</h2><button onclick="loadAudit()">بارگذاری</button><pre id="auditBox" class="hidden"></pre></div>
    </section>
  </main>
</div>

<div id="toast" role="status"></div>

<script>
const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem("fxars_token") || "", user: null, meta: null, scenarios: [] };
const chartState = { chart: null, rsiChart: null, timer: null };

function toast(message, ok) {
  const el = $("toast"); el.textContent = message;
  el.style.borderColor = ok ? "#166534" : "#991b1b";
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 3500);
}
function num(v, d) { return (v === null || v === undefined) ? "—" : Number(v).toFixed(d === undefined ? 2 : d); }
function esc(v) { return String(v === null || v === undefined ? "" : v).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function togglePassword() { $("password").type = $("showPassword").checked ? "text" : "password"; }

async function api(path, options = {}) {
  const headers = Object.assign({"Content-Type": "application/json"}, options.headers || {});
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  if ((options.method || "GET") === "POST") headers["Idempotency-Key"] = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
  const response = await fetch(path, Object.assign({}, options, {headers}));
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = {raw: text}; }
  if (!response.ok) {
    const message = (data && data.error && data.error.message) || ("HTTP " + response.status);
    if (response.status === 401 && !path.includes("/auth/login")) logout(false);
    throw new Error(message);
  }
  return data;
}

function initTabs() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === name));
      if (name === "chart" && !chartState.chart) loadChart().catch(() => {});
      if (name === "trading") { loadBrokerStatus().catch(() => {}); loadOrders().catch(() => {}); }
      if (name === "history") loadHistoryFiles().catch(() => {});
    });
  });
}

async function login(event) {
  if (event) event.preventDefault();
  const button = $("loginButton"); button.disabled = true; $("loginError").textContent = "";
  const body = {username: $("username").value.trim(), password: $("password").value};
  if ($("totp").value.trim()) body.totp_code = $("totp").value.trim();
  try {
    const data = await api("/api/v1/auth/login", {method: "POST", body: JSON.stringify(body)});
    state.token = data.token; state.user = data.user;
    localStorage.setItem("fxars_token", data.token);
    showApp(); await loadAll();
    toast("خوش آمدید " + (data.user.display_name || data.user.username), true);
  } catch (error) { $("loginError").textContent = error.message; $("loginButton").disabled = false; }
}
async function quickDemo() {
  $("loginError").textContent = "";
  try {
    const data = await api("/api/v1/auth/demo-login", {method: "POST", body: JSON.stringify({role: "ANALYST"})});
    state.token = data.token; state.user = data.user;
    localStorage.setItem("fxars_token", data.token);
    showApp(); await loadAll();
    toast("ورود دمو", true);
  } catch (error) { $("loginError").textContent = error.message; }
}
async function fetchDemoCode() {
  try {
    const data = await api("/api/v1/auth/demo-totp?username=admin");
    $("totp").value = data.code;
    toast("کد MFA: " + data.expires_in + "s", true);
  } catch (error) { $("loginError").textContent = error.message; }
}
function showApp() {
  $("loginView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  $("appHeader").classList.remove("hidden");
}
function logout(reload = true) {
  if (state.token) fetch("/api/v1/auth/logout", {method: "POST", headers: {"Authorization": "Bearer " + state.token, "Idempotency-Key": String(Date.now())}}).catch(() => {});
  state.token = ""; state.user = null;
  localStorage.removeItem("fxars_token");
  if (reload) { window.location.reload(); return; }
  $("appView").classList.add("hidden"); $("appHeader").classList.add("hidden");
  $("loginView").classList.remove("hidden"); $("loginButton").disabled = false;
  $("password").value = ""; $("totp").value = "";
}

async function loadAll() {
  if (!state.token) { logout(false); return; }
  try {
    const me = await api("/api/v1/auth/me");
    state.user = me.user;
    $("userLabel").textContent = me.user.username + " (" + me.user.role + ")";
    const meta = await api("/api/v1/meta");
    state.meta = meta;
    $("phaseBadge").textContent = "فاز: " + meta.phase;
    $("configBadge").textContent = "config " + meta.config_hash.slice(0, 10);
    $("killBadge").textContent = "Kill Switch: " + (meta.killswitch.active ? "فعال" : "غیرفعال");
    $("killBadge").className = "badge " + (meta.killswitch.active ? "bad" : "ok");
    const health = await api("/api/v1/health");
    $("healthBox").innerHTML = "<b>وضعیت</b><span>" + esc(health.status) + "</span><b>زمان</b><span>" + esc(health.time) + "</span><b>ممیزی</b><span>" + (health.audit ? "معتبر" : "ناسازگار") + "</span>";
    $("statHealth").textContent = health.status === "ok" ? "✅ سالم" : "⚠️ " + health.status;
    $("statPhase").textContent = meta.phase;
    $("statKill").textContent = meta.killswitch.active ? "🔴 فعال" : "🟢 غیرفعال";
    $("statKill").className = "value " + (meta.killswitch.active ? "neg" : "pos");
    const instruments = await api("/api/v1/instruments");
    const options = instruments.items.map(i => "<option>" + esc(i.instrument_id) + "</option>").join("");
    $("instrument").innerHTML = options; $("btInstrument").innerHTML = options; $("chartInstrument").innerHTML = options;
    await loadScenarios();
    await loadCandles();
    showApp();
  } catch (error) { toast(error.message, false); $("loginError").textContent = error.message; }
}

async function refreshSummary() {
  try {
    const scenarios = await api("/api/v1/scenarios?limit=5");
    $("statScenarioCount").textContent = scenarios.count;
    const active = scenarios.items.filter(s => ["WATCH","ARMED","TRIGGERED"].includes(s.status));
    $("summaryScenarios").innerHTML = active.length === 0 ? "<span class='muted'>سناریو فعالی نیست</span>" : active.map(s => "<div style='padding:6px 0;border-bottom:1px solid var(--border)'><b>" + esc(s.scenario_id.slice(0,12)) + "</b> — " + esc(s.instrument_id) + " " + esc(s.direction) + " (" + esc(s.status) + ")</div>").join("");
  } catch (e) {}
}

async function loadChart() {
  const instrument = $("chartInstrument").value || "EURUSD";
  const timeframe = $("chartTimeframe").value || "H1";
  const limit = parseInt($("chartLimit").value || "100", 10);
  $("chartStatus").textContent = "بارگذاری...";
  try {
    const data = await api("/api/v1/live/chart?instrument=" + encodeURIComponent(instrument) + "&timeframe=" + timeframe + "&limit=" + limit);
    renderChart(data);
    $("chartStatus").textContent = data.count + " کندل";
    $("chartInfo").textContent = data.instrument + " / " + data.timeframe + " — " + data.count + " کندل";
  } catch (error) { $("chartStatus").textContent = "خطا"; toast(error.message, false); }
}

function renderChart(data) {
  if (!window.LightweightCharts) { toast("LightweightCharts نیست", false); return; }
  const LWC = window.LightweightCharts;
  if (chartState.chart) { chartState.chart.remove(); chartState.chart = null; }
  if (chartState.rsiChart) { chartState.rsiChart.remove(); chartState.rsiChart = null; }
  const container = $("chartContainer"), rsiContainer = $("rsiContainer");
  const chart = LWC.createChart(container, {
    width: container.clientWidth, height: 420,
    layout: { background: { color: "#0a1428" }, textColor: "#94a3b8" },
    grid: { vertLines: { color: "#1e3a5f" }, horzLines: { color: "#1e3a5f" } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1e3a5f" },
    rightPriceScale: { borderColor: "#1e3a5f" },
  });
  const candleSeries = chart.addCandlestickSeries({ upColor: "#22c55e", downColor: "#ef4444", borderUpColor: "#22c55e", borderDownColor: "#ef4444", wickUpColor: "#22c55e", wickDownColor: "#ef4444" });
  candleSeries.setData(data.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));
  const ema20 = chart.addLineSeries({ color: "#fbbf24", lineWidth: 1, title: "EMA20" });
  const ema50 = chart.addLineSeries({ color: "#f472b6", lineWidth: 1, title: "EMA50" });
  const ema200 = chart.addLineSeries({ color: "#a78bfa", lineWidth: 1, title: "EMA200" });
  const times = data.candles.map(c => c.time);
  function setEma(series, values) {
    if (!values || !values.length) return;
    const points = [];
    for (let i = 0; i < Math.min(values.length, times.length); i++) if (values[i] != null) points.push({ time: times[i], value: values[i] });
    series.setData(points);
  }
  setEma(ema20, data.indicators.ema20); setEma(ema50, data.indicators.ema50); setEma(ema200, data.indicators.ema200);
  for (const sc of (data.scenarios || [])) {
    if (sc.entry) candleSeries.createPriceLine({ price: parseFloat(sc.entry), color: "#22c55e", lineWidth: 1, lineStyle: 2, title: "Entry" });
    if (sc.stop) candleSeries.createPriceLine({ price: parseFloat(sc.stop), color: "#ef4444", lineWidth: 1, lineStyle: 2, title: "Stop" });
    for (const t of (sc.targets || [])) if (t) candleSeries.createPriceLine({ price: parseFloat(t), color: "#38bdf8", lineWidth: 1, lineStyle: 2, title: "TP" });
  }
  chart.timeScale().fitContent();
  const rsiChart = LWC.createChart(rsiContainer, {
    width: rsiContainer.clientWidth, height: 140,
    layout: { background: { color: "#0a1428" }, textColor: "#94a3b8" },
    grid: { vertLines: { color: "#1e3a5f" }, horzLines: { color: "#1e3a5f" } },
    timeScale: { timeVisible: false, borderColor: "#1e3a5f" },
    rightPriceScale: { borderColor: "#1e3a5f" },
  });
  const rsiSeries = rsiChart.addLineSeries({ color: "#38bdf8", lineWidth: 1, title: "RSI14" });
  if (data.indicators.rsi14) {
    const pts = [];
    for (let i = 0; i < Math.min(data.indicators.rsi14.length, times.length); i++) if (data.indicators.rsi14[i] != null) pts.push({ time: times[i], value: data.indicators.rsi14[i] });
    rsiSeries.setData(pts);
  }
  rsiSeries.createPriceLine({ price: 70, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
  rsiSeries.createPriceLine({ price: 30, color: "#22c55e", lineWidth: 1, lineStyle: 2 });
  rsiChart.timeScale().fitContent();
  chartState.chart = chart; chartState.rsiChart = rsiChart;
  if (chartState.timer) clearInterval(chartState.timer);
  chartState.timer = setInterval(() => { if ($("chartAutoRefresh").checked) loadChart().catch(() => {}); }, 10000);
}

async function loadCandles() {
  const instrument = $("instrument").value || "EURUSD";
  const timeframe = $("timeframe").value || "H1";
  try {
    const data = await api("/api/v1/market-data/candles?instrument_id=" + encodeURIComponent(instrument) + "&timeframe=" + timeframe + "&limit=5");
    const last = data.items[data.items.length - 1];
    if (!last) { $("marketSummary").innerHTML = "<b>داده</b><span>نیست</span>"; return; }
    $("marketSummary").innerHTML = "<b>آخرین</b><span>" + esc(last.bar_open_time_utc) + "</span><b>Close</b><span>" + esc(last.close) + "</span><b>Spread</b><span>" + esc(last.spread) + "</span>";
  } catch (error) { toast(error.message, false); }
}

async function runAnalysis() {
  $("analysisStatus").textContent = "اجرا...";
  try {
    const data = await api("/api/v1/analysis-runs", {method: "POST", body: JSON.stringify({instrument_id: $("instrument").value, timeframe: $("timeframe").value})});
    const d = data.decision, run = data.run;
    const color = d.action === "LONG" ? "pos" : d.action === "SHORT" ? "neg" : "muted";
    $("analysisResult").innerHTML = "<div class='kv'><b>اجرا</b><span>" + esc(run.run_id.slice(0, 16)) + "</span><b>وضعیت</b><span>" + esc(run.status) + "</span><b>تصمیم</b><span class='" + color + "'>" + esc(d.action) + "</span><b>امتیاز</b><span>" + num(d.score, 3) + "</span><b>پوشش</b><span>" + Math.round(d.coverage * 100) + "%</span>" + (d.no_trade_reason ? "<b>دلیل</b><span>" + esc(d.no_trade_reason) + "</span>" : "") + "</div>";
    $("decisionBox").classList.remove("hidden");
    $("decisionBox").textContent = JSON.stringify(d, null, 2);
    $("analysisStatus").textContent = "✅";
    await loadScenarios(); await refreshSummary();
    if (data.scenario) $("riskScenario").value = data.scenario.scenario_id;
    toast("ثبت شد", true);
  } catch (error) { $("analysisStatus").textContent = ""; toast(error.message, false); }
}

async function loadScenarios() {
  try {
    const data = await api("/api/v1/scenarios?limit=25");
    state.scenarios = data.items;
    $("scenarioCount").textContent = data.count + " مورد";
    $("scenarioRows").innerHTML = data.items.map(s => "<tr class='scenario-row' data-id='" + esc(s.scenario_id) + "'><td>" + esc(s.scenario_id.slice(0, 12)) + "</td><td>" + esc(s.instrument_id) + "</td><td>" + esc(s.direction) + "</td><td>" + esc(s.status) + "</td><td>" + esc(s.expiry_at) + "</td></tr>").join("") || "<tr><td colspan=5 class='muted'>نیست</td></tr>";
    document.querySelectorAll(".scenario-row").forEach(row => { row.addEventListener("click", () => showScenario(row.dataset.id)); });
    $("riskScenario").innerHTML = data.items.map(s => "<option value='" + esc(s.scenario_id) + "'>" + esc(s.scenario_id.slice(0, 12)) + " — " + esc(s.direction) + "</option>").join("");
    await refreshSummary();
  } catch (error) { toast(error.message, false); }
}

async function showScenario(id) {
  try {
    const data = await api("/api/v1/scenarios/" + encodeURIComponent(id));
    const s = data.scenario;
    $("scenarioDetail").innerHTML = "<div class='kv'><b>ورود</b><span>" + esc(JSON.stringify(s.entry_condition)) + "</span><b>حد ضرر</b><span>" + esc(JSON.stringify(s.stop_logic)) + "</span><b>اهداف</b><span>" + esc((s.target_logic || []).map(t => t.value + "R @ " + t.price).join(" | ")) + "</span></div>";
  } catch (error) { toast(error.message, false); }
}

async function evaluateRisk() {
  const sid = $("riskScenario").value;
  if (!sid) { toast("سناریو نیست", false); return; }
  try {
    const account = { equity: $("equity").value, balance: $("equity").value, free_margin: $("equity").value, taken_at: new Date().toISOString(), currency: "USD", leverage: "100", open_positions: 0, positions: [] };
    const data = await api("/api/v1/risk/evaluate", {method: "POST", body: JSON.stringify({scenario_id: sid, account})});
    const d = data.decision;
    $("riskResult").innerHTML = "<div class='kv'><b>وضعیت</b><span class='" + (d.approved ? "pos" : "neg") + "'>" + (d.approved ? "✅" : "❌") + " " + esc(d.reason_code) + "</span><b>حجم</b><span>" + esc(d.position_size) + "</span><b>کنترل‌های رد</b><span>" + (d.checks_failed.join(", ") || "—") + "</span></div>";
    toast(d.approved ? "تأیید" : "رد", d.approved);
  } catch (error) { toast(error.message, false); }
}

async function runBacktest() {
  try {
    $("btResult").innerHTML = "<span class='muted'>اجرا...</span>";
    const data = await api("/api/v1/backtests", {method: "POST", body: JSON.stringify({instrument_id: $("btInstrument").value, timeframe: "H1", segment: $("btSegment").value})});
    const m = data.run.metrics;
    $("btResult").innerHTML = "<div class='kv'><b>معاملات</b><span>" + esc(m.trade_count) + "</span><b>سود</b><span>" + esc(num(m.net_profit)) + "</span><b>PF</b><span>" + esc(num(m.profit_factor)) + "</span><b>Sharpe</b><span>" + esc(num(m.sharpe)) + "</span></div><p class='muted'><a style='color:#7dd3fc' target='_blank' href='/api/v1/backtests/" + data.run.run_id + "/report?format=html'>گزارش</a></p>";
  } catch (error) { $("btResult").innerHTML = ""; toast(error.message, false); }
}

// ============ Trading ============
async function loadBrokerStatus() {
  try {
    const data = await api("/api/v1/trading/status");
    const el = $("brokerStatus");
    if (data.connected) {
      el.innerHTML = "<div class='kv'><b>وضعیت</b><span class='pos'>✅ متصل</span><b>حساب</b><span>" + esc(data.account.login) + "</span><b>موجودی</b><span>" + esc(data.account.balance) + " " + esc(data.account.currency) + "</span></div>";
    } else {
      el.innerHTML = "<div class='kv'><b>وضعیت</b><span class='neg'>❌ قطع</span><b>دلیل</b><span>" + esc(data.reason || "—") + "</span></div>";
    }
    $("tradingPhase").textContent = data.phase || "—";
    $("tradingEnabled").textContent = (data.phase && data.phase !== "READ_ONLY") ? "✅ فعال" : "❌ غیرفعال";
  } catch (e) { toast(e.message, false); }
}
async function loadOrders() {
  try {
    const data = await api("/api/v1/orders?limit=50");
    $("ordersRows").innerHTML = data.items.map(o => "<tr><td>" + esc(o.intent_id.slice(0, 12)) + "</td><td>" + esc(o.instrument_id) + "</td><td>" + esc(o.side) + "</td><td>" + esc(o.volume) + "</td><td>" + esc(o.status) + "</td><td>" + esc(o.created_at) + "</td></tr>").join("") || "<tr><td colspan=6 class='muted'>نیست</td></tr>";
    const sc = await api("/api/v1/scenarios?limit=25");
    $("tradeScenario").innerHTML = sc.items.filter(s => ["WATCH","ARMED","TRIGGERED"].includes(s.status)).map(s => "<option value='" + esc(s.scenario_id) + "'>" + esc(s.scenario_id.slice(0, 12)) + " — " + esc(s.direction) + "</option>").join("");
  } catch (e) { toast(e.message, false); }
}
async function submitOrder() {
  const sid = $("tradeScenario").value;
  if (!sid) { toast("سناریو نیست", false); return; }
  if (!confirm("⚠️ ارسال سفارش واقعی به بروکر. مطمئن؟")) return;
  try {
    $("tradeResult").innerHTML = "<span class='muted'>ارسال...</span>";
    const data = await api("/api/v1/orders", {method: "POST", body: JSON.stringify({scenario_id: sid})});
    $("tradeResult").innerHTML = "<div class='kv'><b>سفارش</b><span>" + esc(data.intent.intent_id) + "</span><b>وضعیت</b><span class='pos'>" + esc(data.intent.status) + "</span></div>";
    toast("ارسال شد", true);
    await loadOrders();
  } catch (e) { $("tradeResult").innerHTML = "<span class='neg'>" + esc(e.message) + "</span>"; }
}
async function reconcile() {
  try {
    const data = await api("/api/v1/trading/reconcile", {method: "POST", body: "{}"});
    toast("تطبیق: " + data.count, true);
    await loadOrders();
  } catch (e) { toast(e.message, false); }
}

// ============ History ============
async function downloadHistory() {
  try {
    const instruments = $("histInstruments").value.split(",").map(s => s.trim()).filter(Boolean);
    const timeframes = $("histTimeframes").value.split(",").map(s => s.trim()).filter(Boolean);
    $("historyResult").innerHTML = "<span class='muted'>دانلود...</span>";
    const data = await api("/api/v1/history/download", {method: "POST", body: JSON.stringify({instruments, timeframes, bars: parseInt($("histBars").value)})});
    $("historyResult").innerHTML = "<div class='kv'><b>کل کندل</b><span>" + data.total + "</span><b>فایل</b><span>" + data.files.length + "</span><b>خطا</b><span>" + data.errors.length + "</span></div>" + (data.files.length ? "<ul>" + data.files.map(f => "<li>" + esc(f) + "</li>").join("") + "</ul>" : "");
    toast("دانلود: " + data.total, true);
    await loadHistoryFiles();
  } catch (e) { $("historyResult").innerHTML = "<span class='neg'>" + esc(e.message) + "</span>"; }
}
async function loadHistoryFiles() {
  try {
    const data = await api("/api/v1/history/files");
    $("historyFiles").innerHTML = data.count === 0 ? "<span class='muted'>فایلی نیست</span>" : data.files.map(f => "<div>" + esc(f.name) + " <span class='muted'>(" + Math.round(f.size/1024) + " KB)</span></div>").join("");
  } catch (e) { /* ignore */ }
}
async function ingestHistory() {
  try {
    const data = await api("/api/v1/history/ingest", {method: "POST", body: JSON.stringify({files: []})});
    $("historyResult").innerHTML = "<div class='kv'>" + data.results.map(r => "<b>" + esc(r.file) + "</b><span>acc=" + (r.accepted || 0) + " q=" + (r.quarantined || 0) + (r.error ? " err=" + esc(r.error) : "") + "</span>").join("") + "</div>";
  } catch (e) { toast(e.message, false); }
}

// ============ Ops ============
async function toggleKill(active) {
  try {
    const reason = $("killReason").value || (active ? "توقف" : "بازگشت");
    await api("/api/v1/killswitch", {method: "POST", body: JSON.stringify({active, reason})});
    toast(active ? "فعال شد" : "غیرفعال شد", true);
    await loadAll();
  } catch (e) { toast(e.message, false); }
}
async function loadAudit() {
  try {
    const data = await api("/api/v1/audit-events?limit=30");
    $("auditBox").classList.remove("hidden");
    $("auditBox").textContent = JSON.stringify(data, null, 2);
  } catch (e) { toast(e.message, false); }
}

initTabs();
if (state.token) { showApp(); loadAll(); } else { $("loginView").classList.remove("hidden"); }
</script>
</body>
</html>"""
'@

    if ($DryRun) {
        Write-Warn2 "DRY-RUN: dashboard.py نوشته نشد"
    } else {
        Backup-File -RelPath 'fxars\ui\dashboard.py'
        Write-TextFile -RelPath 'fxars\ui\dashboard.py' -Content $dashboardText
        if (Test-PyCompile -RelPath 'fxars\ui\dashboard.py') {
            Write-Ok "dashboard.py با ۹ تب بازنویسی شد"
        } else {
            Restore-File -RelPath 'fxars\ui\dashboard.py' | Out-Null
        }
    }

    # =====================================================================
    # 4) patch cli/main.py — download command
    # =====================================================================
    Write-Host "`n--- [4/6] cli/main.py (download) ---" -ForegroundColor Yellow

    $cliText = Read-TextFile -RelPath 'fxars\cli\main.py'
    if ($cliText -match 'FIX-21-DOWNLOAD-CLI') {
        Write-Skip "cli/main.py از قبل patch شده"
    } else {
        # 4a) افزودن cmd_download قبل از cmd_reconcile
        $anchor1 = 'def cmd_reconcile(args: argparse.Namespace) -> None:'
        $downloadFunc = @'
def cmd_download(args: argparse.Namespace) -> None:
    """FIX-21-DOWNLOAD-CLI: دانلود هیستوری از MT5."""
    from fxars.live.history import download_history
    platform = _platform(args)
    try:
        result = download_history(
            symbols=args.instruments,
            timeframes=args.timeframes,
            bars=args.bars,
            output_dir=args.output_dir,
            platform=platform if args.ingest else None,
        )
        print(f"Total candles: {result['total']}")
        print(f"Files: {len(result['files'])}")
        for f in result["files"]:
            print(f"  {f}")
        if result["errors"]:
            print(f"Errors: {len(result['errors'])}")
            for e in result["errors"][:10]:
                print(f"  {e}")
    finally:
        platform.close()


def cmd_reconcile(args: argparse.Namespace) -> None:
'@
        if (-not $cliText.Contains($anchor1)) {
            Write-Err "anchor cmd_reconcile پیدا نشد"
        } else {
            Backup-File -RelPath 'fxars\cli\main.py'
            $cliText = $cliText.Replace($anchor1, $downloadFunc.TrimEnd())

            # 4b) افزودن subparser قبل از ac
            $anchor2 = '    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")'
            $downloadParser = @'
    download = sub.add_parser("download", parents=[common], help="دانلود هیستوری از MT5")
    download.add_argument("--instruments", nargs="+", required=True)
    download.add_argument("--timeframes", nargs="+", required=True)
    download.add_argument("--bars", type=int, default=5000)
    download.add_argument("--output-dir", default="data/history")
    download.add_argument("--ingest", action="store_true")
    download.set_defaults(func=cmd_download)

    ac = sub.add_parser("ac", help="اجرای آزمون‌های پذیرش")
'@
            if (-not $cliText.Contains($anchor2)) {
                Write-Err "anchor ac parser پیدا نشد"
                Restore-File -RelPath 'fxars\cli\main.py' | Out-Null
            } else {
                $cliText = $cliText.Replace($anchor2, $downloadParser.TrimEnd())
                $cliText = $cliText.TrimEnd() + "`n`n# FIX-21-DOWNLOAD-CLI`n"
                Write-TextFile -RelPath 'fxars\cli\main.py' -Content $cliText
                if (Test-PyCompile -RelPath 'fxars\cli\main.py') {
                    Write-Ok "cli/main.py patch شد (download)"
                } else {
                    Restore-File -RelPath 'fxars\cli\main.py' | Out-Null
                }
            }
        }
    }

    # =====================================================================
    # 5) gitignore
    # =====================================================================
    Write-Host "`n--- [5/6] .gitignore ---" -ForegroundColor Yellow

    if ($DryRun) {
        Write-Warn2 "DRY-RUN: gitignore patch نشد"
    } else {
        $giPath = Join-Path $ProjectRoot '.gitignore'
        if (Test-Path $giPath) {
            $gi = Get-Content $giPath -Raw -Encoding UTF8
            if ($gi -notmatch 'data/history') {
                Add-Content -Path $giPath -Value "`n# FIX-21: history downloads`ndata/history/`n" -Encoding UTF8
                Write-Ok ".gitignore += data/history/"
            } else {
                Write-Skip ".gitignore از قبل data/history دارد"
            }
        }
    }

    # =====================================================================
    # 6) تست
    # =====================================================================
    Write-Host "`n--- [6/6] تست ---" -ForegroundColor Yellow

    if ($DryRun) {
        Write-Warn2 "DRY-RUN: تست اجرا نشد"
    } else {
        Push-Location $ProjectRoot
        try {
            Write-Host "  py_compile همه فایل‌های تغییرکرده..." -ForegroundColor Cyan
            $files = @(
                'fxars\api\trading.py',
                'fxars\api\server.py',
                'fxars\ui\dashboard.py',
                'fxars\cli\main.py'
            )
            $allOk = $true
            foreach ($f in $files) {
                if (-not (Test-PyCompile -RelPath $f)) { $allOk = $false }
            }
            if (-not $allOk) {
                Write-Err "برخی فایل‌ها syntax error دارند — بررسی کنید"
                return
            }
            Write-Ok "همه فایل‌ها compile شدند"

            Write-Host "`n  اجرای تست‌های موجود..." -ForegroundColor Cyan
            & python -B -m unittest tests.test_api tests.test_http_integration tests.test_security 2>&1 | Select-Object -Last 15
        } finally {
            Pop-Location
        }
    }

    Write-Host "`n===[ DONE: gam 21 ]===" -ForegroundColor Green
    Write-Host "`nگام بعدی:" -ForegroundColor Cyan
    Write-Host "  cd $ProjectRoot" -ForegroundColor Cyan
    Write-Host "  python -m fxars serve --port 8080" -ForegroundColor Cyan
    Write-Host "  مرورگر: http://127.0.0.1:8080/" -ForegroundColor Cyan
    Write-Host "`nتست دانلود هیستوری:" -ForegroundColor Cyan
    Write-Host "  python -m fxars download --instruments EURUSD GBPUSD --timeframes H1 H4 --bars 500" -ForegroundColor Cyan
}
catch {
    Write-Err "خطای غیرمنتظره: $_"
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
}
finally {
    Pause-IfNeeded -NoPause:$NoPause
}
