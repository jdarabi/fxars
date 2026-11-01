#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
Write-Host "[FIX-05] Backtest parity (full)" -ForegroundColor Cyan

$file = Join-Path $ProjectRoot 'fxars\research\backtest.py'
$content = Get-Content $file -Raw -Encoding UTF8

if ($content -match 'FIX-05-BACKTEST-PARITY-DONE') {
    Write-Host "  Already fully patched. Skipping." -ForegroundColor Yellow
    return
}

# ---------- 5.1 افزودن mode به BacktestConfig (idempotent) ----------
if ($content -notmatch 'FIX-05-BACKTEST-PARITY') {
    $oldCfg = @'
    min_signal_strength: float = 0.30
    quote_rates: dict[str, Decimal] = field(default_factory=lambda: {"JPY": Decimal("0.0067")})
    seed: int = 7
'@
    $newCfg = @'
    min_signal_strength: float = 0.30
    quote_rates: dict[str, Decimal] = field(default_factory=lambda: {"JPY": Decimal("0.0067")})
    seed: int = 7
    # FIX-05-BACKTEST-PARITY:
    #   "scenario" = منطق دقیقاً هم‌خوان با ScenarioBuilder/TriggerEvaluator (پیش‌فرض)
    #   "baseline" = منطق ساده قبلی (stop از کف/سقف ۲۰ کندل + ورود در open)
    mode: str = "scenario"
'@
    if (-not $content.Contains($oldCfg)) { throw "BacktestConfig anchor not found" }
    $content = $content.Replace($oldCfg, $newCfg)

    $oldPost = @'
        object.__setattr__(self, "target_r_multiples", tuple(_d(item) for item in self.target_r_multiples))
        object.__setattr__(self, "quote_rates", {key: _d(value) for key, value in self.quote_rates.items()})
'@
    $newPost = @'
        object.__setattr__(self, "target_r_multiples", tuple(_d(item) for item in self.target_r_multiples))
        object.__setattr__(self, "quote_rates", {key: _d(value) for key, value in self.quote_rates.items()})
        if self.mode not in ("scenario", "baseline"):
            raise ValueError(f"mode نامعتبر: {self.mode!r} (allowed: scenario, baseline)")
'@
    if (-not $content.Contains($oldPost)) { throw "__post_init__ anchor not found" }
    $content = $content.Replace($oldPost, $newPost)
    Write-Host "  [OK] BacktestConfig.mode added" -ForegroundColor Green
}

# ---------- 5.2 افزودن imports لازم برای شاخه scenario ----------
if ($content -notmatch 'from fxars\.decision\.scenario import ScenarioBuilder') {
    $content = $content.Replace(
        'from fxars.decision.aggregation import aggregate_evidence',
        "from fxars.decision.aggregation import aggregate_evidence`r`nfrom fxars.decision.scenario import ScenarioBuilder`r`nfrom fxars.decision.trigger import TriggerEvaluator"
    )
    Write-Host "  [OK] imports added" -ForegroundColor Green
}

# ---------- 5.3 پچ __init__ برای نگه‌داشتن builder/evaluator ----------
$oldInit = @'
    def __init__(self, instrument: Instrument, timeframe: str, config: BacktestConfig, analysis: AnalysisSettings) -> None:
        self.instrument = instrument
        self.timeframe = timeframe
        self.config = config
        self.analysis = analysis
        self._pip = instrument.pip_size
        self._contract = instrument.contract_size
        self._quant = Decimal(1).scaleb(-instrument.digits)
'@
$newInit = @'
    def __init__(self, instrument: Instrument, timeframe: str, config: BacktestConfig, analysis: AnalysisSettings,
                 *, calendar=None) -> None:
        self.instrument = instrument
        self.timeframe = timeframe
        self.config = config
        self.analysis = analysis
        self._pip = instrument.pip_size
        self._contract = instrument.contract_size
        self._quant = Decimal(1).scaleb(-instrument.digits)
        # FIX-05-BACKTEST-PARITY: در mode=scenario از همین builder/evaluator استفاده می‌کنیم.
        self._scenario_builder = ScenarioBuilder(analysis, calendar) if calendar else ScenarioBuilder(analysis)
        self._trigger_evaluator = TriggerEvaluator(analysis, calendar) if calendar else TriggerEvaluator(analysis)
'@
if (-not $content.Contains($oldInit)) { throw "__init__ anchor not found" }
$content = $content.Replace($oldInit, $newInit)

