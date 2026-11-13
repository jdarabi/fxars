"""شمارشی‌های دامنه؛ مقادیر رشته‌ای برای سازگاری قرارداد JSON."""

from __future__ import annotations

from datetime import timedelta
from enum import Enum

from fxars.core.timeutil import TIMEFRAME_MINUTES, timeframe_delta


class Timeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"

    @property
    def minutes(self) -> int:
        return TIMEFRAME_MINUTES[self.value]

    @property
    def delta(self) -> timedelta:
        return timeframe_delta(self.value)

    @classmethod
    def parse(cls, value: str | Timeframe) -> Timeframe:
        if isinstance(value, Timeframe):
            return value
        try:
            return cls(str(value).upper())
        except ValueError:
            raise ValueError(f"timeframe نامعتبر: {value!r}") from None


class QualityStatus(str, Enum):
    VALID = "VALID"
    SUSPECT = "SUSPECT"
    INVALID = "INVALID"

    @property
    def rank(self) -> int:
        return {"VALID": 0, "SUSPECT": 1, "INVALID": 2}[self.value]

    @property
    def is_usable(self) -> bool:
        return self is not QualityStatus.INVALID


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"

    @property
    def sign(self) -> int:
        return {"LONG": 1, "SHORT": -1, "NEUTRAL": 0}[self.value]

    @property
    def opposite(self) -> Direction:
        return Direction.SHORT if self is Direction.LONG else Direction.LONG if self is Direction.SHORT else Direction.NEUTRAL


class EvidenceFamily(str, Enum):
    STRUCTURE = "STRUCTURE"
    TREND = "TREND"
    MOMENTUM = "MOMENTUM"
    VOLATILITY = "VOLATILITY"
    LEVELS = "LEVELS"
    VOLUME = "VOLUME"
    FUNDAMENTAL = "FUNDAMENTAL"
    INTERMARKET = "INTERMARKET"


class DecisionAction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class AnalysisStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NO_TRADE = "NO_TRADE"
    STALE = "STALE"
    FAILED = "FAILED"


class ScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    WATCH = "WATCH"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ScenarioStatus.INVALIDATED,
            ScenarioStatus.EXPIRED,
            ScenarioStatus.REJECTED,
        }

    @property
    def is_live(self) -> bool:
        return self in {
            ScenarioStatus.DRAFT,
            ScenarioStatus.WATCH,
            ScenarioStatus.ARMED,
            ScenarioStatus.TRIGGERED,
        }


class RiskReasonCode(str, Enum):
    APPROVED = "APPROVED"
    PHASE_NOT_ALLOWED = "PHASE_NOT_ALLOWED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    RISK_LOCK_ACTIVE = "RISK_LOCK_ACTIVE"
    SCENARIO_INVALID = "SCENARIO_INVALID"
    SCENARIO_EXPIRED = "SCENARIO_EXPIRED"
    SIGNAL_TOO_WEAK = "SIGNAL_TOO_WEAK"
    INSTRUMENT_SPEC_MISSING = "INSTRUMENT_SPEC_MISSING"
    INSTRUMENT_SPEC_INVALID = "INSTRUMENT_SPEC_INVALID"
    ACCOUNT_SNAPSHOT_STALE = "ACCOUNT_SNAPSHOT_STALE"
    STALE_DATA = "STALE_DATA"
    PRICE_INVALID = "PRICE_INVALID"
    STOP_DISTANCE_INVALID = "STOP_DISTANCE_INVALID"
    POSITION_SIZE_INVALID = "POSITION_SIZE_INVALID"
    RISK_PER_TRADE_EXCEEDED = "RISK_PER_TRADE_EXCEEDED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    MARKET_CLOSED = "MARKET_CLOSED"
    MAX_OPEN_TRADES = "MAX_OPEN_TRADES"
    MAX_DAILY_TRADES = "MAX_DAILY_TRADES"
    CONVERSION_RATE_MISSING = "CONVERSION_RATE_MISSING"
    SYMBOL_EXPOSURE_LIMIT = "SYMBOL_EXPOSURE_LIMIT"
    CURRENCY_EXPOSURE_LIMIT = "CURRENCY_EXPOSURE_LIMIT"
    CORRELATION_EXPOSURE_LIMIT = "CORRELATION_EXPOSURE_LIMIT"
    EVENT_BLACKOUT = "EVENT_BLACKOUT"
    SPREAD_LIMIT = "SPREAD_LIMIT"
    MARGIN_INSUFFICIENT = "MARGIN_INSUFFICIENT"
    POLICY_MISSING = "POLICY_MISSING"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"


