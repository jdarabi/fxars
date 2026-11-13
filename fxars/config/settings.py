"""پیکربندی نسخه‌دار سامانه."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from decimal import Decimal
from pathlib import Path
from typing import Any

from fxars.config.decision import DecisionPolicy
from fxars.core.hashing import sha256_obj
from fxars.core.numerics import to_decimal
from fxars.domain.enums import EventImportance, Phase, Role
from fxars.version import CODE_VERSION, RISK_POLICY_VERSION, RULES_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]
@dataclass(frozen=True)
class AdvisorSettings:
    """FIX-DUAL: تنظیمات فاز مشاور."""
    min_score_threshold: float = 0.20
    max_signals_per_hour: int = 10
    send_no_trade: bool = False
    notify_telegram: bool = True
    notify_desktop: bool = True
    instruments: tuple = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "XAUUSD")
    timeframes: tuple = ("M15", "H1", "H4")


@dataclass(frozen=True)
class AutomatedLimitedSettings:
    """FIX-DUAL: تنظیمات فاز ربات با سقف سخت."""
    enabled: bool = False
    max_volume_per_order: Decimal = Decimal("0.01")
    max_open_positions: int = 1
    max_daily_trades: int = 3
    risk_per_trade: Decimal = Decimal("0.0025")
    daily_loss_limit: Decimal = Decimal("0.02")
    drawdown_stop: Decimal = Decimal("0.10")
    max_spread_pips: Decimal = Decimal("3.0")
    instruments: tuple = ("EURUSD",)
    timeframes: tuple = ("H1",)
    require_triggered_scenario: bool = True
    require_kill_switch_off: bool = True
    killed: bool = False


@dataclass(frozen=True)
class PhaseSettings:
    """FIX-DUAL: فاز فعلی و تنظیمات هر دو حالت."""
    mode: str = "ADVISOR"
    advisor: AdvisorSettings = field(default_factory=AdvisorSettings)
    automated_limited: AutomatedLimitedSettings = field(default_factory=AutomatedLimitedSettings)

    @classmethod
    def load(cls, path: Path | None = None) -> PhaseSettings:
        config_path = path or (PROJECT_ROOT / "config" / "phase.json")
        data: dict = {}
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8-sig"))
            except Exception:
                data = {}
        adv = data.get("advisor", {}) or {}
        aut = data.get("automated_limited", {}) or {}
        return cls(
            mode=str(data.get("mode", "ADVISOR")).upper(),
            advisor=AdvisorSettings(
                min_score_threshold=float(adv.get("min_score_threshold", 0.20)),
                max_signals_per_hour=int(adv.get("max_signals_per_hour", 10)),
                send_no_trade=bool(adv.get("send_no_trade", False)),
                notify_telegram=bool(adv.get("notify_telegram", True)),
                notify_desktop=bool(adv.get("notify_desktop", True)),
                instruments=tuple(adv.get("instruments", AdvisorSettings.instruments)),
                timeframes=tuple(adv.get("timeframes", AdvisorSettings.timeframes)),
            ),
            automated_limited=AutomatedLimitedSettings(
                enabled=bool(aut.get("enabled", False)),
                max_volume_per_order=Decimal(str(aut.get("max_volume_per_order", "0.01"))),
                max_open_positions=int(aut.get("max_open_positions", 1)),
                max_daily_trades=int(aut.get("max_daily_trades", 3)),
                risk_per_trade=Decimal(str(aut.get("risk_per_trade", "0.0025"))),
                daily_loss_limit=Decimal(str(aut.get("daily_loss_limit", "0.02"))),
                drawdown_stop=Decimal(str(aut.get("drawdown_stop", "0.10"))),
                max_spread_pips=Decimal(str(aut.get("max_spread_pips", "3.0"))),
                instruments=tuple(aut.get("instruments", AutomatedLimitedSettings.instruments)),
                timeframes=tuple(aut.get("timeframes", AutomatedLimitedSettings.timeframes)),
                require_triggered_scenario=bool(aut.get("require_triggered_scenario", True)),
                require_kill_switch_off=bool(aut.get("require_kill_switch_off", True)),
                killed=bool(aut.get("killed", False)),
            ),
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "advisor": {
                "min_score_threshold": self.advisor.min_score_threshold,
                "max_signals_per_hour": self.advisor.max_signals_per_hour,
                "send_no_trade": self.advisor.send_no_trade,
                "notify_telegram": self.advisor.notify_telegram,
                "notify_desktop": self.advisor.notify_desktop,
                "instruments": list(self.advisor.instruments),
                "timeframes": list(self.advisor.timeframes),
            },
            "automated_limited": {
                "enabled": self.automated_limited.enabled,
                "max_volume_per_order": str(self.automated_limited.max_volume_per_order),
                "max_open_positions": self.automated_limited.max_open_positions,
                "max_daily_trades": self.automated_limited.max_daily_trades,
                "risk_per_trade": str(self.automated_limited.risk_per_trade),
                "daily_loss_limit": str(self.automated_limited.daily_loss_limit),
                "drawdown_stop": str(self.automated_limited.drawdown_stop),
                "max_spread_pips": str(self.automated_limited.max_spread_pips),
                "instruments": list(self.automated_limited.instruments),
                "timeframes": list(self.automated_limited.timeframes),
                "require_triggered_scenario": self.automated_limited.require_triggered_scenario,
                "require_kill_switch_off": self.automated_limited.require_kill_switch_off,
                "killed": self.automated_limited.killed,
            },
        }

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"


def _dec(value: Any, default: str = "0") -> Decimal:
    return to_decimal(value if value is not None else default)


@dataclass(frozen=True)
class DatabaseSettings:
    backend: str = "sqlite"
    postgres_dsn: str = ""
    postgres_connect_timeout: int = 10
    postgres_statement_timeout_ms: int = 30000
    postgres_application_name: str = "fxars"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatabaseSettings:
        data = data or {}
        return cls(
            backend=str(data.get("backend", "sqlite")),
            postgres_dsn=str(data.get("postgres_dsn", "")),
            postgres_connect_timeout=int(data.get("postgres_connect_timeout", 10)),
            postgres_statement_timeout_ms=int(data.get("postgres_statement_timeout_ms", 30000)),
            postgres_application_name=str(data.get("postgres_application_name", "fxars")),
        )


@dataclass(frozen=True)
class RiskPolicy:
    version: str = RISK_POLICY_VERSION
    risk_per_trade: Decimal = Decimal("0.0025")
    hard_cap_risk_per_trade: Decimal = Decimal("0.005")
    daily_loss_limit: Decimal = Decimal("0.02")
    drawdown_warn: Decimal = Decimal("0.05")
    drawdown_stop: Decimal = Decimal("0.10")
    max_open_positions: int = 3
    max_positions_per_symbol: int = 1
    max_currency_exposure: Decimal = Decimal("0.02")
    max_correlation_exposure: Decimal = Decimal("0.025")
    max_spread_pips: Decimal = Decimal("3.0")
    min_stop_pips: Decimal = Decimal("3.0")
    max_stop_pips: Decimal = Decimal("150.0")
    margin_buffer: Decimal = Decimal("0.20")
    max_account_age_seconds: int = 300
    data_grace_seconds: int = 300
    max_bar_age_bars: float = 1.5
    max_entry_deviation_pips: Decimal = Decimal("25")
    decision_ttl_seconds: int = 300
    min_signal_strength: float = 0.35
    blackout_before_minutes: int = 30
    blackout_after_minutes: int = 30
    blackout_min_importance: EventImportance = EventImportance.HIGH
    correlation_window: int = 100
    correlation_threshold: float = 0.6
    max_daily_trades: int = 6
    max_daily_loss_hard_cap: Decimal = Decimal("0.05")
    max_drawdown_hard_cap: Decimal = Decimal("0.20")
    require_mfa_for_admin: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskPolicy:
        data = data or {}
        return cls(
            version=str(data.get("version", cls.version)),
            risk_per_trade=_dec(data.get("risk_per_trade"), "0.0025"),
            hard_cap_risk_per_trade=_dec(data.get("hard_cap_risk_per_trade"), "0.005"),
            daily_loss_limit=_dec(data.get("daily_loss_limit"), "0.02"),
            drawdown_warn=_dec(data.get("drawdown_warn"), "0.05"),
            drawdown_stop=_dec(data.get("drawdown_stop"), "0.10"),
            max_open_positions=int(data.get("max_open_positions", 3)),
            max_positions_per_symbol=int(data.get("max_positions_per_symbol", 1)),
            max_currency_exposure=_dec(data.get("max_currency_exposure"), "0.02"),
            max_correlation_exposure=_dec(data.get("max_correlation_exposure"), "0.025"),
            max_spread_pips=_dec(data.get("max_spread_pips"), "3.0"),
            min_stop_pips=_dec(data.get("min_stop_pips"), "3.0"),
            max_stop_pips=_dec(data.get("max_stop_pips"), "150.0"),
            margin_buffer=_dec(data.get("margin_buffer"), "0.20"),
            max_account_age_seconds=int(data.get("max_account_age_seconds", 300)),
            data_grace_seconds=int(data.get("data_grace_seconds", 300)),
            max_bar_age_bars=float(data.get("max_bar_age_bars", 1.5)),
            max_entry_deviation_pips=_dec(data.get("max_entry_deviation_pips"), "25"),
            decision_ttl_seconds=int(data.get("decision_ttl_seconds", 300)),
            min_signal_strength=float(data.get("min_signal_strength", 0.35)),
            blackout_before_minutes=int(data.get("blackout_before_minutes", 30)),
            blackout_after_minutes=int(data.get("blackout_after_minutes", 30)),
            blackout_min_importance=EventImportance(data.get("blackout_min_importance", "HIGH")),
            correlation_window=int(data.get("correlation_window", 100)),
            correlation_threshold=float(data.get("correlation_threshold", 0.6)),
            max_daily_trades=int(data.get("max_daily_trades", 6)),
            max_daily_loss_hard_cap=_dec(data.get("max_daily_loss_hard_cap"), "0.05"),
            max_drawdown_hard_cap=_dec(data.get("max_drawdown_hard_cap"), "0.20"),
            require_mfa_for_admin=bool(data.get("require_mfa_for_admin", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class AnalysisSettings:
    swing_k: int = 3
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    rsi_bull: float = 55.0
    rsi_bear: float = 45.0
    roc_period: int = 10
    atr_period: int = 14
    vol_window: int = 20
    atr_percentile_window: int = 100
    min_bars: int = 220
    level_lookback: int = 240
    level_proximity_pips: Decimal = Decimal("6")
    level_merge_pips: Decimal = Decimal("8")
    fvg_min_atr: Decimal = Decimal("0.20")
    displacement_atr: Decimal = Decimal("1.10")
    sweep_lookback: int = 24
    evidence_horizon_bars: int = 8
    max_evidence_age_bars: int = 6
    min_strength: float = 0.25
    family_cap: float = 0.35
    min_net_score: float = 0.10
    conflict_threshold: float = 0.25
    max_conflict_families: int = 1
    min_coverage: float = 0.25
    stability_window: int = 3
    stability_min_agreement: float = 0.66
    fundamental_lookback_hours: int = 24
    fundamental_surprise_floor: float = 0.0
    intermarket_min_correlation: float = 0.35
    intermarket_window: int = 60
    stop_buffer_pips: Decimal = Decimal("5")
    rr_targets: tuple = (Decimal("1.5"), Decimal("3.0"))
    scenario_expiry_bars: int = 8
    weights: dict = field(default_factory=dict)
    intermarket_refs: dict = field(
        default_factory=lambda: {"EURUSD": ["DXY"], "GBPUSD": ["DXY"], "XAUUSD": ["DXY"]}
    )

    @classmethod
    def from_dict(cls, data: dict) -> AnalysisSettings:
        data = data or {}
        base = cls()
        values = {}
        for item in fields(cls):
            if item.name not in data:
                continue
            value = data[item.name]
            current = getattr(base, item.name)
            if item.name == "rr_targets":
                value = tuple(_dec(entry) for entry in value)
            elif isinstance(current, Decimal):
                value = _dec(value)
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            values[item.name] = value
        return cls(**values)

    def to_dict(self) -> dict:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class DataQualitySettings:
    max_bar_age_bars: float = 1.5
    freshness_grace_seconds: int = 300
    source_divergence_pips: Decimal = Decimal("2.0")
    max_spread_pips: Decimal = Decimal("20")
    max_price_jump_pips: Decimal = Decimal("250")
    max_reported_gaps: int = 40
    gap_tolerance_bars: int = 1
    quarantine_invalid: bool = True
    require_available_at: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> DataQualitySettings:
        data = data or {}
        return cls(
            max_bar_age_bars=float(data.get("max_bar_age_bars", 1.5)),
            freshness_grace_seconds=int(data.get("freshness_grace_seconds", 300)),
            source_divergence_pips=_dec(data.get("source_divergence_pips"), "2.0"),
            max_spread_pips=_dec(data.get("max_spread_pips"), "20"),
            max_price_jump_pips=_dec(data.get("max_price_jump_pips"), "250"),
            max_reported_gaps=int(data.get("max_reported_gaps", 40)),
            gap_tolerance_bars=int(data.get("gap_tolerance_bars", 1)),
            quarantine_invalid=bool(data.get("quarantine_invalid", True)),
            require_available_at=bool(data.get("require_available_at", True)),
        )

    def to_dict(self) -> dict:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class ApiSettings:
    host: str = "127.0.0.1"
    port: int = 8080
    require_idempotency: bool = True
    rate_limit_per_minute: int = 120
    max_body_bytes: int = 1_000_000
    page_size_default: int = 100
    page_size_max: int = 500
    session_ttl_minutes: int = 480
    cors_allow_origin: str = ""
    rate_limit_backend: str = "memory"
    redis_url: str = "redis://127.0.0.1:6379/0"
    rate_limit_prefix: str = "fxars:rl:"
    auto_trade_enabled: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> ApiSettings:
        data = data or {}
        return cls(
            host=str(data.get("host", "127.0.0.1")),
            port=int(data.get("port", 8080)),
            require_idempotency=bool(data.get("require_idempotency", True)),
            rate_limit_per_minute=int(data.get("rate_limit_per_minute", 120)),
            max_body_bytes=int(data.get("max_body_bytes", 1_000_000)),
            page_size_default=int(data.get("page_size_default", 100)),
            page_size_max=int(data.get("page_size_max", 500)),
            session_ttl_minutes=int(data.get("session_ttl_minutes", 480)),
            cors_allow_origin=str(data.get("cors_allow_origin", "")),
            rate_limit_backend=str(data.get("rate_limit_backend", "memory")),
            redis_url=str(data.get("redis_url", "redis://127.0.0.1:6379/0")),
            rate_limit_prefix=str(data.get("rate_limit_prefix", "fxars:rl:")),
            auto_trade_enabled=bool(data.get("auto_trade_enabled", False)),
        )


@dataclass(frozen=True)
class SecuritySettings:
    pbkdf2_iterations: int = 210_000
    secret_key: str = "dev-insecure-secret-change-me"
    kms_provider: str = "local"
    login_max_attempts: int = 8
    login_window_seconds: int = 300
    mfa_roles: tuple = (Role.ADMIN, Role.RISK_MANAGER, Role.OPERATOR)
    session_token_bytes: int = 32

    @classmethod
    def from_dict(cls, data: dict) -> SecuritySettings:
        data = data or {}
        roles = data.get("mfa_roles", ["ADMIN", "RISK_MANAGER", "OPERATOR"])
        return cls(
            pbkdf2_iterations=int(data.get("pbkdf2_iterations", 210_000)),
            secret_key=str(data.get("secret_key", "dev-insecure-secret-change-me")),
            kms_provider=str(data.get("kms_provider", "local")),
            login_max_attempts=int(data.get("login_max_attempts", 8)),
            login_window_seconds=int(data.get("login_window_seconds", 300)),
            mfa_roles=tuple(Role(role) for role in roles),
            session_token_bytes=int(data.get("session_token_bytes", 32)),
        )


@dataclass(frozen=True)
class BacktestSettings:
    initial_equity: Decimal = Decimal("10000")
    risk_per_trade: Decimal = Decimal("0.0025")
    default_spread_pips: Decimal = Decimal("1.2")
    slippage_pips: Decimal = Decimal("0.3")
    commission_per_lot: Decimal = Decimal("7.0")
    swap_per_lot_per_night: Decimal = Decimal("-2.5")
    stop_buffer_pips: Decimal = Decimal("5")
    target_r_multiples: tuple = (Decimal("1.5"), Decimal("3.0"))
    partial_close_fraction: Decimal = Decimal("0.5")
    breakeven_after_tp1: bool = True
    max_bars_in_trade: int = 24
    expiry_bars: int = 8
    min_trades_for_report: int = 20
    seed: int = 7
    oos_train_fraction: float = 0.6
    oos_validation_fraction: float = 0.2
    embargo_bars: int = 5
    walkforward_train_bars: int = 600
    walkforward_test_bars: int = 200
    walkforward_step_bars: int = 200
    monte_carlo_runs: int = 200
    allowed_regimes: tuple = ()

    @classmethod
    def from_dict(cls, data: dict) -> BacktestSettings:
        data = data or {}
        targets = data.get("target_r_multiples", [1.5, 3.0])
        return cls(
            initial_equity=_dec(data.get("initial_equity"), "10000"),
            risk_per_trade=_dec(data.get("risk_per_trade"), "0.0025"),
            default_spread_pips=_dec(data.get("default_spread_pips"), "1.2"),
            slippage_pips=_dec(data.get("slippage_pips"), "0.3"),
            commission_per_lot=_dec(data.get("commission_per_lot"), "7.0"),
            swap_per_lot_per_night=_dec(data.get("swap_per_lot_per_night"), "-2.5"),
            stop_buffer_pips=_dec(data.get("stop_buffer_pips"), "5"),
            target_r_multiples=tuple(_dec(item) for item in targets),
            partial_close_fraction=_dec(data.get("partial_close_fraction"), "0.5"),
            breakeven_after_tp1=bool(data.get("breakeven_after_tp1", True)),
            max_bars_in_trade=int(data.get("max_bars_in_trade", 24)),
            expiry_bars=int(data.get("expiry_bars", 8)),
            min_trades_for_report=int(data.get("min_trades_for_report", 20)),
            seed=int(data.get("seed", 7)),
            oos_train_fraction=float(data.get("oos_train_fraction", 0.6)),
            oos_validation_fraction=float(data.get("oos_validation_fraction", 0.2)),
            embargo_bars=int(data.get("embargo_bars", 5)),
            walkforward_train_bars=int(data.get("walkforward_train_bars", 600)),
            walkforward_test_bars=int(data.get("walkforward_test_bars", 200)),
            walkforward_step_bars=int(data.get("walkforward_step_bars", 200)),
            monte_carlo_runs=int(data.get("monte_carlo_runs", 200)),
            allowed_regimes=tuple(data.get("allowed_regimes", []) or ()),
        )

    def to_dict(self) -> dict:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class Settings:
    environment: str = "dev"
    phase: Phase = Phase.READ_ONLY
    db_path: str = str(PROJECT_ROOT / "data" / "fxars.db")
    reports_dir: str = str(PROJECT_ROOT / "reports")
    data_dir: str = str(PROJECT_ROOT / "data")
    code_version: str = CODE_VERSION
    rules_version: str = RULES_VERSION
    seed: int = 7
    risk: RiskPolicy = field(default_factory=RiskPolicy)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    data_quality: DataQualitySettings = field(default_factory=DataQualitySettings)
    api: ApiSettings = field(default_factory=ApiSettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    backtest: BacktestSettings = field(default_factory=BacktestSettings)
    decision: DecisionPolicy = field(default_factory=DecisionPolicy)
    display_timezone: str = "Asia/Tehran"
    database: DatabaseSettings = field(default_factory=DatabaseSettings)

    @property
    def execution_enabled(self) -> bool:
        return self.phase.allows_order_intents

    def config_hash(self) -> str:
        return sha256_obj(
            {
                "code_version": self.code_version,
                "rules_version": self.rules_version,
                "seed": self.seed,
                "risk": self.risk.to_dict(),
                "analysis": self.analysis.to_dict(),
                "data_quality": self.data_quality.to_dict(),
                "backtest": self.backtest.to_dict(),
                "decision": self.decision.to_dict(),
            }
        )

    def to_dict(self) -> dict:
        from fxars.core.serde import jsonable

        data = jsonable(self)
        data["security"].pop("secret_key", None)
        data["execution_enabled"] = self.execution_enabled
        data["config_hash"] = self.config_hash()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        data = data or {}
        settings = cls(
            environment=str(data.get("environment", "dev")),
            phase=Phase(data.get("phase", "READ_ONLY")),
            db_path=str(data.get("db_path") or (PROJECT_ROOT / "data" / "fxars.db")),
            reports_dir=str(data.get("reports_dir") or (PROJECT_ROOT / "reports")),
            data_dir=str(data.get("data_dir") or (PROJECT_ROOT / "data")),
            code_version=str(data.get("code_version", CODE_VERSION)),
            rules_version=str(data.get("rules_version", RULES_VERSION)),
            seed=int(data.get("seed", 7)),
            risk=RiskPolicy.from_dict(data.get("risk", {})),
            analysis=AnalysisSettings.from_dict(data.get("analysis", {})),
            data_quality=DataQualitySettings.from_dict(data.get("data_quality", {})),
            api=ApiSettings.from_dict(data.get("api", {})),
            security=SecuritySettings.from_dict(data.get("security", {})),
            backtest=BacktestSettings.from_dict(data.get("backtest", {})),
            decision=DecisionPolicy.from_dict(data.get("decision", {})),
            display_timezone=str(data.get("display_timezone", "Asia/Tehran")),
            database=DatabaseSettings.from_dict(data.get("database", {})),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """اعتبارسنجی Fail-Fast تنظیمات؛ پیکربندی متناقض نباید بالا بیاید."""
        problems = _invariant_problems(self)
        if problems:
            joined = "\n".join(f"- {item}" for item in problems)
            raise ValueError(f"تنظیمات نامعتبر:\n{joined}")

    @classmethod
    def load(cls, path=None):
        config_path = Path(path) if path else Path(os.environ.get("FXARS_CONFIG", DEFAULT_CONFIG_PATH))
        data = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8-sig") as handle:
                data = json.load(handle)
        if os.environ.get("FXARS_PHASE"):
            data["phase"] = os.environ["FXARS_PHASE"]
        if os.environ.get("FXARS_DB_PATH"):
            data["db_path"] = os.environ["FXARS_DB_PATH"]
        if os.environ.get("FXARS_SECRET_KEY"):
            data.setdefault("security", {})["secret_key"] = os.environ["FXARS_SECRET_KEY"]
        if os.environ.get("FXARS_KMS_PROVIDER"):
            data.setdefault("security", {})["kms_provider"] = os.environ["FXARS_KMS_PROVIDER"]
        if os.environ.get("FXARS_SEED"):
            data["seed"] = int(os.environ["FXARS_SEED"])
        if os.environ.get("FXARS_API_PORT"):
            data.setdefault("api", {})["port"] = int(os.environ["FXARS_API_PORT"])
        if os.environ.get("FXARS_API_HOST"):
            data.setdefault("api", {})["host"] = os.environ["FXARS_API_HOST"]
        if os.environ.get("FXARS_DB_BACKEND"):
            data.setdefault("database", {})["backend"] = os.environ["FXARS_DB_BACKEND"]
        if os.environ.get("FXARS_POSTGRES_DSN"):
            data.setdefault("database", {})["postgres_dsn"] = os.environ["FXARS_POSTGRES_DSN"]
        settings = cls.from_dict(data)
        if os.environ.get("FXARS_ENABLE_DEMO") == "1" and settings.environment != "dev":
            raise ValueError(
                "FXARS_ENABLE_DEMO=1 فقط در محیط dev مجاز است؛ "
                "مسیرهای دمو (از جمله نمایش TOTP) در محیط غیرتوسعه غیرفعال می‌مانند."
            )
        if settings.environment == "prod":
            insecure = {"dev-insecure-secret-change-me", "", "change-me", "secret"}
            key = settings.security.secret_key
            if key in insecure or len(key) < 32:
                raise ValueError(
                    "secret_key نامعتبر در محیط prod: باید حداقل ۳۲ کاراکتر تصادفی باشد."
                )
        return settings

def _invariant_problems(settings: Settings) -> list[str]:
    """قواعد سازگاری که پیکربندی متناقض را پیش از اجرا متوقف می‌کند."""
    from decimal import Decimal as D

    problems: list[str] = []

    def hold(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    risk = settings.risk
    hold(D("0") < risk.risk_per_trade <= risk.hard_cap_risk_per_trade,
         f"risk.risk_per_trade ({risk.risk_per_trade}) باید مثبت و ≤ hard_cap_risk_per_trade ({risk.hard_cap_risk_per_trade}) باشد.")
    hold(risk.hard_cap_risk_per_trade <= D("0.10"),
         f"risk.hard_cap_risk_per_trade ({risk.hard_cap_risk_per_trade}) نباید از ۱۰٪ بیشتر باشد.")
    hold(D("0") < risk.daily_loss_limit <= risk.max_daily_loss_hard_cap <= D("0.20"),
         f"risk.daily_loss_limit ({risk.daily_loss_limit}) باید مثبت و ≤ max_daily_loss_hard_cap ({risk.max_daily_loss_hard_cap} ≤ 0.20) باشد.")
    hold(D("0") < risk.drawdown_warn < risk.drawdown_stop <= risk.max_drawdown_hard_cap <= D("1"),
         f"ترتیب آستانه‌های افت سرمایه نامعتبر است: drawdown_warn ({risk.drawdown_warn}) < drawdown_stop ({risk.drawdown_stop}) ≤ max_drawdown_hard_cap ({risk.max_drawdown_hard_cap} ≤ 1).")
    hold(1 <= risk.max_open_positions <= 100,
         f"risk.max_open_positions ({risk.max_open_positions}) باید بین ۱ و ۱۰۰ باشد.")
    hold(1 <= risk.max_positions_per_symbol <= risk.max_open_positions,
         f"risk.max_positions_per_symbol ({risk.max_positions_per_symbol}) باید ≥۱ و ≤ max_open_positions باشد.")
    hold(1 <= risk.max_daily_trades <= 100,
         f"risk.max_daily_trades ({risk.max_daily_trades}) باید بین ۱ و ۱۰۰ باشد.")
    hold(D("0") < risk.max_currency_exposure <= D("1"),
         f"risk.max_currency_exposure ({risk.max_currency_exposure}) باید در بازه (0, 1] باشد.")
    hold(D("0") < risk.max_correlation_exposure <= D("1"),
         f"risk.max_correlation_exposure ({risk.max_correlation_exposure}) باید در بازه (0, 1] باشد.")
    hold(0.0 <= risk.min_signal_strength <= 1.0,
         f"risk.min_signal_strength ({risk.min_signal_strength}) باید در بازه [0, 1] باشد.")
    hold(D("0") < risk.min_stop_pips <= risk.max_stop_pips,
         f"risk.min_stop_pips ({risk.min_stop_pips}) باید مثبت و ≤ max_stop_pips ({risk.max_stop_pips}) باشد.")
    hold(D("0") <= risk.margin_buffer < D("1"),
         f"risk.margin_buffer ({risk.margin_buffer}) باید در بازه [0, 1) باشد.")
    hold(D("0") < risk.max_spread_pips,
         f"risk.max_spread_pips ({risk.max_spread_pips}) باید مثبت باشد.")
    hold(0.0 <= risk.correlation_threshold <= 1.0,
         f"risk.correlation_threshold ({risk.correlation_threshold}) باید در بازه [0, 1] باشد.")
    hold(risk.decision_ttl_seconds > 0,
         f"risk.decision_ttl_seconds ({risk.decision_ttl_seconds}) باید مثبت باشد.")

    analysis = settings.analysis
    hold(analysis.min_bars >= 50,
         f"analysis.min_bars ({analysis.min_bars}) نباید کمتر از ۵۰ باشد.")
    hold(1 <= analysis.scenario_expiry_bars <= 100,
         f"analysis.scenario_expiry_bars ({analysis.scenario_expiry_bars}) باید بین ۱ و ۱۰۰ باشد "
         "(مقدار بزرگ باعث باقی‌ماندن سناریوی منقضی می‌شود).")
    hold(1 <= analysis.max_evidence_age_bars <= 100,
         f"analysis.max_evidence_age_bars ({analysis.max_evidence_age_bars}) باید بین ۱ و ۱۰۰ باشد.")
    hold(0.0 <= analysis.min_strength <= 1.0,
         f"analysis.min_strength ({analysis.min_strength}) باید در بازه [0, 1] باشد.")
    hold(bool(analysis.rr_targets) and all(value > 0 for value in analysis.rr_targets),
         "analysis.rr_targets باید فهرستی از مضارب مثبت R باشد.")

    backtest = settings.backtest
    hold(backtest.initial_equity > 0,
         f"backtest.initial_equity ({backtest.initial_equity}) باید مثبت باشد.")
    hold(D("0") < backtest.risk_per_trade <= D("0.02"),
         f"backtest.risk_per_trade ({backtest.risk_per_trade}) باید در بازه (0, 0.02] باشد؛ "
         "ریسک بیشتر نتایج بک‌تست را غیرواقعی می‌کند.")
    hold(0.0 < backtest.oos_train_fraction < 1.0 and 0.0 < backtest.oos_validation_fraction < 1.0,
         "کسرهای OOS باید در بازه (0, 1) باشند.")
    hold(backtest.oos_train_fraction + backtest.oos_validation_fraction < 1.0,
         "مجموع oos_train_fraction و oos_validation_fraction باید کمتر از ۱ باشد.")

    api = settings.api
    hold(1 <= api.port <= 65535, f"api.port ({api.port}) باید بین ۱ و ۶۵۵۳۵ باشد.")
    hold(1 <= api.page_size_default <= api.page_size_max,
         f"api.page_size_default ({api.page_size_default}) باید ≥۱ و ≤ page_size_max ({api.page_size_max}) باشد.")

    security = settings.security
    hold(security.kms_provider in {"local", "env"},
         f"security.kms_provider ({security.kms_provider}) باید local یا env باشد.")
    hold(security.pbkdf2_iterations >= 100_000,
         f"security.pbkdf2_iterations ({security.pbkdf2_iterations}) نباید کمتر از ۱۰۰۰۰۰ باشد.")

    problems.extend(settings.decision.problems())

    return problems


# FIX-BOM-TOLERANT