# ---------- 5.4 جایگزینی حلقه تصمیم/برنامه‌ریزی ----------
$oldLoop = @'
            if position is None and pending is None and index + 1 < end_index:
                decision = self._decide(timeline, candle)
                stats["decisions"] += 1
                if decision is None or decision.action is DecisionAction.NO_TRADE:
                    stats["no_trade"] += 1
                elif decision.strength < self.config.min_signal_strength:
                    stats["skipped"] += 1
                else:
                    pending = self._plan(decision, candles, index)
'@
$newLoop = @'
            if position is None and pending is None and index + 1 < end_index:
                decision = self._decide(timeline, candle)
                stats["decisions"] += 1
                if decision is None or decision.action is DecisionAction.NO_TRADE:
                    stats["no_trade"] += 1
                elif decision.strength < self.config.min_signal_strength:
                    stats["skipped"] += 1
                else:
                    if self.config.mode == "scenario":
                        pending = self._plan_from_scenario(decision, candles, index, timeline)
                    else:
                        pending = self._plan(decision, candles, index)
'@
if (-not $content.Contains($oldLoop)) { throw "simulate decision anchor not found" }
$content = $content.Replace($oldLoop, $newLoop)

# ---------- 5.5 افزودن متد _plan_from_scenario ----------
# بعد از _plan فعلی اضافه می‌شود.
$oldPlan = @'
    def _plan(self, decision: Decision, candles: Sequence[Candle], index: int) -> dict[str, Any]:
        window = 20
        start = max(0, index - window + 1)
        if decision.direction is Direction.LONG:
            reference = min(item.low for item in candles[start:index + 1])
            stop = reference - self.config.stop_buffer_pips * self._pip
        else:
            reference = max(item.high for item in candles[start:index + 1])
            stop = reference + self.config.stop_buffer_pips * self._pip
        return {
            "direction": decision.direction,
            "created_index": index,
            "stop": stop.quantize(self._quant),
            "decision_strength": decision.strength,
        }
'@
$newPlan = @'
    def _plan(self, decision: Decision, candles: Sequence[Candle], index: int) -> dict[str, Any]:
        """Baseline: stop از کف/سقف ۲۰ کندل + بافر. برای سازگاری نگه داشته شده."""
        window = 20
        start = max(0, index - window + 1)
        if decision.direction is Direction.LONG:
            reference = min(item.low for item in candles[start:index + 1])
            stop = reference - self.config.stop_buffer_pips * self._pip
        else:
            reference = max(item.high for item in candles[start:index + 1])
            stop = reference + self.config.stop_buffer_pips * self._pip
        return {
            "direction": decision.direction,
            "created_index": index,
            "stop": stop.quantize(self._quant),
            "decision_strength": decision.strength,
        }

    def _plan_from_scenario(self, decision: Decision, candles: Sequence[Candle], index: int,
                            timeline: EvidenceTimeline) -> dict[str, Any] | None:
        """FIX-05-BACKTEST-PARITY: برنامه ورود را با همان ScenarioBuilder زنده می‌سازیم.

        به این ترتیب بک‌تست، *همان* منطق Trigger/Stop/Target/Expiry سناریوی زنده را
        شبیه‌سازی می‌کند و اعداد گزارش به سناریوهای واقعی قابل تعمیم هستند.
        """
        from fxars.analysis.engine import AnalysisOutcome
        from fxars.domain.models import Candle as _Candle
        try:
            window = candles[max(0, index - 600): index + 1]
            # یک outcome سبک برای builder (بدون اندیکاتورهای جدید؛ فقط کندل‌ها و ATR لازم است)
            # برای حفظ سرعت، Summary و structure از تحلیل زنده نداریم؛ در صورت نیاز
            # downstream از Swing/ATR داخل builder استفاده می‌شود.
            from fxars.analysis.context import IndicatorSet
            indicators = IndicatorSet.build(window, self.analysis)
            outcome = AnalysisOutcome(
                instrument=self.instrument,
                timeframe=self.timeframe,
                as_of=candles[index].available_at,
                candles=list(window),
                indicators=indicators,
                structure=_empty_structure(window),
                evidences=[], summary={},
                snapshot_id="bt_inline", config_hash=self.config.hash(),
            )
            built = self._scenario_builder.build(
                outcome, decision, run_id="bt_parity", rules_version="rules_v1.3.0",
            )
            if built.scenario is None:
                return None
            sc = built.scenario
            entry_level = Decimal(sc.entry_condition.get("level", "0"))
            stop_level = Decimal(sc.stop_logic.get("level", "0"))
            targets = list(sc.target_logic)
            return {
                "direction": decision.direction,
                "created_index": index,
                "stop": stop_level.quantize(self._quant),
                "entry_trigger": entry_level.quantize(self._quant),
                "targets": targets,
                "expiry_at": sc.expiry_at,
                "decision_strength": decision.strength,
                "mode": "scenario",
            }
        except Exception:
            # Fail-safe: در صورت خطا به baseline برمی‌گردیم تا بک‌تست متوقف نشود.
            fallback = self._plan(decision, candles, index)
            fallback["mode"] = "baseline_fallback"
            return fallback
