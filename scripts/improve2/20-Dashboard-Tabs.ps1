# scripts/improve2/20-Dashboard-Tabs.ps1
#Requires -Version 7.0
<#
.SYNOPSIS
    بازطراحی داشبورد با ۷ تب جداگانه.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\project\FX',
    [switch]$DryRun,
    [switch]$NoPause
)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"

try {
    Write-Host "`n===[ گام ۲۰: داشبورد تب‌دار ]===" -ForegroundColor Cyan
    $dash = Join-Path $ProjectRoot 'fxars\ui\dashboard.py'
    if (-not (Test-Path -LiteralPath $dash)) { Write-Err "dashboard.py پیدا نشد"; return }

    $text = Read-TextFile -FullPath $dash
    if ($text -match 'FIX-20-DASHBOARD-TABS') {
        Write-Skip "از قبل patch شده"
        return
    }

    if ($DryRun) {
        Write-Warn2 "DRY-RUN: dashboard.py نوشته نشد"
        return
    }

    Backup-File -FullPath $dash

    $newContent = @'
"""داشبورد تک‌صفحه‌ای فارسی (RTL) با تب‌های جداگانه — FIX-20-DASHBOARD-TABS."""

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

/* Tabs */
.tabs{display:flex;gap:2px;background:var(--panel2);border-bottom:1px solid var(--border);padding:0 18px;overflow-x:auto;position:sticky;top:57px;z-index:9}
.tab{padding:12px 20px;background:transparent;border:none;color:var(--muted);cursor:pointer;font-family:inherit;font-size:13px;border-bottom:3px solid transparent;transition:.15s;white-space:nowrap}
.tab:hover{color:var(--text);background:rgba(255,255,255,.03)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent);background:rgba(56,189,248,.06)}

main{padding:20px;max-width:1400px;margin:0 auto}
.tab-panel{display:none}
.tab-panel.active{display:block}