class OrderStatus(str, Enum):
    INTENT_CREATED = "INTENT_CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RiskLockState(str, Enum):
    """وضعیت چرخه قفل ریسک (بخش ۳-۳ سند تکمیلی ۱.۱).

    NORMAL و WARNING اجازه ارسال می‌دهند؛ بقیه وضعیت‌ها ارسال سفارش را متوقف
    می‌کنند تا بازبینی/آزادسازی رسمی ثبت شود.
    """

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    LOCKED_DAILY = "LOCKED_DAILY"
    LOCKED_WEEKLY = "LOCKED_WEEKLY"
    KILL_SWITCH = "KILL_SWITCH"
    MANUAL_REVIEW = "MANUAL_REVIEW"

    @property
    def blocks_orders(self) -> bool:
        return self in {
            RiskLockState.LOCKED_DAILY,
            RiskLockState.LOCKED_WEEKLY,
            RiskLockState.KILL_SWITCH,
            RiskLockState.MANUAL_REVIEW,
        }


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def direction(self) -> Direction:
        return Direction.LONG if self is Side.BUY else Direction.SHORT


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class Phase(str, Enum):
    """FIX-DUAL: فازهای سامانه.

    ADVISOR: مشاور تریدر — هیچ سفارشی ارسال نمی‌شود.
    READ_ONLY: فقط خواندن (میراث MVP-1).
    PAPER: اجرای شبیه‌سازی.
    DEMO: اجرای دمو روی بروکر دمو.
    ASSISTED: اجرای دستی با تأیید اپراتور.
    AUTOMATED_LIMITED: ربات با سقف سخت.
    """
    READ_ONLY = "READ_ONLY"
    ADVISOR = "ADVISOR"
    PAPER = "PAPER"
    DEMO = "DEMO"
    ASSISTED = "ASSISTED"
    AUTOMATED_LIMITED = "AUTOMATED_LIMITED"

    @property
    def allows_order_intents(self) -> bool:
        # FIX-DUAL: ADVISOR هرگز OrderIntent نمی‌سازد
        return self in {Phase.PAPER, Phase.DEMO, Phase.ASSISTED, Phase.AUTOMATED_LIMITED}

    @property
    def allows_real_broker(self) -> bool:
        return self in {Phase.DEMO, Phase.ASSISTED, Phase.AUTOMATED_LIMITED}

    @property
    def is_advisor_mode(self) -> bool:
        return self in {Phase.READ_ONLY, Phase.ADVISOR}

    @property
    def is_automation_mode(self) -> bool:
        return self in {Phase.PAPER, Phase.DEMO, Phase.ASSISTED, Phase.AUTOMATED_LIMITED}

class SessionName(str, Enum):
    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"


class EventImportance(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @property
    def rank(self) -> int:
        return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}[self.value]


class Role(str, Enum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    RESEARCHER = "RESEARCHER"
    RISK_MANAGER = "RISK_MANAGER"
    OPERATOR = "OPERATOR"
    TENANT_USER = "TENANT_USER"
    AUDITOR = "AUDITOR"


class Permission(str, Enum):
    DATA_READ = "data.read"
    DATA_INGEST = "data.ingest"
    ANALYSIS_RUN = "analysis.run"
    SCENARIO_READ = "scenario.read"
    SCENARIO_TRANSITION = "scenario.transition"
    RISK_EVALUATE = "risk.evaluate"
    RISK_POLICY_WRITE = "risk.policy.write"
    BACKTEST_RUN = "backtest.run"
    REPORT_READ = "report.read"
    AUDIT_READ = "audit.read"
    EXECUTION_ORDER = "execution.order"
    EXECUTION_APPROVE = "execution.approve"
    USERS_ADMIN = "users.admin"
    TENANT_ADMIN = "tenant.admin"
    KILLSWITCH_TOGGLE = "killswitch.toggle"
    SETTINGS_WRITE = "settings.write"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    TIME_EXIT = "TIME_EXIT"
    END_OF_DATA = "END_OF_DATA"


class BacktestSegment(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    LOCKED_TEST = "LOCKED_TEST"
    ALL = "ALL"
