#Requires -Version 7.0
<#
.SYNOPSIS
    اعمال پیکربندی سازگار با Settings.validate برای حساب دمو $100.

.DESCRIPTION
    1) از فایل‌های config موجود backup می‌گیرد
    2) settings.json، phase.json، live.json را با نسخه‌های جدید بازنویسی می‌کند
    3) اعتبارسنجی می‌کند (Settings.load)
    4) هم‌خوانی سه فایل را گزارش می‌دهد

.PARAMETER ProjectRoot
    مسیر ریشه پروژه (پیش‌فرض: C:\project\FX)

.PARAMETER DryRun
    فقط نمایش تغییرات، بدون نوشتن فایل
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\project\FX',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ConfigDir = Join-Path $ProjectRoot 'config'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupDir = Join-Path $ProjectRoot ".fix-backups\config-$Stamp"

# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------
function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "   [OK]   $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "   [WARN] $msg" -ForegroundColor Yellow }
function Write-Err2($msg) { Write-Host "   [FAIL] $msg" -ForegroundColor Red }

function Backup-ConfigFile {
    param([string]$FileName)
    $src = Join-Path $ConfigDir $FileName
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Warn2 "فایل موجود نیست، backup انجام نشد: $FileName"
        return
    }
    if (-not (Test-Path -LiteralPath $BackupDir)) {
        New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    }
    Copy-Item -LiteralPath $src -Destination (Join-Path $BackupDir $FileName) -Force
    Write-Ok "backup: $FileName"
}

function Write-ConfigFile {
    param(
        [string]$FileName,
        [string]$Content
    )
    $dst = Join-Path $ConfigDir $FileName
    if ($DryRun) {
        Write-Warn2 "DRY-RUN: $FileName نوشته نشد"
        return
    }
    # UTF-8 بدون BOM (JSON استاندارد)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($dst, $Content.TrimStart("`r", "`n"), $utf8NoBom)
    Write-Ok "نوشته شد: $FileName ($($Content.Length) کاراکتر)"
}

function Test-JsonFile {
    param([string]$FileName)
    $path = Join-Path $ConfigDir $FileName
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Err2 "JSON وجود ندارد: $FileName"
        return $false
    }
    try {
        $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
        $null = $text | ConvertFrom-Json
        Write-Ok "JSON معتبر: $FileName"
        return $true
    } catch {
        Write-Err2 "JSON نامعتبر: $FileName — $_"
        return $false
    }
}

# ---------------------------------------------------------------------------
# شروع
# ---------------------------------------------------------------------------
Write-Host "`n=== اعمال پیکربندی سازگار با Settings.validate ===" -ForegroundColor Magenta
Write-Host "ProjectRoot : $ProjectRoot"
Write-Host "ConfigDir   : $ConfigDir"
Write-Host "BackupDir   : $BackupDir"
if ($DryRun) { Write-Host "Mode        : DRY-RUN" -ForegroundColor Yellow }

if (-not (Test-Path -LiteralPath $ConfigDir)) {
    Write-Err2 "پوشه config پیدا نشد: $ConfigDir"
    exit 1
}

# ---------------------------------------------------------------------------
# ۱) settings.json
# ---------------------------------------------------------------------------
Write-Step "[1/4] settings.json"