/* Cards */
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:16px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 12px;color:#93c5fd;display:flex;justify-content:space-between;align-items:center;gap:8px}
.card h3{font-size:13px;margin:14px 0 8px;color:#93c5fd}

/* Grids */
.grid-2{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}
.grid-3{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.stat{background:var(--panel2);border:1px solid var(--border);border-radius:10px;padding:14px}
.stat .label{color:var(--muted);font-size:12px;margin-bottom:6px}
.stat .value{font-size:22px;color:var(--accent);font-weight:bold}
.stat .value.pos{color:var(--ok)}.stat .value.neg{color:var(--bad)}

/* Forms */
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

/* Tables */
table{width:100%;border-collapse:collapse;margin-top:8px}
th,td{padding:8px;border-bottom:1px solid var(--border);text-align:right;font-size:12px;vertical-align:top}
th{color:#93c5fd;font-weight:600}
tr.scenario-row{cursor:pointer}tr.scenario-row:hover{background:#0a1428}

/* Misc */
pre{white-space:pre-wrap;background:#0a1428;border:1px solid var(--border);border-radius:10px;padding:10px;max-height:400px;overflow:auto;font-size:12px;direction:ltr;text-align:left}
.muted{color:var(--muted);font-size:12px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;font-size:12px;margin-top:8px}
.kv b{color:var(--muted);font-weight:500}
.hidden{display:none!important}
.pos{color:var(--ok)}.neg{color:var(--bad)}
#toast{position:fixed;bottom:16px;left:16px;background:#0c4a6e;border:1px solid #0369a1;padding:10px 16px;border-radius:10px;opacity:0;transition:.3s;z-index:100;max-width:70vw;color:#e0f2fe}
#toast.show{opacity:1}

/* Login */
.login{max-width:440px;margin:7vh auto;background:var(--panel);border:1px solid var(--border);border-radius:18px;padding:26px;box-shadow:0 20px 50px #0008}
.login h1{color:var(--accent);font-size:20px;margin:0 0 4px}
.login .sub{color:var(--muted);font-size:12px;margin-bottom:14px}
#loginError{color:#f87171;min-height:18px;font-size:12px;margin-top:10px}
.help{margin-top:12px;padding-top:10px;border-top:1px dashed var(--border);font-size:12px;color:var(--muted);line-height:1.9}
.help code{background:#0a1428;padding:2px 6px;border-radius:6px;direction:ltr;display:inline-block}

/* Chart */
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

<!-- =================== LOGIN =================== -->
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
    <button type="button" class="ghost" onclick="quickDemo()">ورود سریع دمو (تحلیل‌گر)</button>
  </div>
  <div id="loginError" role="alert"></div>
  <div class="help">
    <b>راهنمای دمو:</b><br>
    تحلیل‌گر: <code>analyst</code> / <code>&lt;رمز دمو&gt;</code><br>
    مدیر: <code>admin</code> / <code>&lt;رمز دمو&gt;</code> + کد ۶ رقمی
  </div>
</div>

<!-- =================== APP =================== -->
<div id="appView" class="hidden">
  <header id="appHeader">
    <h1>FX-ARS</h1>
    <span class="badge" id="phaseBadge">فاز: —</span>
    <span class="badge" id="killBadge">Kill Switch: —</span>
    <span class="badge" id="configBadge" title="config hash">—</span>
    <div class="spacer"></div>
    <span class="muted" id="userLabel"></span>
    <button class="ghost" onclick="loadAll()">🔄 به‌روزرسانی</button>
    <button class="danger" onclick="logout()">خروج</button>
  </header>

  <!-- Tabs -->
  <nav class="tabs" role="tablist">
    <button class="tab active" data-tab="summary" role="tab">📊 خلاصه</button>
    <button class="tab" data-tab="chart" role="tab">📈 نمودار</button>
    <button class="tab" data-tab="analysis" role="tab">🎯 تحلیل</button>
    <button class="tab" data-tab="scenarios" role="tab">📋 سناریوها</button>
    <button class="tab" data-tab="risk" role="tab">🛡️ ریسک</button>
    <button class="tab" data-tab="backtest" role="tab">📊 بک‌تست</button>
    <button class="tab" data-tab="ops" role="tab">⚙️ عملیات</button>
  </nav>

  <main>

    <!-- ============ TAB 1: خلاصه ============ -->
    <section class="tab-panel active" data-panel="summary">
      <div class="grid-3">
        <div class="stat"><div class="label">وضعیت سرویس</div><div class="value" id="statHealth">—</div></div>
        <div class="stat"><div class="label">فاز</div><div class="value" id="statPhase">—</div></div>
        <div class="stat"><div class="label">Kill Switch</div><div class="value" id="statKill">—</div></div>
        <div class="stat"><div class="label">آخرین تصمیم</div><div class="value" id="statLastDecision">—</div></div>
        <div class="stat"><div class="label">تعداد سناریو فعال</div><div class="value" id="statScenarioCount">—</div></div>
        <div class="stat"><div class="label">Outbox در انتظار</div><div class="value" id="statOutbox">—</div></div>
      </div>

      <div class="grid-2">
        <div class="card">
          <h2>📌 آخرین تحلیل</h2>
          <div id="summaryLastAnalysis" class="muted">برای بارگذاری دکمه «به‌روزرسانی» را بزنید</div>
        </div>
        <div class="card">
          <h2>📋 سناریوهای فعال</h2>
          <div id="summaryScenarios" class="muted">—</div>
        </div>
      </div>
    </section>

    <!-- ============ TAB 2: نمودار ============ -->
    <section class="tab-panel" data-panel="chart">
      <div class="card">
        <h2>📈 نمودار زنده <span class="muted" id="chartStatus"></span></h2>
        <div class="chart-toolbar">
          <div><label>نماد</label><select id="chartInstrument"></select></div>
          <div><label>تایم‌فریم</label><select id="chartTimeframe"><option>M5</option><option>M15</option><option>M30</option><option selected>H1</option><option>H4</option><option>D1</option></select></div>
          <div><label>تعداد کندل</label><select id="chartLimit"><option>50</option><option selected>100</option><option>200</option><option>300</option></select></div>
          <button onclick="loadChart()">بارگذاری</button>
          <label><input type="checkbox" id="chartAutoRefresh" checked style="width:auto"> خودکار (10s)</label>
        </div>
        <div id="chartContainer"></div>
        <div id="rsiContainer"></div>
        <div class="legend">
          <span class="ema20">EMA20</span><span class="ema50">EMA50</span><span class="ema200">EMA200</span>
          <span class="entry">Entry</span><span class="stop">Stop</span><span class="target">Target</span>
        </div>
        <div id="chartInfo" class="muted" style="margin-top:10px"></div>
      </div>
    </section>

    <!-- ============ TAB 3: تحلیل ============ -->
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
        <h2>📊 نتیجه تصمیم <span class="muted" id="analysisStatus"></span></h2>
        <div id="analysisResult" class="muted">هنوز تحلیلی اجرا نشده</div>
        <pre id="decisionBox" class="hidden"></pre>
      </div>
    </section>

    <!-- ============ TAB 4: سناریوها ============ -->
    <section class="tab-panel" data-panel="scenarios">
      <div class="card">
        <h2>📋 فهرست سناریوها <span class="muted" id="scenarioCount"></span></h2>
        <table>
          <thead><tr><th>شناسه</th><th>نماد</th><th>جهت</th><th>وضعیت</th><th>انقضا</th></tr></thead>
          <tbody id="scenarioRows"></tbody>
        </table>
        <div id="scenarioDetail" class="muted" style="margin-top:12px">برای جزئیات روی سناریو کلیک کنید.</div>
      </div>
    </section>

    <!-- ============ TAB 5: ریسک ============ -->
    <section class="tab-panel" data-panel="risk">
      <div class="card">
        <h2>🛡️ ارزیابی ریسک</h2>
        <label>Equity حساب (USD)</label><input id="equity" value="10000">
        <label>سناریو</label><select id="riskScenario"></select>
        <div style="margin-top:12px"><button onclick="evaluateRisk()">ارزیابی ریسک (بدون سفارش)</button></div>
        <div id="riskResult" style="margin-top:12px"></div>
      </div>
    </section>

    <!-- ============ TAB 6: بک‌تست ============ -->
    <section class="tab-panel" data-panel="backtest">
      <div class="card">
        <h2>📊 اجرای بک‌تست</h2>
        <div class="row">
          <div><label>نماد</label><select id="btInstrument"></select></div>
          <div><label>بازه</label><select id="btSegment"><option>ALL</option><option>TRAIN</option><option>VALIDATION</option><option>LOCKED_TEST</option></select></div>
          <button onclick="runBacktest()">اجرای بک‌تست</button>
        </div>
        <div id="btResult" style="margin-top:12px" class="muted">هنوز بک‌تستی اجرا نشده</div>
      </div>
    </section>

    <!-- ============ TAB 7: عملیات ============ -->
    <section class="tab-panel" data-panel="ops">
      <div class="grid-2">
        <div class="card">
          <h2>🔍 سلامت سرویس</h2>
          <div class="kv" id="healthBox"></div>
        </div>
        <div class="card">
          <h2>🚨 Kill Switch</h2>
          <div class="kv" id="killBox"></div>
          <div class="row" style="margin-top:12px">
            <input id="killReason" placeholder="دلیل توقف اضطراری">
            <button class="danger" onclick="toggleKill(true)">فعال‌سازی</button>
            <button class="ghost" onclick="toggleKill(false)">غیرفعال‌سازی</button>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>📜 ممیزی</h2>
        <button onclick="loadAudit()">بارگذاری ممیزی</button>
        <pre id="auditBox" class="hidden"></pre>
      </div>
    </section>

  </main>
</div>

<div id="toast" role="status"></div>

<script>
// ============================================================
// State
// ============================================================
const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem("fxars_token") || "", user: null, meta: null, scenarios: [] };
const chartState = { chart: null, candleSeries: null, ema20: null, ema50: null, ema200: null, rsiChart: null, rsiSeries: null, timer: null };

// ============================================================
// Helpers
// ============================================================
function toast(message, ok) {
  const el = $("toast");
  el.textContent = message;
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
  if ((options.method || "GET") === "POST") {
    headers["Idempotency-Key"] = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
  }
  const response = await fetch(path, Object.assign({}, options, {headers}));
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = {raw: text}; }
  if (!response.ok) {
    const message = (data && data.error && data.error.message) || ("HTTP " + response.status);
    if (response.status === 401 && !path.includes("/auth/login")) { logout(false); }
    throw new Error(message);
  }
  return data;
}

// ============================================================
// Tabs
// ============================================================
function initTabs() {
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === name));
      // بارگذاری تنبل
      if (name === "chart" && !chartState.chart) { loadChart().catch(() => {}); }
    });
  });
}