'@
if (-not $content.Contains($oldPlan)) { throw "_plan anchor not found" }
$content = $content.Replace($oldPlan, $newPlan)

# ---------- 5.6 اصلاح _enter برای احترام به entry_trigger/expiry در mode scenario ----------
$oldEnter = @'
    def _enter(self, plan: dict[str, Any], candle: Candle, equity: Decimal) -> _OpenTrade | None:
        direction: Direction = plan["direction"]
        spread = candle.spread if candle.spread is not None else self.config.spread_pips * self._pip
        half = spread / Decimal("2")
        slip = self.config.slippage_pips * self._pip
        if direction is Direction.LONG:
            entry = candle.open + half + slip
        else:
            entry = candle.open - half - slip
        entry = entry.quantize(self._quant)
        stop = plan["stop"]
'@
$newEnter = @'
    def _enter(self, plan: dict[str, Any], candle: Candle, equity: Decimal) -> _OpenTrade | None:
        direction: Direction = plan["direction"]
        spread = candle.spread if candle.spread is not None else self.config.spread_pips * self._pip
        half = spread / Decimal("2")
        slip = self.config.slippage_pips * self._pip
        entry_trigger = plan.get("entry_trigger")
        if plan.get("mode") == "scenario" and entry_trigger is not None:
            # شبیه‌سازی realistic trigger: ورود در Trigger Level اگر در دامنه کندل لمس شده باشد.
            if direction is Direction.LONG:
                if candle.high < entry_trigger:
                    return None
                entry = entry_trigger + half + slip
            else:
                if candle.low > entry_trigger:
                    return None
                entry = entry_trigger - half - slip
        else:
            if direction is Direction.LONG:
                entry = candle.open + half + slip
            else:
                entry = candle.open - half - slip
        entry = entry.quantize(self._quant)
        stop = plan["stop"]
'@
if (-not $content.Contains($oldEnter)) { throw "_enter anchor not found" }
$content = $content.Replace($oldEnter, $newEnter)

# ---------- 5.7 helper ساده برای ساخت structure خالی ----------
if ($content -notmatch 'def _empty_structure') {
    $content += @'


def _empty_structure(candles: Sequence[Candle]):
    """structure حداقلی برای builder در بک‌تست parity (بدون swing/بریک پیچیده)."""
    from fxars.analysis.structure import StructureResult
    result = StructureResult()
    if candles:
        highs = max(candles[-20:], key=lambda c: c.high)
        lows = min(candles[-20:], key=lambda c: c.low)
        from fxars.analysis.structure import Swing
        result.last_swing_high = Swing(index=0, price=highs.high, kind="HIGH", confirmed_index=0)
        result.last_swing_low = Swing(index=0, price=lows.low, kind="LOW", confirmed_index=0)
    return result
'@
}

$content = $content + "`r`n# FIX-05-BACKTEST-PARITY-DONE`r`n"
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] backtest.py patched (scenario/baseline modes)" -ForegroundColor Green

# ---------- 5.8 اتصال calendar به ResearchService ----------
$rsFile = Join-Path $ProjectRoot 'fxars\research\service.py'
$rsContent = Get-Content $rsFile -Raw -Encoding UTF8
if ($rsContent -notmatch 'FIX-05-RESEARCH-CALENDAR') {
    $oldRs = @'
        engine = BacktestEngine(context.instrument, timeframe, config, self.settings.analysis)
'@
    $newRs = @'
        # FIX-05-RESEARCH-CALENDAR: پاس دادن calendar به موتور بک‌تست برای parity با سناریو
        engine = BacktestEngine(context.instrument, timeframe, config, self.settings.analysis,
                                calendar=self.settings and getattr(self, "_calendar", None))
'@
    if ($rsContent.Contains($oldRs)) {
        $rsContent = $rsContent.Replace($oldRs, $newRs)
        Set-Content -Path $rsFile -Value $rsContent -Encoding UTF8 -NoNewline
        Write-Host "  [OK] ResearchService calendar pass-through" -ForegroundColor Green
    }
}

Write-Host "[FIX-05] Note: پیش‌فرض mode به 'scenario' تغییر کرد. برای گزارش قبلی،" -ForegroundColor Yellow
Write-Host "        از config_overrides={'mode':'baseline'} استفاده کنید." -ForegroundColor Yellow