$settingsJson = @'
{
    "environment": "dev",
    "phase": "READ_ONLY",
    "db_path": "data/fxars.db",
    "display_timezone": "Asia/Tehran",
    "seed": 7,
    "risk": {
        "version": "risk_policy_v1.2",
        "risk_per_trade": "0.05",
        "hard_cap_risk_per_trade": "0.10",
        "daily_loss_limit": "0.10",
        "drawdown_warn": "0.10",
        "drawdown_stop": "0.15",
        "max_open_positions": 1,
        "max_positions_per_symbol": 1,
        "max_currency_exposure": "1.0",
        "max_correlation_exposure": "1.0",
        "max_spread_pips": "10.0",
        "min_stop_pips": "3.0",
        "max_stop_pips": "30.0",
        "margin_buffer": "0.10",
        "max_account_age_seconds": 300,
        "data_grace_seconds": 300,
        "max_bar_age_bars": 1.5,
        "max_entry_deviation_pips": "25",
        "decision_ttl_seconds": 300,
        "min_signal_strength": 0.35,
        "blackout_before_minutes": 30,
        "blackout_after_minutes": 30,
        "blackout_min_importance": "HIGH",
        "correlation_window": 100,
        "correlation_threshold": 0.6,
        "max_daily_trades": 6,
        "max_daily_loss_hard_cap": "0.10",
        "max_drawdown_hard_cap": "0.20",
        "require_mfa_for_admin": true
    },
    "analysis": {
        "swing_k": 3,
        "min_bars": 220,
        "max_evidence_age_bars": 6,
        "min_strength": 0.25,
        "min_coverage": 0.25,
        "stop_buffer_pips": "5",
        "rr_targets": ["1.5", "3.0"],
        "scenario_expiry_bars": 8,
        "intermarket_refs": {
            "EURUSD": ["DXY"],
            "GBPUSD": ["DXY"],
            "XAUUSD": ["DXY"],
            "AUDUSD": ["DXY"],
            "NZDUSD": ["DXY"],
            "USDJPY": ["DXY"]
        }
    },
    "data_quality": {
        "max_bar_age_bars": 1.5,
        "freshness_grace_seconds": 300,
        "source_divergence_pips": "2.0"
    },
    "backtest": {
        "initial_equity": "100",
        "risk_per_trade": "0.02",
        "default_spread_pips": "1.2",
        "slippage_pips": "0.3",
        "commission_per_lot": "7.0",
        "commission_note": "per lot round turn",
        "seed": 7
    },
    "api": {
        "host": "127.0.0.1",
        "port": 8080,
        "require_idempotency": true,
        "rate_limit_per_minute": 120
    },
    "security": {
        "pbkdf2_iterations": 210000,
        "login_max_attempts": 8,
        "mfa_roles": ["ADMIN", "RISK_MANAGER", "OPERATOR"]
    }
}
'@

Backup-ConfigFile -FileName 'settings.json'
Write-ConfigFile -FileName 'settings.json' -Content $settingsJson
$null = Test-JsonFile -FileName 'settings.json'

# ---------------------------------------------------------------------------
# ۲) phase.json
# ---------------------------------------------------------------------------
Write-Step "[2/4] phase.json"

$phaseJson = @'
{
    "mode": "AUTOMATED_LIMITED",
    "advisor": {
        "min_score_threshold": 0.2,
        "max_signals_per_hour": 10,
        "send_no_trade": false,
        "notify_telegram": true,
        "notify_desktop": true,
        "instruments": [
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "AUDUSD",
            "USDCAD",
            "USDCHF",
            "XAUUSD"
        ],
        "timeframes": [
            "M15",
            "H1",
            "H4"
        ]
    },
    "automated_limited": {
        "enabled": true,
        "max_volume_per_order": "0.02",
        "max_open_positions": 1,
        "max_daily_trades": 6,
        "risk_per_trade": "0.05",
        "daily_loss_limit": "0.10",
        "drawdown_stop": "0.15",
        "max_spread_pips": "3.0",
        "instruments": [
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "NZDUSD",
            "XAUUSD"
        ],
        "timeframes": [
            "M15",
            "H1"
        ],
        "require_triggered_scenario": false,
        "require_kill_switch_off": true,
        "killed": false
    }
}
'@

Backup-ConfigFile -FileName 'phase.json'
Write-ConfigFile -FileName 'phase.json' -Content $phaseJson
$null = Test-JsonFile -FileName 'phase.json'

# ---------------------------------------------------------------------------
# ۳) live.json
# ---------------------------------------------------------------------------
Write-Step "[3/4] live.json"

$liveJson = @'
{
    "instrument": "EURUSD",
    "instruments": [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "NZDUSD",
        "XAUUSD"
    ],
    "timeframes": [
        "M15",
        "H1"
    ],
    "primary_timeframe": "H1",
    "interval_seconds": 120,
    "schedule": {
        "mode": "always",
        "minute_offsets": [
            0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30,
            32, 34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58
        ],
        "active_hours_utc": [
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
            16, 17, 18, 19, 20, 21, 22, 23
        ],
        "active_days": [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri"
        ]
    },
    "send_no_trade": false,
    "max_signals_per_hour": 10,
    "history_bars": 500,
    "source_id": "mt5",
    "min_score_threshold": 0.15,
    "execute_orders": true
}
'@

Backup-ConfigFile -FileName 'live.json'
Write-ConfigFile -FileName 'live.json' -Content $liveJson
$null = Test-JsonFile -FileName 'live.json'