// ============================================================
// Login
// ============================================================
async function login(event) {
  if (event) event.preventDefault();
  const button = $("loginButton");
  button.disabled = true;
  $("loginError").textContent = "";
  const body = {username: $("username").value.trim(), password: $("password").value};
  if ($("totp").value.trim()) body.totp_code = $("totp").value.trim();
  try {
    const data = await api("/api/v1/auth/login", {method: "POST", body: JSON.stringify(body)});
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem("fxars_token", data.token);
    showApp();
    await loadAll();
    toast("خوش آمدید " + (data.user.display_name || data.user.username), true);
  } catch (error) {
    $("loginError").textContent = error.message;
    $("loginButton").disabled = false;
  }
}

async function quickDemo() {
  $("loginError").textContent = "";
  try {
    const data = await api("/api/v1/auth/demo-login", {method: "POST", body: JSON.stringify({role: "ANALYST"})});
    state.token = data.token; state.user = data.user;
    localStorage.setItem("fxars_token", data.token);
    showApp(); await loadAll();
    toast("ورود دمو انجام شد", true);
  } catch (error) {
    $("loginError").textContent = "ورود سریع در دسترس نیست: " + error.message;
  }
}

async function fetchDemoCode() {
  try {
    const data = await api("/api/v1/auth/demo-totp?username=admin");
    $("totp").value = data.code;
    toast("کد MFA تا " + data.expires_in + " ثانیه معتبر است", true);
  } catch (error) {
    $("loginError").textContent = "دریافت کد دمو ممکن نیست: " + error.message;
  }
}

