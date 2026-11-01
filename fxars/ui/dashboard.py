"""داشبورد تک‌صفحه‌ای فارسی (RTL) با JavaScript خالص."""

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
header{display:flex;gap:10px;align-items:center;padding:10px 18px;background:var(--panel);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5;flex-wrap:wrap}
header h1{font-size:17px;margin:0;color:var(--accent);white-space:nowrap}
header .spacer{flex:1}
.badge{padding:3px 10px;border-radius:999px;font-size:12px;border:1px solid var(--border);background:var(--panel2)}
.badge.ok{color:var(--ok);border-color:#14532d}.badge.bad{color:var(--bad);border-color:#7f1d1d}.badge.warn{color:var(--warn);border-color:#78350f}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px;padding:16px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:14px;min-height:180px}
.card h2{font-size:14px;margin:0 0 10px;color:#93c5fd;display:flex;justify-content:space-between;align-items:center;gap:8px}
label{display:block;color:var(--muted);font-size:12px;margin:8px 0 4px}
input,select,button,textarea{font-family:inherit;font-size:13px}
input,select{width:100%;padding:9px;border-radius:9px;border:1px solid var(--border);background:#0a1428;color:var(--text)}
input:focus,select:focus{outline:2px solid #0369a1;outline-offset:1px}
button{padding:9px 14px;border-radius:9px;border:1px solid #0369a1;background:#0c4a6e;color:#e0f2fe;cursor:pointer;white-space:nowrap}
button:hover{background:#075985}button:disabled{opacity:.55;cursor:not-allowed}
button.danger{border-color:#991b1b;background:#7f1d1d}button.ghost{background:transparent;border-color:var(--border);color:var(--muted)}
button.link{background:none;border:none;color:var(--accent);padding:0;text-decoration:underline;cursor:pointer}
.row{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap}.row>*{flex:1;min-width:130px}.row button{flex:0 0 auto}
table{width:100%;border-collapse:collapse;margin-top:8px}th,td{padding:6px;border-bottom:1px solid var(--border);text-align:right;font-size:12px;vertical-align:top}
th{color:#93c5fd;font-weight:600}
tr.scenario-row{cursor:pointer}tr.scenario-row:hover{background:#0a1428}
pre{white-space:pre-wrap;background:#0a1428;border:1px solid var(--border);border-radius:10px;padding:10px;max-height:280px;overflow:auto;font-size:12px;direction:ltr;text-align:left}
.muted{color:var(--muted);font-size:12px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 10px;font-size:12px;margin-top:8px}
.kv b{color:var(--muted);font-weight:500}
.login{max-width:440px;margin:7vh auto;background:var(--panel);border:1px solid var(--border);border-radius:18px;padding:26px;box-shadow:0 20px 50px #0008}
.login h1{color:var(--accent);font-size:20px;margin:0 0 4px}
.login .sub{color:var(--muted);font-size:12px;margin-bottom:14px}
.hidden{display:none!important}
.tag{display:inline-block;padding:2px 8px;border-radius:8px;background:#0a1428;border:1px solid var(--border);font-size:11px;margin:2px}
.pos{color:var(--ok)}.neg{color:var(--bad)}
#toast{position:fixed;bottom:16px;left:16px;background:#0c4a6e;border:1px solid #0369a1;padding:10px 16px;border-radius:10px;opacity:0;transition:.3s;z-index:50;max-width:70vw}
#toast.show{opacity:1}
#loginError{color:#f87171;min-height:18px;font-size:12px;margin-top:10px}
.help{margin-top:12px;padding-top:10px;border-top:1px dashed var(--border);font-size:12px;color:var(--muted);line-height:1.9}
.help code{background:#0a1428;padding:2px 6px;border-radius:6px;direction:ltr;display:inline-block}
.inline{display:flex;gap:8px;align-items:center}
.inline input[type=checkbox]{width:auto}
</style>
</head>
<body>
<header id="appHeader" class="hidden">
  <h1>FX-ARS</h1>
  <span class="badge" id="phaseBadge">فاز: —</span>
  <span class="badge" id="killBadge">Kill Switch: —</span>
  <span class="badge" id="configBadge" title="config hash">—</span>
  <div class="spacer"></div>
  <span class="muted" id="userLabel"></span>
  <button class="ghost" onclick="loadAll()">به‌روزرسانی</button>
  <button class="danger" onclick="logout()">خروج</button>
</header>

<div id="loginView" class="login">
  <h1>ورود به FX-ARS</h1>
  <div class="sub">سامانه تحلیل و پشتیبانی تصمیم — فاز MVP-1 (فقط‌خواندنی)</div>
  <form id="loginForm" onsubmit="login(event)">
    <label for="username">نام کاربری</label>
    <input id="username" autocomplete="username" value="analyst" autofocus>
    <label for="password">رمز عبور</label>
    <input id="password" type="password" autocomplete="current-password">
    <div class="inline" style="margin-top:6px">
      <input type="checkbox" id="showPassword" onchange="togglePassword()">
      <label for="showPassword" style="margin:0">نمایش رمز</label>
    </div>
    <label for="totp">کد MFA (برای نقش‌های مدیریتی)</label>
    <div class="row">
      <input id="totp" inputmode="numeric" autocomplete="one-time-code" placeholder="۶ رقم" maxlength="6">
      <button type="button" class="ghost" onclick="fetchDemoCode()">کد دمو</button>
    </div>
    <div style="margin-top:16px"><button id="loginButton" type="submit" style="width:100%">ورود</button></div>
  </form>
  <div class="inline" style="margin-top:10px">
    <button type="button" class="ghost" onclick="quickDemo()">ورود سریع دمو (تحلیل‌گر)</button>
  </div>
  <div id="loginError" role="alert"></div>
  <div class="help">
    <b>راهنمای دمو:</b><br>
    تحلیل‌گر: <code>analyst</code> / <code>AnalystDemo123!</code> (بدون MFA)<br>
    مدیر: <code>admin</code> / <code>AdminDemo12345!</code> + کد ۶ رقمی<br>
    اگر کد MFA ندارید، دکمه «کد دمو» را بزنید (فقط در محیط توسعه/لوکال فعال است).
  </div>
</div>

<main id="appView" class="hidden">
  <section class="card">
    <h2>تحلیل بازار <span class="muted" id="analysisStatus"></span></h2>
    <div class="row">
      <div><label>نماد</label><select id="instrument"></select></div>
      <div><label>تایم‌فریم</label><select id="timeframe"><option>H1</option><option>M15</option><option>H4</option><option>D1</option></select></div>
      <button onclick="runAnalysis()">اجرای تحلیل</button>
    </div>
    <div class="kv" id="marketSummary"></div>
    <pre id="decisionBox" class="hidden"></pre>
  </section>

  <section class="card">
    <h2>سناریوها <span class="muted" id="scenarioCount"></span></h2>
    <table><thead><tr><th>شناسه</th><th>نماد</th><th>جهت</th><th>وضعیت</th><th>انقضا</th></tr></thead><tbody id="scenarioRows"></tbody></table>
    <div id="scenarioDetail" class="muted" style="margin-top:8px">برای جزئیات روی سناریو کلیک کنید.</div>
  </section>

  <section class="card">
    <h2>دروازه ریسک</h2>
    <label>Equity حساب (USD)</label><input id="equity" value="10000">
    <label>سناریو</label><select id="riskScenario"></select>
    <div style="margin-top:10px"><button onclick="evaluateRisk()">ارزیابی ریسک (بدون سفارش)</button></div>
    <div id="riskResult"></div>
  </section>

  <section class="card">
    <h2>پژوهش و بک‌تست</h2>
    <div class="row">
      <div><label>نماد</label><select id="btInstrument"></select></div>
      <div><label>بازه</label><select id="btSegment"><option>ALL</option><option>TRAIN</option><option>VALIDATION</option><option>LOCKED_TEST</option></select></div>
      <button onclick="runBacktest()">اجرای بک‌تست</button>
    </div>
    <div id="btResult" style="margin-top:8px"></div>
  </section>

  <section class="card">
    <h2>عملیات و ممیزی</h2>
    <div class="kv" id="healthBox"></div>
    <div class="row" style="margin-top:10px">
      <input id="killReason" placeholder="دلیل توقف اضطراری">
      <button class="danger" onclick="toggleKill(true)">فعال‌سازی</button>
      <button class="ghost" onclick="toggleKill(false)">غیرفعال‌سازی</button>
    </div>
    <pre id="auditBox" class="hidden"></pre>
  </section>
</main>
<div id="toast" role="status"></div>

<script>
const $ = (id) => document.getElementById(id);
const state = { token: localStorage.getItem("fxars_token") || "", user: null, meta: null, scenarios: [] };

function toast(message, ok) {
  const el = $("toast");
  el.textContent = message;
  el.style.borderColor = ok ? "#166534" : "#991b1b";
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 3500);
}
function num(value, digits) { return (value === null || value === undefined) ? "—" : Number(value).toFixed(digits === undefined ? 2 : digits); }
function esc(value) { return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
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
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem("fxars_token", data.token);
    showApp();
    await loadAll();
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
  $("appHeader").classList.remove("hidden");
  $("appView").classList.remove("hidden");
}

function logout(reload = true) {
  if (state.token) {
    fetch("/api/v1/auth/logout", {method: "POST", headers: {"Authorization": "Bearer " + state.token, "Idempotency-Key": String(Date.now())}}).catch(() => {});
  }
  state.token = "";
  state.user = null;
  localStorage.removeItem("fxars_token");
  if (reload) { window.location.reload(); return; }
  $("appView").classList.add("hidden");
  $("appHeader").classList.add("hidden");
  $("loginView").classList.remove("hidden");
  $("loginButton").disabled = false;
  $("password").value = "";
  $("totp").value = "";
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
    $("healthBox").innerHTML = "<b>وضعیت</b><span>" + esc(health.status) + "</span>" +
      "<b>زمان</b><span>" + esc(health.time) + "</span>" +
      "<b>ممیزی</b><span>" + (health.audit ? "معتبر" : "ناسازگار") + "</span>";
    const instruments = await api("/api/v1/instruments");
    const options = instruments.items.map(i => "<option>" + esc(i.instrument_id) + "</option>").join("");
    $("instrument").innerHTML = options;
    $("btInstrument").innerHTML = options;
    await loadScenarios();
    await loadCandles();
    showApp();
  } catch (error) {
    toast(error.message, false);
    $("loginError").textContent = error.message;
  }
}

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
    const decision = data.decision;
    const run = data.run;
    $("decisionBox").classList.remove("hidden");
    $("decisionBox").textContent = JSON.stringify({
      run_id: run.run_id, status: run.status, action: decision.action, score: decision.score,
      coverage: decision.coverage, stability: decision.stability, no_trade_reason: decision.no_trade_reason,
      family_scores: decision.family_scores, scenario_id: data.scenario ? data.scenario.scenario_id : null
    }, null, 2);
    $("analysisStatus").textContent = "اجرا شد: " + run.run_id.slice(0, 12);
    await loadScenarios();
    if (data.scenario) { $("riskScenario").value = data.scenario.scenario_id; }
    toast("تحلیل ثبت شد", true);
  } catch (error) {
    $("analysisStatus").textContent = "";
    toast(error.message, false);
  }
}

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
    ).join("") || "<tr><td colspan=5 class=muted>سناریویی ثبت نشده است.</td></tr>";
    document.querySelectorAll(".scenario-row").forEach(row => {
      row.addEventListener("click", () => showScenario(row.dataset.id));
    });
    $("riskScenario").innerHTML = data.items.map(s =>
      "<option value='" + esc(s.scenario_id) + "'>" + esc(s.scenario_id.slice(0, 12)) + " — " + esc(s.direction) + " (" + esc(s.status) + ")</option>"
    ).join("");
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
      "<div class='muted'>گذارها: " + (data.transitions.map(t => t.from_status + "→" + t.to_status).join(", ") || "—") + "</div>";
  } catch (error) { toast(error.message, false); }
}

async function evaluateRisk() {
  const scenarioId = $("riskScenario").value;
  if (!scenarioId) { toast("ابتدا تحلیل اجرا کنید", false); return; }
  try {
    const account = {
      equity: $("equity").value, balance: $("equity").value, free_margin: $("equity").value,
      taken_at: new Date().toISOString(), currency: "USD", leverage: "100", open_positions: 0, positions: []
    };
    const data = await api("/api/v1/risk/evaluate", {method: "POST", body: JSON.stringify({scenario_id: scenarioId, account})});
    const d = data.decision;
    $("riskResult").innerHTML = "<div class='kv'><b>وضعیت</b><span class='" + (d.approved ? "pos" : "neg") + "'>" +
      (d.approved ? "تأیید" : "رد") + " (" + esc(d.reason_code) + ")</span>" +
      "<b>حجم</b><span>" + esc(d.position_size) + " lot</span>" +
      "<b>ریسک</b><span>" + esc(d.risk_amount) + " " + esc(d.risk_currency) + "</span>" +
      "<b>کنترل‌های ردشده</b><span>" + (d.checks_failed.join(", ") || "—") + "</span>" +
      "<b>دلیل</b><span>" + esc(d.reason_detail) + "</span></div>";
    toast(d.approved ? "ریسک تأیید شد" : "ریسک رد شد", d.approved);
  } catch (error) { toast(error.message, false); }
}

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

async function toggleKill(active) {
  try {
    const reason = $("killReason").value || (active ? "توقف اضطراری دستی" : "بازگشت به وضعیت عادی");
    await api("/api/v1/killswitch", {method: "POST", body: JSON.stringify({active, reason})});
    toast(active ? "Kill Switch فعال شد" : "Kill Switch غیرفعال شد", true);
    await loadAll();
  } catch (error) { toast(error.message, false); }
}

if (state.token) { showApp(); loadAll(); } else { $("loginView").classList.remove("hidden"); }
</script>
</body>
</html>"""