# ---------------------------------------------------------------------------
# ۴) اعتبارسنجی با Settings.load
# ---------------------------------------------------------------------------
Write-Step "[4/4] اعتبارسنجی (Settings.load)"

if ($DryRun) {
    Write-Warn2 "DRY-RUN: اعتبارسنجی انجام نشد"
    exit 0
}

Push-Location $ProjectRoot
try {
    $validation = & python -c "from fxars.config.settings import Settings; s = Settings.load(); print('OK'); print('risk_per_trade       :', s.risk.risk_per_trade); print('hard_cap             :', s.risk.hard_cap_risk_per_trade); print('daily_loss_limit     :', s.risk.daily_loss_limit); print('drawdown_warn        :', s.risk.drawdown_warn); print('drawdown_stop        :', s.risk.drawdown_stop); print('max_stop_pips        :', s.risk.max_stop_pips); print('max_daily_loss_cap   :', s.risk.max_daily_loss_hard_cap); print('max_drawdown_cap     :', s.risk.max_drawdown_hard_cap); print('backtest.risk        :', s.backtest.risk_per_trade); print('backtest.equity      :', s.backtest.initial_equity)" 2>&1

    if ($LASTEXITCODE -ne 0) {
        Write-Err2 "اعتبارسنجی شکست خورد:"
        $validation | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }
        Write-Host "`nبازگردانی از backup:" -ForegroundColor Yellow
        Write-Host "   Copy-Item '$BackupDir\*.json' '$ConfigDir' -Force" -ForegroundColor Yellow
        exit 1
    }

    $validation | ForEach-Object { Write-Host "   $_" }

    # ---------------------------------------------------------------------------
    # هم‌خوانی سه فایل
    # ---------------------------------------------------------------------------
    Write-Step "هم‌خوانی سه فایل"

    $check = & python -c @"
import json, sys
from pathlib import Path
root = Path('.')
live = json.loads((root / 'config' / 'live.json').read_text(encoding='utf-8'))
phase = json.loads((root / 'config' / 'phase.json').read_text(encoding='utf-8'))
settings = json.loads((root / 'config' / 'settings.json').read_text(encoding='utf-8'))
auto = phase['automated_limited']
risk = settings['risk']
checks = [
    ('instruments', live['instruments'] == auto['instruments']),
    ('timeframes', live['timeframes'] == auto['timeframes']),
    ('execute_orders', bool(live['execute_orders']) == bool(auto['enabled'])),
    ('risk_per_trade', str(auto['risk_per_trade']) == str(risk['risk_per_trade'])),
    ('daily_loss_limit', str(auto['daily_loss_limit']) == str(risk['daily_loss_limit'])),
    ('drawdown_stop', str(auto['drawdown_stop']) == str(risk['drawdown_stop'])),
    ('risk <= cap', float(risk['risk_per_trade']) <= float(risk['hard_cap_risk_per_trade'])),
    ('warn < stop', float(risk['drawdown_warn']) < float(risk['drawdown_stop'])),
    ('loss <= max_loss_cap', float(risk['daily_loss_limit']) <= float(risk['max_daily_loss_hard_cap'])),
    ('stop <= max_dd_cap', float(risk['drawdown_stop']) <= float(risk['max_drawdown_hard_cap'])),
]
all_ok = True
for name, ok in checks:
    mark = 'OK  ' if ok else 'FAIL'
    print(f'   [{mark}] {name}')
    if not ok:
        all_ok = False
sys.exit(0 if all_ok else 1)
"@ 2>&1

    if ($LASTEXITCODE -ne 0) {
        $check | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        Write-Err2 "برخی بررسی‌ها ناموفق‌اند"
        exit 1
    }
    $check | ForEach-Object { Write-Host $_ -ForegroundColor Green }

    Write-Host "`n=== ✅ پیکربندی با موفقیت اعمال شد ===" -ForegroundColor Green
    Write-Host "`nاجرای بعدی:" -ForegroundColor Cyan
    Write-Host "  python -m fxars live --live-config config/live.json --instruments EURUSD --max-cycles 1 --execute-orders" -ForegroundColor Cyan
    Write-Host "`nRollback در صورت نیاز:" -ForegroundColor DarkGray
    Write-Host "  Copy-Item '$BackupDir\*.json' '$ConfigDir' -Force" -ForegroundColor DarkGray
}
finally {
    Pop-Location
}