function showApp() {
  $("loginView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  $("appHeader").classList.remove("hidden");
}

function logout(reload = true) {
  if (state.token) {
    fetch("/api/v1/auth/logout", {method: "POST", headers: {"Authorization": "Bearer " + state.token, "Idempotency-Key": String(Date.now())}}).catch(() => {});
  }
  state.token = ""; state.user = null;
  localStorage.removeItem("fxars_token");
  if (reload) { window.location.reload(); return; }
  $("appView").classList.add("hidden");
  $("appHeader").classList.add("hidden");
  $("loginView").classList.remove("hidden");
  $("loginButton").disabled = false;
  $("password").value = ""; $("totp").value = "";
}

// ============================================================
// Load all
// ============================================================
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
    $("healthBox").innerHTML = "<b>وضعیت</b><span>" + esc(health.status) + "</span>" +
      "<b>زمان</b><span>" + esc(health.time) + "</span>" +
      "<b>ممیزی</b><span>" + (health.audit ? "معتبر" : "ناسازگار") + "</span>";
    $("statHealth").textContent = health.status === "ok" ? "✅ سالم" : "⚠️ " + health.status;
    $("statPhase").textContent = meta.phase;
    $("statKill").textContent = meta.killswitch.active ? "🔴 فعال" : "🟢 غیرفعال";
    $("statKill").className = "value " + (meta.killswitch.active ? "neg" : "pos");

    const instruments = await api("/api/v1/instruments");
    const options = instruments.items.map(i => "<option>" + esc(i.instrument_id) + "</option>").join("");
    $("instrument").innerHTML = options;
    $("btInstrument").innerHTML = options;
    $("chartInstrument").innerHTML = options;

    await loadScenarios();
    await loadCandles();
    showApp();
  } catch (error) {
    toast(error.message, false);
    $("loginError").textContent = error.message;
  }
}

