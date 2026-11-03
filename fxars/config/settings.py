"""پیکربندی نسخه‌دار سامانه.

همه پارامترهای مؤثر بر تصمیم (ریسک، تحلیل، کیفیت داده) بخشی از config_hash هستند
تا هر خروجی قابل ردیابی و بازتولید باشد (اصل Version Everything).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from decimal import Decimal
from pathlib import Path
from typing import Any

from fxars.core.hashing import sha256_obj
from fxars.core.numerics import to_decimal
from fxars.domain.enums import EventImportance, Phase, Role
from fxars.version import CODE_VERSION, RISK_POLICY_VERSION, RULES_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.json"


def _dec(value: Any, default: str = "0") -> Decimal:
    return to_decimal(value if value is not None else default)


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
    decision_ttl_seconds: int = 300
    min_signal_strength: float = 0.35
    blackout_before_minutes: int = 30
    blackout_after_minutes: int = 30
    blackout_min_importance: EventImportance = EventImportance.HIGH
    correlation_window: int = 100
    correlation_threshold: float = 0.6
    max_daily_trades: int = 6
    require_mfa_for_admin: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskPolicy":
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
            decision_ttl_seconds=int(data.get("decision_ttl_seconds", 300)),
            min_signal_strength=float(data.get("min_signal_strength", 0.35)),
            blackout_before_minutes=int(data.get("blackout_before_minutes", 30)),
            blackout_after_minutes=int(data.get("blackout_after_minutes", 30)),
            blackout_min_importance=EventImportance(data.get("blackout_min_importance", "HIGH")),
            correlation_window=int(data.get("correlation_window", 100)),
            correlation_threshold=float(data.get("correlation_threshold", 0.6)),
            max_daily_trades=int(data.get("max_daily_trades", 6)),
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
    rr_targets: tuple[Decimal, ...] = (Decimal("1.5"), Decimal("3.0"))
    scenario_expiry_bars: int = 8
    weights: dict[str, float] = field(default_factory=dict)
    intermarket_refs: dict[str, list[str]] = field(
        default_factory=lambda: {"EURUSD": ["DXY"], "GBPUSD": ["DXY"], "XAUUSD": ["DXY"]}
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisSettings":
        data = data or {}
        base = cls()
        values: dict[str, Any] = {}
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

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        return jsonable(self)


@dataclass(frozen=True)
class DataQualitySettings:
    max_bar_age_bars: float = 1.5
    freshness_grace_seconds: int = 300
    source_divergence_pips: Decimal = Decimal("2.0")
    max_reported_gaps: int = 40
    gap_tolerance_bars: int = 1
    quarantine_invalid: bool = True
    require_available_at: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataQualitySettings":
        data = data or {}
        return cls(
            max_bar_age_bars=float(data.get("max_bar_age_bars", 1.5)),
            freshness_grace_seconds=int(data.get("freshness_grace_seconds", 300)),
            source_divergence_pips=_dec(data.get("source_divergence_pips"), "2.0"),
            max_reported_gaps=int(data.get("max_reported_gaps", 40)),
            gap_tolerance_bars=int(data.get("gap_tolerance_bars", 1)),
            quarantine_invalid=bool(data.get("quarantine_invalid", True)),
            require_available_at=bool(data.get("require_available_at", True)),
        )

    def to_dict(self) -> dict[str, Any]:
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiSettings":
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
        )


@dataclass(frozen=True)
class SecuritySettings:
    pbkdf2_iterations: int = 210_000
    secret_key: str = "dev-insecure-secret-change-me"
    login_max_attempts: int = 8
    login_window_seconds: int = 300
    mfa_roles: tuple[Role, ...] = (Role.ADMIN, Role.RISK_MANAGER, Role.OPERATOR)
    session_token_bytes: int = 32

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecuritySettings":
        data = data or {}
        roles = data.get("mfa_roles", ["ADMIN", "RISK_MANAGER", "OPERATOR"])
        return cls(
            pbkdf2_iterations=int(data.get("pbkdf2_iterations", 210_000)),
            secret_key=str(data.get("secret_key", "dev-insecure-secret-change-me")),
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
    target_r_multiples: tuple[Decimal, ...] = (Decimal("1.5"), Decimal("3.0"))
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
    # P3-4-ext3: regime filter (empty = allow all)
    allowed_regimes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BacktestSettings":
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

    def to_dict(self) -> dict[str, Any]:
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
    display_timezone: str = "Asia/Tehran"

    @property
    def execution_enabled(self) -> bool:
        return self.phase.allows_order_intents

    def config_hash(self) -> str:
        """هش پارامترهای مؤثر بر تحلیل/ریسک (بدون مسیرها و پورت)."""
        return sha256_obj(
            {
                "code_version": self.code_version,
                "rules_version": self.rules_version,
                "seed": self.seed,
                "risk": self.risk.to_dict(),
                "analysis": self.analysis.to_dict(),
                "data_quality": self.data_quality.to_dict(),
                "backtest": self.backtest.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        from fxars.core.serde import jsonable

        data = jsonable(self)
        data["security"].pop("secret_key", None)
        data["execution_enabled"] = self.execution_enabled
        data["config_hash"] = self.config_hash()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        data = data or {}
        return cls(
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
            display_timezone=str(data.get("display_timezone", "Asia/Tehran")),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        """بارگذاری از فایل JSON (اختیاری) + بازنویسی متغیرهای محیطی.

        FIX-03-HARDEN-SECRET: در محیط prod، secret_key پیش‌فرض یا کوتاه
        باعث fail-fast در startup می‌شود.
        """
        config_path = Path(path) if path else Path(os.environ.get("FXARS_CONFIG", DEFAULT_CONFIG_PATH))
        data: dict[str, Any] = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as handle:
                data = json.load(handle)
        if os.environ.get("FXARS_PHASE"):
            data["phase"] = os.environ["FXARS_PHASE"]
        if os.environ.get("FXARS_DB_PATH"):
            data["db_path"] = os.environ["FXARS_DB_PATH"]
        if os.environ.get("FXARS_SECRET_KEY"):
            data.setdefault("security", {})["secret_key"] = os.environ["FXARS_SECRET_KEY"]
        if os.environ.get("FXARS_SEED"):
            data["seed"] = int(os.environ["FXARS_SEED"])
        if os.environ.get("FXARS_API_PORT"):
            data.setdefault("api", {})["port"] = int(os.environ["FXARS_API_PORT"])
        if os.environ.get("FXARS_API_HOST"):
            data.setdefault("api", {})["host"] = os.environ["FXARS_API_HOST"]
        settings = cls.from_dict(data)
        # FIX-03-HARDEN-SECRET: در prod، secret_key ضعیف/پیش‌فرض مجاز نیست
        if settings.environment == "prod":
            insecure = {"dev-insecure-secret-change-me", "", "change-me", "secret"}
            key = settings.security.secret_key
            if key in insecure or len(key) < 32:
                raise ValueError(
                    "secret_key نامعتبر در محیط prod: باید حداقل ۳۲ کاراکتر تصادفی "
                    "و متفاوت از مقدار پیش‌فرض باشد. "
                    "این مقدار را از FXARS_SECRET_KEY یا config/security.secret_key تنظیم کنید."
                )
        return settings