// ============================================================
// Summary tab
// ============================================================
async function refreshSummary() {
  try {
    const scenarios = await api("/api/v1/scenarios?limit=5");
    $("statScenarioCount").textContent = scenarios.count;
    if (scenarios.items.length > 0) {
      const active = scenarios.items.filter(s => ["WATCH","ARMED","TRIGGERED"].includes(s.status));
      $("summaryScenarios").innerHTML = active.length === 0
        ? "<span class='muted'>سناریو فعالی نیست</span>"
        : active.map(s => "<div style='padding:6px 0;border-bottom:1px solid var(--border)'>" +
            "<b>" + esc(s.scenario_id.slice(0,12)) + "</b> — " + esc(s.instrument_id) + " " + esc(s.direction) +
            " <span class='muted'>(" + esc(s.status) + ")</span></div>").join("");
    } else {
      $("summaryScenarios").innerHTML = "<span class='muted'>سناریویی ثبت نشده</span>";
    }
  } catch (e) { /* ignore */ }
}

// ============================================================
// Chart tab
// ============================================================
async function loadChart() {
  const instrument = $("chartInstrument").value || "EURUSD";
  const timeframe = $("chartTimeframe").value || "H1";
  const limit = parseInt($("chartLimit").value || "100", 10);
  $("chartStatus").textContent = "در حال بارگذاری...";
  try {
    const data = await api("/api/v1/live/chart?instrument=" + encodeURIComponent(instrument) + "&timeframe=" + timeframe + "&limit=" + limit);
    renderChart(data);
    $("chartStatus").textContent = data.count + " کندل";
    $("chartInfo").textContent = data.instrument + " / " + data.timeframe + " — " + data.count + " کندل — منبع: " + (data.source || "?") + " — " + new Date().toLocaleTimeString("fa-IR");
  } catch (error) {
    $("chartStatus").textContent = "خطا";
    toast("بارگذاری نمودار ناموفق: " + error.message, false);
  }
}

function renderChart(data) {
  if (!window.LightweightCharts) { toast("LightweightCharts بارگذاری نشد", false); return; }
  const LWC = window.LightweightCharts;
  if (chartState.chart) { chartState.chart.remove(); chartState.chart = null; }
  if (chartState.rsiChart) { chartState.rsiChart.remove(); chartState.rsiChart = null; }

  const container = $("chartContainer");
  const rsiContainer = $("rsiContainer");
  const chart = LWC.createChart(container, {
    width: container.clientWidth, height: 420,
    layout: { background: { color: "#0a1428" }, textColor: "#94a3b8" },
    grid: { vertLines: { color: "#1e3a5f" }, horzLines: { color: "#1e3a5f" } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1e3a5f" },
    rightPriceScale: { borderColor: "#1e3a5f" },
    crosshair: { mode: LWC.CrosshairMode.Normal },
  });
  const candleSeries = chart.addCandlestickSeries({
    upColor: "#22c55e", downColor: "#ef4444",
    borderUpColor: "#22c55e", borderDownColor: "#ef4444",
    wickUpColor: "#22c55e", wickDownColor: "#ef4444",
  });
  candleSeries.setData(data.candles.map(c => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));

  const ema20 = chart.addLineSeries({ color: "#fbbf24", lineWidth: 1, title: "EMA20" });
  const ema50 = chart.addLineSeries({ color: "#f472b6", lineWidth: 1, title: "EMA50" });
  const ema200 = chart.addLineSeries({ color: "#a78bfa", lineWidth: 1, title: "EMA200" });
  const times = data.candles.map(c => c.time);
  function setEma(series, values) {
    if (!values || !values.length) return;
    const points = [];
    for (let i = 0; i < Math.min(values.length, times.length); i++) {
      if (values[i] !== null && values[i] !== undefined) points.push({ time: times[i], value: values[i] });
    }
    series.setData(points);
  }
  setEma(ema20, data.indicators.ema20);
  setEma(ema50, data.indicators.ema50);
  setEma(ema200, data.indicators.ema200);

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
    const rsiPoints = [];
    for (let i = 0; i < Math.min(data.indicators.rsi14.length, times.length); i++) {
      if (data.indicators.rsi14[i] !== null && data.indicators.rsi14[i] !== undefined) rsiPoints.push({ time: times[i], value: data.indicators.rsi14[i] });
    }
    rsiSeries.setData(rsiPoints);
  }
  rsiSeries.createPriceLine({ price: 70, color: "#ef4444", lineWidth: 1, lineStyle: 2 });
  rsiSeries.createPriceLine({ price: 30, color: "#22c55e", lineWidth: 1, lineStyle: 2 });
  rsiChart.timeScale().fitContent();

  chart.timeScale().subscribeVisibleLogicalRangeChange(r => { if (r) rsiChart.timeScale().setVisibleLogicalRange(r); });
  rsiChart.timeScale().subscribeVisibleLogicalRangeChange(r => { if (r) chart.timeScale().setVisibleLogicalRange(r); });

  const ro = new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth });
    rsiChart.applyOptions({ width: rsiContainer.clientWidth });
  });
  ro.observe(container);

  chartState.chart = chart; chartState.candleSeries = candleSeries;
  chartState.ema20 = ema20; chartState.ema50 = ema50; chartState.ema200 = ema200;
  chartState.rsiChart = rsiChart; chartState.rsiSeries = rsiSeries;

  if (chartState.timer) clearInterval(chartState.timer);
  chartState.timer = setInterval(() => { if ($("chartAutoRefresh").checked) loadChart().catch(() => {}); }, 10000);
}

// ============================================================
// Analysis tab
// ============================================================
async function loadCandles() {
  const instrument = $("instrument").value || "EURUSD";
  const timeframe = $("timeframe").value || "H1";
  try {
    const data = await api("/api/v1/market-data/candles?instrument_id=" + encodeURIComponent(instrument) + "&timeframe=" + timeframe + "&limit=5");
    const last = data.items[data.items.length - 1];
    if (!last) { $("marketSummary").innerHTML = "<b>داده</b><span>موجود نیست</span>"; return; }
    $("marketSummary").innerHTML =
      "<b>آخرین کندل</b><span>" + esc(last.bar_open_time_utc) + "</span>" +
      "<b>Close</b><span>" + esc(last.close) + "</span>" +
      "<b>Spread</b><span>" + esc(last.spread) + "</span>" +
      "<b>کیفیت</b><span>" + esc(last.quality_status) + "</span>";
  } catch (error) { toast(error.message, false); }
}

async function runAnalysis() {
  $("analysisStatus").textContent = "در حال اجرا...";
  try {
    const data = await api("/api/v1/analysis-runs", {method: "POST", body: JSON.stringify({instrument_id: $("instrument").value, timeframe: $("timeframe").value})});
    const d = data.decision;
    const run = data.run;
    const color = d.action === "LONG" ? "pos" : d.action === "SHORT" ? "neg" : "muted";
    $("analysisResult").innerHTML =
      "<div class='kv'>" +
        "<b>اجرا</b><span>" + esc(run.run_id.slice(0, 16)) + "…</span>" +
        "<b>وضعیت</b><span>" + esc(run.status) + "</span>" +
        "<b>تصمیم</b><span class='" + color + "'>" + esc(d.action) + "</span>" +
        "<b>امتیاز</b><span>" + num(d.score, 3) + "</span>" +
        "<b>پوشش</b><span>" + Math.round(d.coverage * 100) + "%</span>" +
        "<b>پایداری</b><span>" + Math.round(d.stability * 100) + "%</span>" +
        (d.no_trade_reason ? "<b>دلیل NO TRADE</b><span>" + esc(d.no_trade_reason) + "</span>" : "") +
        (data.scenario ? "<b>سناریو</b><span>" + esc(data.scenario.scenario_id) + "</span>" : "") +
      "</div>";
    $("decisionBox").classList.remove("hidden");
    $("decisionBox").textContent = JSON.stringify(d, null, 2);
    $("analysisStatus").textContent = "✅ " + run.run_id.slice(0, 12);
    await loadScenarios();
    await refreshSummary();
    if (data.scenario) $("riskScenario").value = data.scenario.scenario_id;
    toast("تحلیل ثبت شد", true);
  } catch (error) {
    $("analysisStatus").textContent = "";
    toast(error.message, false);
  }
}

// ============================================================
// Scenarios tab
// ============================================================
async function loadScenarios() {
  try {
    const data = await api("/api/v1/scenarios?limit=25");
    state.scenarios = data.items;
    $("scenarioCount").textContent = data.count + " مورد";
    $("scenarioRows").innerHTML = data.items.map(s =>
      "<tr class='scenario-row' data-id='" + esc(s.scenario_id) + "'>" +
      "<td>" + esc(s.scenario_id.slice(0, 12)) + "</td>" +
      "<td>" + esc(s.instrument_id) + "</td>" +
      "<td>" + esc(s.direction) + "</td>" +
      "<td>" + esc(s.status) + "</td>" +
      "<td>" + esc(s.expiry_at) + "</td></tr>"
    ).join("") || "<tr><td colspan=5 class='muted'>سناریویی ثبت نشده است.</td></tr>";
    document.querySelectorAll(".scenario-row").forEach(row => {
      row.addEventListener("click", () => showScenario(row.dataset.id));
    });
    $("riskScenario").innerHTML = data.items.map(s =>
      "<option value='" + esc(s.scenario_id) + "'>" + esc(s.scenario_id.slice(0, 12)) + " — " + esc(s.direction) + " (" + esc(s.status) + ")</option>"
    ).join("");
    await refreshSummary();
  } catch (error) { toast(error.message, false); }
}

async function showScenario(id) {
  try {
    const data = await api("/api/v1/scenarios/" + encodeURIComponent(id));
    const s = data.scenario;
    $("scenarioDetail").innerHTML =
      "<div class='kv'><b>ورود</b><span>" + esc(JSON.stringify(s.entry_condition)) + "</span>" +
      "<b>محدوده</b><span>" + esc(s.entry_zone ? s.entry_zone.low + " — " + s.entry_zone.high : "—") + "</span>" +
      "<b>ابطال</b><span>" + esc(JSON.stringify(s.invalidation_condition)) + "</span>" +
      "<b>حد ضرر</b><span>" + esc(JSON.stringify(s.stop_logic)) + "</span>" +
      "<b>اهداف</b><span>" + esc((s.target_logic || []).map(t => t.value + "R @ " + t.price).join(" | ")) + "</span>" +
      "<b>توضیح</b><span>" + esc(s.decision_explanation) + "</span></div>" +
      "<div class='muted' style='margin-top:8px'>گذارها: " + (data.transitions.map(t => t.from_status + "→" + t.to_status).join(", ") || "—") + "</div>";
  } catch (error) { toast(error.message, false); }
}

// ============================================================
// Risk tab
// ============================================================
async function evaluateRisk() {
  const scenarioId = $("riskScenario").value;
  if (!scenarioId) { toast("ابتدا تحلیل اجرا کنید", false); return; }
  try {
    const account = {
      equity: $("equity").value, balance: $("equity").value, free_margin: $("equity").value,
      taken_at: new Date().toISOString(), currency: "USD", leverage: "100",
      open_positions: 0, positions: []
    };
    const data = await api("/api/v1/risk/evaluate", {method: "POST", body: JSON.stringify({scenario_id: scenarioId, account})});
    const d = data.decision;
    $("riskResult").innerHTML = "<div class='kv'><b>وضعیت</b><span class='" + (d.approved ? "pos" : "neg") + "'>" +
      (d.approved ? "✅ تأیید" : "❌ رد") + " (" + esc(d.reason_code) + ")</span>" +
      "<b>حجم</b><span>" + esc(d.position_size) + " lot</span>" +
      "<b>ریسک</b><span>" + esc(d.risk_amount) + " " + esc(d.risk_currency) + "</span>" +
      "<b>کنترل‌های ردشده</b><span>" + (d.checks_failed.join(", ") || "—") + "</span>" +
      "<b>دلیل</b><span>" + esc(d.reason_detail) + "</span></div>";
    toast(d.approved ? "ریسک تأیید شد" : "ریسک رد شد", d.approved);
  } catch (error) { toast(error.message, false); }
}

// ============================================================
// Backtest tab
// ============================================================
async function runBacktest() {
  try {
    $("btResult").innerHTML = "<span class='muted'>در حال اجرا (چند ثانیه)...</span>";
    const data = await api("/api/v1/backtests", {method: "POST", body: JSON.stringify({instrument_id: $("btInstrument").value, timeframe: "H1", segment: $("btSegment").value})});
    const m = data.run.metrics;
    $("btResult").innerHTML = "<div class='kv'><b>معاملات</b><span>" + esc(m.trade_count) + "</span>" +
      "<b>سود خالص</b><span>" + esc(num(m.net_profit)) + "</span>" +
      "<b>Profit Factor</b><span>" + esc(num(m.profit_factor)) + "</span>" +
      "<b>Max DD</b><span>" + esc(num(m.max_drawdown_pct)) + "%</span>" +
      "<b>Sharpe</b><span>" + esc(num(m.sharpe)) + "</span>" +
      "<b>هزینه کل</b><span>" + esc(num(m.costs.total)) + "</span></div>" +
      "<p class='muted'><a style='color:#7dd3fc' target='_blank' href='/api/v1/backtests/" + data.run.run_id + "/report?format=html'>گزارش کامل HTML</a></p>";
  } catch (error) {
    $("btResult").innerHTML = "";
    toast(error.message, false);
  }
}

// ============================================================
// Ops tab
// ============================================================
async function toggleKill(active) {
  try {
    const reason = $("killReason").value || (active ? "توقف اضطراری دستی" : "بازگشت به وضعیت عادی");
    await api("/api/v1/killswitch", {method: "POST", body: JSON.stringify({active, reason})});
    toast(active ? "Kill Switch فعال شد" : "Kill Switch غیرفعال شد", true);
    await loadAll();
  } catch (error) { toast(error.message, false); }
}

async function loadAudit() {
  try {
    const data = await api("/api/v1/audit-events?limit=30");
    $("auditBox").classList.remove("hidden");
    $("auditBox").textContent = JSON.stringify(data, null, 2);
  } catch (error) { toast(error.message, false); }
}

// ============================================================
// Init
// ============================================================
initTabs();
if (state.token) { showApp(); loadAll(); } else { $("loginView").classList.remove("hidden"); }
</script>
</body>
</html>"""
'@

    Write-TextFile -FullPath $dash -Content $newContent
    Write-Ok "dashboard.py بازنویسی شد (۷ تب)"

    if (-not (Test-PyCompile -FullPath $dash)) {
        Write-Err "py_compile ناموفق — rollback"
        Restore-File -FullPath $dash | Out-Null
        return
    }
    Write-Ok "syntax compiles"

    Write-Host "`n===[ DONE: gam 20 ]===" -ForegroundColor Green
    Write-Host "`nگام بعدی:" -ForegroundColor Cyan
    Write-Host "  python -m fxars serve --port 8080" -ForegroundColor Cyan
    Write-Host "  سپس مرورگر: http://127.0.0.1:8080/" -ForegroundColor Cyan
}
catch {
    Write-Err "خطا: $_"
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
}
finally {
    Pause-IfNeeded -NoPause:$NoPause
}
