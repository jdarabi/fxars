"""HTTP API با کتابخانه استاندارد (بدون وابستگی خارجی)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from fxars.api.metrics import get_registry
from fxars.api.metrics_dashboard import render_metrics_dashboard
from fxars.api.openapi import docs_html, openapi_spec

# FIX-E402-LAZY: re-export for backward compatibility (tests import from here)
from fxars.api.rate_limit import (  # noqa: F401
    MemoryRateLimiter as RateLimiter,
)
from fxars.api.rate_limit import (
    build_rate_limiter,
)
from fxars.core.context import correlation_scope, current_correlation_id
from fxars.core.errors import (
    AuthenticationError,
    FxarsError,
    NotFoundError,
    RateLimitedError,
    ValidationError,
)
from fxars.core.hashing import sha256_obj
from fxars.core.logging_setup import get_logger
from fxars.core.serde import jsonable
from fxars.core.timeutil import format_ts, parse_ts
from fxars.domain.enums import BacktestSegment, Permission, ScenarioStatus
from fxars.identity.rbac import permissions_for, require_permission
from fxars.platform import Platform

logger = get_logger("api")


@dataclass
class ApiRequest:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes
    ip: str = ""

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("بدنه درخواست JSON معتبر نیست.") from exc
        if not isinstance(data, dict):
            raise ValidationError("بدنه درخواست باید یک شیء JSON باشد.")
        return data

    def one(self, key: str, default: str | None = None) -> str | None:
        values = self.query.get(key)
        return values[0] if values else default

    def integer(self, key: str, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
        raw = self.one(key)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except ValueError:
            raise ValidationError(f"پارامتر {key} باید عدد صحیح باشد.") from None
        return max(minimum, min(maximum, value))


@dataclass
class ApiResponse:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


class ApiApp:
    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.settings = platform.settings
        self.identity = platform.identity
        self.limiter = build_rate_limiter(self.settings)  # FIX-11-REDIS
        self.routes: list[tuple[str, re.Pattern[str], Callable[..., ApiResponse], Permission | None, bool]] = []
        self.metrics = get_registry()
        self._register()

    def _register(self) -> None:
        def add(method: str, pattern: str, handler: Callable[..., ApiResponse],
                permission: Permission | None = None, public: bool = False) -> None:
            self.routes.append((method, re.compile(pattern), handler, permission, public))

        add("GET", r"^/api/v1/health$", self._health, public=True)
        add("GET", r"^/api/v1/phase$", self._phase_get, Permission.DATA_READ)
        add("POST", r"^/api/v1/phase$", self._phase_set, Permission.SETTINGS_WRITE)
        add("GET", r"^/api/v1/debug/rate-status$", self._rate_status, public=True)
        add("GET", r"^/api/v1/health/live$", self._health_live, public=True)
        add("GET", r"^/api/v1/health/ready$", self._health_ready, public=True)
        add("GET", r"^/api/v1/metrics$", self._metrics_endpoint, public=True)
        add("GET", r"^/metrics-dashboard$", self._metrics_dashboard, public=True)
        add("POST", r"^/api/v1/auth/login$", self._login, public=True)
        add("POST", r"^/api/v1/auth/demo-login$", self._demo_login, public=True)
        add("GET", r"^/api/v1/auth/demo-totp$", self._demo_totp, public=True)
        add("POST", r"^/api/v1/auth/logout$", self._logout)
        add("GET", r"^/api/v1/auth/me$", self._me)
        add("GET", r"^/api/v1/tenant$", self._tenant_get, Permission.DATA_READ)
        add("GET", r"^/api/v1/tenant/export$", self._tenant_export, Permission.DATA_READ)
        add("GET", r"^/api/v1/tenant/retention$", self._tenant_retention, Permission.DATA_READ)
        add("GET", r"^/api/v1/tenants$", self._tenants, Permission.TENANT_ADMIN)
        add("GET", r"^/api/v1/tenants/(?P<tenant_id>[A-Za-z0-9_.\-]+)/export$", self._tenant_export,
            Permission.TENANT_ADMIN)
        add("GET", r"^/api/v1/tenants/(?P<tenant_id>[A-Za-z0-9_.\-]+)/retention$", self._tenant_retention,
            Permission.TENANT_ADMIN)
        add("POST", r"^/api/v1/tenants/(?P<tenant_id>[A-Za-z0-9_.\-]+)$", self._tenant_update,
            Permission.TENANT_ADMIN)
        add("GET", r"^/api/v1/meta$", self._meta, Permission.DATA_READ)
        add("GET", r"^/api/v1/instruments$", self._instruments, Permission.DATA_READ)
        add("GET", r"^/api/v1/market-data/candles$", self._candles, Permission.DATA_READ)
        add("GET", r"^/api/v1/data-quality/runs$", self._dq_runs, Permission.DATA_READ)
        add("GET", r"^/api/v1/analysis-runs$", self._analysis_list, Permission.SCENARIO_READ)
        add("POST", r"^/api/v1/analysis-runs$", self._analysis_create, Permission.ANALYSIS_RUN)
        add("GET", r"^/api/v1/analysis-runs/(?P<run_id>[A-Za-z0-9_\-]+)$", self._analysis_get, Permission.SCENARIO_READ)
        add("GET", r"^/api/v1/scenarios$", self._scenarios, Permission.SCENARIO_READ)
        add("GET", r"^/api/v1/scenarios/(?P<scenario_id>[A-Za-z0-9_\-]+)$", self._scenario_get, Permission.SCENARIO_READ)
        add("POST", r"^/api/v1/scenarios/(?P<scenario_id>[A-Za-z0-9_\-]+)/evaluate$", self._scenario_evaluate, Permission.SCENARIO_TRANSITION)
        add("POST", r"^/api/v1/scenarios/(?P<scenario_id>[A-Za-z0-9_\-]+)/transition$", self._scenario_transition, Permission.SCENARIO_TRANSITION)
        add("GET", r"^/api/v1/risk/decisions$", self._risk_list, Permission.SCENARIO_READ)
        add("GET", r"^/api/v1/risk/decisions/(?P<decision_id>[A-Za-z0-9_\-]+)$", self._risk_get, Permission.SCENARIO_READ)
        add("POST", r"^/api/v1/risk/evaluate$", self._risk_evaluate, Permission.RISK_EVALUATE)
        add("GET", r"^/api/v1/backtests$", self._backtests, Permission.REPORT_READ)
        add("POST", r"^/api/v1/backtests$", self._backtest_create, Permission.BACKTEST_RUN)
        add("GET", r"^/api/v1/backtests/(?P<run_id>[A-Za-z0-9_\-]+)$", self._backtest_get, Permission.REPORT_READ)
        add("GET", r"^/api/v1/backtests/(?P<run_id>[A-Za-z0-9_\-]+)/report$", self._backtest_report, Permission.REPORT_READ)
        add("GET", r"^/api/v1/audit-events$", self._audit, Permission.AUDIT_READ)
        add("GET", r"^/api/v1/killswitch$", self._killswitch_get, Permission.SCENARIO_READ)
        add("GET", r"^/api/v1/outbox/stats$", self._outbox_stats, Permission.AUDIT_READ)
        add("POST", r"^/api/v1/outbox/publish$", self._outbox_publish, Permission.KILLSWITCH_TOGGLE)
        add("POST", r"^/api/v1/killswitch$", self._killswitch_set, Permission.KILLSWITCH_TOGGLE)
        add("GET", r"^/api/v1/live/chart$", self._live_chart, Permission.DATA_READ)
        add("GET", r"^/api/v1/live/signals$", self._live_signals, Permission.SCENARIO_READ)
        # FIX-TELEGRAM-CONFIG
        add("GET", r"^/api/v1/settings/telegram$", self._telegram_get, Permission.SCENARIO_READ)
        add("POST", r"^/api/v1/settings/telegram$", self._telegram_set, Permission.KILLSWITCH_TOGGLE)
        add("POST", r"^/api/v1/settings/telegram/test$", self._telegram_test, Permission.KILLSWITCH_TOGGLE)
        add("POST", r"^/api/v1/settings/desktop/test$", self._desktop_test, Permission.KILLSWITCH_TOGGLE)

        # SUPPLEMENT-1.1: قابلیت‌های اطلاعاتی تصمیم و حاکمیت
        add("GET", r"^/api/v1/intelligence/journal$", self._journal_list, Permission.SCENARIO_READ)
        add("POST", r"^/api/v1/intelligence/journal$", self._journal_add, Permission.SCENARIO_TRANSITION)
        add("GET", r"^/api/v1/intelligence/heatmap$", self._heatmap, Permission.SCENARIO_READ)
        add("GET", r"^/api/v1/intelligence/premortem/(?P<run_id>[A-Za-z0-9_\-]+)$",
            self._premortem, Permission.SCENARIO_READ)
        add("GET", r"^/api/v1/intelligence/counterfactual/(?P<scenario_id>[A-Za-z0-9_\-]+)$",
            self._counterfactual, Permission.SCENARIO_READ)
        add("GET", r"^/api/v1/intelligence/challenges/(?P<scenario_id>[A-Za-z0-9_\-]+)$",
            self._challenges_list, Permission.SCENARIO_READ)
        add("POST", r"^/api/v1/intelligence/challenges/(?P<scenario_id>[A-Za-z0-9_\-]+)$",
            self._challenge_add, Permission.SCENARIO_TRANSITION)
        add("GET", r"^/api/v1/governance/provenance/(?P<run_id>[A-Za-z0-9_\-]+)$",
            self._provenance_run, Permission.AUDIT_READ)
        add("GET", r"^/api/v1/governance/policies$", self._policies, Permission.AUDIT_READ)
        add("POST", r"^/api/v1/governance/policies$", self._policy_write, Permission.RISK_POLICY_WRITE)
        add("GET", r"^/api/v1/governance/models$", self._models, Permission.AUDIT_READ)
        add("POST", r"^/api/v1/governance/models$", self._model_write, Permission.RISK_POLICY_WRITE)
        add("GET", r"^/api/v1/governance/acceptance/(?P<run_id>[A-Za-z0-9_\-]+)$",
            self._acceptance, Permission.REPORT_READ)
        add("GET", r"^/api/v1/risk/lock$", self._risk_lock_get, Permission.SCENARIO_READ)
        add("POST", r"^/api/v1/risk/lock$", self._risk_lock_set, Permission.RISK_EVALUATE)

        # FIX-21-TRADING-HISTORY: مسیرهای معاملات و دانلود
        from fxars.api.trading import register_trading_routes
        register_trading_routes(self)

    def handle(self, request: ApiRequest) -> ApiResponse:
        correlation = request.headers.get("x-correlation-id") or None
        with correlation_scope(correlation):
            try:
                return self._dispatch(request)
            except FxarsError as exc:
                exc.correlation_id = exc.correlation_id or current_correlation_id()
                return self._json(exc.http_status, exc.to_dict())
            except (ValueError, TypeError, KeyError) as exc:
                error = ValidationError(
                    f"ورودی نامعتبر است: {exc}",
                    correlation_id=current_correlation_id(),
                    details={"path": request.path, "type": type(exc).__name__},
                )
                return self._json(error.http_status, error.to_dict())
            except Exception:
                logger.exception("unhandled api error", extra={"data": {"path": request.path}})
                from fxars.core.errors import FxarsError as Base

                error = Base("خطای داخلی سامانه رخ داد.", correlation_id=current_correlation_id())
                return self._json(500, error.to_dict())

    def _dispatch(self, request: ApiRequest) -> ApiResponse:
        if request.path in ("/", "/dashboard", "/index.html"):
            from fxars.ui.dashboard import DASHBOARD_HTML

            return ApiResponse(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8",
                               {"Cache-Control": "no-store, max-age=0"})
        if request.path == "/openapi.json":
            return self._json(200, openapi_spec(f"http://{self.settings.api.host}:{self.settings.api.port}"))
        if request.path in ("/docs", "/docs/"):
            return ApiResponse(200, docs_html().encode("utf-8"), "text/html; charset=utf-8")

        matched_methods: set[str] = set()
        for method, pattern, handler, permission, public in self.routes:
            match = pattern.match(request.path)
            if not match:
                continue
            matched_methods.add(method)
            if method != request.method:
                continue
            # FIX-08: Rate limit قبل از auth با IP
            ip_key = f"ip:{request.ip or 'unknown'}"
            if not self.limiter.allow(ip_key):
                raise RateLimitedError()
            user = None
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
                # FIX-08: Rate limit بعد از auth با user_id
                user_key = f"user:{user.user_id}"
                if not self.limiter.allow(user_key):
                    raise RateLimitedError()
            if request.method == "POST" and not public:
                return self._with_idempotency(request, user, lambda h=handler, m=match, u=user: h(request, m.groupdict(), u))
            return handler(request, match.groupdict(), user)
        if matched_methods:
            allow = ", ".join(sorted(matched_methods | {"OPTIONS"}))
            return self._json(
                405,
                {"error": {
                    "code": "METHOD_NOT_ALLOWED",
                    "message": "متد مجاز نیست.",
                    "correlation_id": current_correlation_id(),
                    "details": {"method": request.method, "allowed": sorted(matched_methods)},
                }},
                headers={"Allow": allow},
            )
        raise NotFoundError("مسیر درخواستی یافت نشد.", details={"path": request.path})

    def _authenticate(self, request: ApiRequest):
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise AuthenticationError("هدر Authorization: Bearer توکن لازم است.")
        token = header[7:].strip()
        resolved = self.identity.resolve_session(token)
        if resolved is None:
            raise AuthenticationError("نشست نامعتبر یا منقضی است.")
        return resolved[0]

    # FIX-08: _rate_key حذف شد؛ کلیدها در _dispatch ساخته می‌شوند.

    def _token(self, request: ApiRequest) -> str:
        return request.headers.get("authorization", "")[7:].strip()

    def _with_idempotency(self, request: ApiRequest, user, action: Callable[[], ApiResponse]) -> ApiResponse:
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            if self.settings.api.require_idempotency:
                raise ValidationError("برای عملیات POST هدر Idempotency-Key الزامی است.")
            return action()
        request_hash = sha256_obj({"path": request.path, "body": request.body.decode("utf-8", "replace")})
        # FIX-09-IDEMPOTENCY-ATOMIC
        outcome, existing = self.platform.idempotency.begin(
            key, user.user_id, request.path, request_hash,
        )
        if outcome == "replay" and existing is not None:
            return self._json(existing["status"], existing["response"])
        if outcome == "conflict":
            from fxars.core.errors import IdempotencyConflictError
            raise IdempotencyConflictError(details={"key": key})
        if outcome == "in_progress":
            from fxars.core.errors import ConflictError
            raise ConflictError(
                "درخواست با همین Idempotency-Key در حال پردازش است؛ دوباره تلاش کنید.",
                details={"key": key},
            )

        try:
            response = action()
        except Exception:
            self.platform.idempotency.fail(key, user.user_id)
            raise

        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        self.platform.idempotency.complete(key, user.user_id, response.status, payload)
        return response

    def _json(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> ApiResponse:
        body = json.dumps(jsonable(payload), ensure_ascii=False).encode("utf-8")
        merged = {"X-Correlation-ID": current_correlation_id()}
        if headers:
            merged.update(headers)
        if self.settings.api.cors_allow_origin:
            merged["Access-Control-Allow-Origin"] = self.settings.api.cors_allow_origin
        return ApiResponse(status, body, "application/json; charset=utf-8", merged)

    def _page(self, request: ApiRequest) -> tuple[int, int]:
        limit = request.integer("limit", self.settings.api.page_size_default, maximum=self.settings.api.page_size_max)
        offset = request.integer("offset", 0, minimum=0, maximum=10_000_000)
        return limit, offset

    def _health_live(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.api.health import live
        return self._json(200, live(self.platform).to_dict())

    def _health_ready(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.api.health import ready
        report = ready(self.platform)
        return self._json(200 if report.status == "ok" else 503, report.to_dict())

    def _metrics_endpoint(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self.metrics.set_gauge("fxars_audit_valid", 1.0 if self.platform.audit.verify()["valid"] else 0.0)
        self.metrics.set_gauge("fxars_killswitch_active", 1.0 if self.platform.killswitch.is_active() else 0.0)
        self.metrics.set_gauge("fxars_outbox_pending", float(self.platform.outbox.pending_count))
        text = self.metrics.render_prometheus()
        return ApiResponse(200, text.encode("utf-8"), content_type="text/plain; version=0.0.4; charset=utf-8")

    def _metrics_dashboard(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self.metrics.set_gauge("fxars_audit_valid", 1.0 if self.platform.audit.verify()["valid"] else 0.0)
        self.metrics.set_gauge("fxars_killswitch_active", 1.0 if self.platform.killswitch.is_active() else 0.0)
        self.metrics.set_gauge("fxars_outbox_pending", float(self.platform.outbox.pending_count))
        snapshot = self.metrics.snapshot()
        prometheus = self.metrics.render_prometheus()
        html = render_metrics_dashboard(snapshot, prometheus_text=prometheus)
        return ApiResponse(
            200,
            html.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    def _live_chart(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """Live chart data: candles + indicators + active scenarios."""

        from fxars.analysis.context import IndicatorSet

        instrument_id = request.one("instrument")
        timeframe = (request.one("timeframe") or "H1").upper()
        limit = request.integer("limit", 100, minimum=10, maximum=500)

        if not instrument_id:
            raise ValidationError("parameter instrument is required")

        # Try to find instrument spec
        try:
            instrument = self.platform.instruments.find(instrument_id)
        except Exception:
            instrument = None
        if instrument is None:
            raise NotFoundError("instrument not found: " + instrument_id)

        # Primary source
        try:
            source_id = self.platform.instruments.primary_source(instrument_id, timeframe)
        except Exception:
            source_id = None

        # Fetch candles
        candles = self.platform.candles.range(
            instrument_id, timeframe, source_id=source_id, closed_only=True,
        )
        if not candles:
            raise NotFoundError("no candles for " + instrument_id + "/" + timeframe)

        # Take last N
        tail = candles[-limit:]

        # Build indicators (needs enough bars)
        indicators_out = {"ema20": [], "ema50": [], "ema200": [], "rsi14": []}
        if len(tail) >= 20:
            try:
                full_ind = IndicatorSet.build(list(candles), self.platform.settings.analysis)
                offset = len(candles) - len(tail)
                for k in ("ema_fast", "ema_slow", "ema_trend", "rsi"):
                    series = getattr(full_ind, k)
                    sliced = series[offset:]
                    key = {"ema_fast": "ema20", "ema_slow": "ema50", "ema_trend": "ema200", "rsi": "rsi14"}[k]
                    indicators_out[key] = [None if v is None else round(float(v), 6) for v in sliced]
            except Exception as exc:
                logger.warning("indicator build failed: %s", exc)

        # Active scenarios for this instrument/timeframe
        scenarios_out = []
        try:
            live = self.platform.scenarios.list(instrument_id=instrument_id, limit=20,
                                                tenant_id=user.tenant_id)
            for s in live:
                if s.timeframe != timeframe:
                    continue
                if s.status.value not in ("WATCH", "ARMED", "TRIGGERED"):
                    continue
                scenarios_out.append({
                    "scenario_id": s.scenario_id,
                    "direction": s.direction.value,
                    "status": s.status.value,
                    "entry": s.entry_condition.get("level") if s.entry_condition else None,
                    "stop": s.stop_logic.get("level") if s.stop_logic else None,
                    "targets": [t.get("price") for t in (s.target_logic or ())],
                    "expiry_at": s.expiry_at.isoformat(),
                })
        except Exception as exc:
            logger.warning("scenarios load failed: %s", exc)

        # Convert candles
        candle_items = []
        for c in tail:
            candle_items.append({
                "time": c.open_time.isoformat(),
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": c.tick_volume or 0,
            })

        return self._json(200, {
            "instrument": instrument_id,
            "timeframe": timeframe,
            "source": source_id,
            "count": len(candle_items),
            "candles": candle_items,
            "indicators": indicators_out,
            "scenarios": scenarios_out,
        })

    def _live_signals(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """Recent signals from scenarios (across instruments/timeframes)."""
        limit = request.integer("limit", 20, minimum=1, maximum=100)

        items = []
        try:
            scenarios = self.platform.scenarios.list(limit=limit * 2, tenant_id=user.tenant_id)
            for s in scenarios:
                if s.status.value not in ("WATCH", "ARMED", "TRIGGERED", "DRAFT"):
                    continue
                items.append({
                    "scenario_id": s.scenario_id,
                    "instrument": s.instrument_id,
                    "timeframe": s.timeframe,
                    "direction": s.direction.value,
                    "status": s.status.value,
                    "strength": float(s.strength) if hasattr(s, "strength") else 0.0,
                    "entry": s.entry_condition.get("level") if s.entry_condition else None,
                    "stop": s.stop_logic.get("level") if s.stop_logic else None,
                    "targets": [t.get("price") for t in (s.target_logic or ())],
                    "expiry_at": s.expiry_at.isoformat(),
                    "created_at": s.created_at.isoformat(),
                })
                if len(items) >= limit:
                    break
        except Exception as exc:
            logger.warning("signals load failed: %s", exc)

        return self._json(200, {"items": items, "count": len(items)})


    # ---------------------------------------------------------- FIX-DUAL-PHASE
    def _phase_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """خواندن فاز فعلی و تنظیمات هر دو حالت."""
        return self._json(200, {
            "settings": self.platform.phase_settings.to_dict(),
            "runtime_phase": self.settings.phase.value,
            "execution_enabled": self.settings.execution_enabled,
            "broker": getattr(self.platform.execution.broker, "name", None),
        })

    def _phase_set(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """تغییر فاز فعلی و اعمال فوری آن روی settings/services/broker. فقط ADMIN/RISK_MANAGER."""
        body = request.json()
        mode = str(body.get("mode", "")).upper()
        allowed = ["ADVISOR", "AUTOMATED_LIMITED", "READ_ONLY", "PAPER", "DEMO", "ASSISTED"]
        if mode not in allowed:
            raise ValidationError("mode نامعتبر است.", details={"allowed": allowed})
        automated_enabled: bool | None = None
        if mode == "AUTOMATED_LIMITED":
            confirm = str(body.get("robot_confirm", "")).strip()
            if confirm != "ENABLE ROBOT":
                raise ValidationError(
                    "برای فعال‌سازی ربات، فیلد robot_confirm باید دقیقاً ENABLE ROBOT باشد.",
                    details={"hint": "این یک تأیید امنیتی است"},
                )
            automated_enabled = True
        try:
            outcome = self.platform.apply_phase(mode, automated_enabled=automated_enabled)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        self.settings = self.platform.settings
        warning: str | None = None
        if (
            outcome["runtime_phase"] in ("DEMO", "ASSISTED", "AUTOMATED_LIMITED")
            and outcome["broker"] != "mt5"
        ):
            warning = (
                "فاز اعمال شد اما اتصال MT5 برقرار نیست؛ تا اتصال دمو، "
                "سفارش‌ها با REAL_BROKER_UNAVAILABLE مسدود می‌شوند."
            )
        self.platform.audit.append(
            "PHASE_CHANGED", "system", "phase", actor=user.username,
            payload={
                "from": outcome["previous_phase"],
                "to": outcome["runtime_phase"],
                "mode": outcome["requested_mode"],
                "broker": outcome["broker"],
            },
        )
        return self._json(200, {
            "mode": outcome["requested_mode"],
            "runtime_phase": outcome["runtime_phase"],
            "execution_enabled": outcome["execution_enabled"],
            "broker": outcome["broker"],
            "warning": warning,
            "note": "فاز در همین اجرا اعمال شد.",
        })

    def _health(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        db_ok = self.platform.db.query_one("SELECT 1 AS ok") is not None
        return self._json(200, {
            "status": "ok" if db_ok else "degraded",
            "phase": self.settings.phase.value,
            "time": format_ts(self.platform.clock()),
            "audit": self.platform.audit.verify()["valid"],
            "killswitch": self.platform.killswitch.is_active(),
        })

    def _rate_status(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """FIX-08-RATE-LIMIT: وضعیت Rate Limit (فقط dev + localhost)."""
        if self.settings.environment != "dev":
            raise NotFoundError("مسیر درخواستی یافت نشد.", details={"path": request.path})
        if request.ip not in ("127.0.0.1", "::1", ""):
            raise NotFoundError("مسیر درخواستی یافت نشد.", details={"path": request.path})
        return self._json(200, {
            "limit_per_minute": self.limiter.limit,
            "window_seconds": self.limiter.window,
            "buckets": self.limiter.snapshot(),
        })

    def _login(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        result = self.identity.login(
            str(body.get("username", "")), str(body.get("password", "")),
            totp_code=body.get("totp_code"), ip=request.ip,
        )
        return self._json(200, {
            "token": result.token,
            "expires_at": format_ts(result.session.expires_at),
            "user": result.user.to_dict(),
            "permissions": sorted(permission.value for permission in permissions_for(result.user.role)),
        })

    def _logout(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self.identity.logout(self._token(request), actor=user.username)
        return self._json(200, {"status": "logged_out"})

    def _demo_enabled(self, request: ApiRequest) -> bool:
        """FIX-03-HARDEN-DEMO: ورود دمو فقط با شرط سه‌گانه.

        1) environment == "dev"
        2) IP لوکال (127.0.0.1 یا ::1)
        3) متغیر محیطی FXARS_ENABLE_DEMO=1 صریحاً ست شده باشد

        شرط سوم از فعال‌شدن ناخواسته دمو در صورت Reverse Proxy جلوگیری می‌کند.
        """
        import os as _os
        if self.settings.environment != "dev":
            return False
        if request.ip not in ("127.0.0.1", "::1", ""):
            return False
        return _os.environ.get("FXARS_ENABLE_DEMO", "") == "1"

    def _require_demo(self, request: ApiRequest) -> None:
        if not self._demo_enabled(request):
            raise AuthenticationError(
                "ورود دمو فقط در محیط development و از localhost فعال است.",
                details={"environment": self.settings.environment},
            )

    def _demo_login(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self._require_demo(request)
        body = request.json()
        role = str(body.get("role", "ANALYST")).upper()
        if role not in ("ANALYST", "AUDITOR"):
            raise AuthenticationError("ورود سریع دمو فقط برای ANALYST/AUDITOR مجاز است؛ مدیر باید MFA بدهد.")
        username = "analyst" if role == "ANALYST" else "auditor"
        target = self.platform.users.get_by_username(username)
        if target is None or not target.active:
            from fxars.core.errors import NotFoundError

            raise NotFoundError(f"کاربر دمو {username} یافت نشد؛ ابتدا init را اجرا کنید.")
        result = self.identity.start_session(target, ip=request.ip)
        self.platform.audit.append(
            "USER_LOGIN", "user", target.user_id, actor=username,
            payload={"ip": request.ip, "demo": True, "role": target.role.value},
        )
        return self._json(200, {
            "token": result.token,
            "expires_at": format_ts(result.session.expires_at),
            "user": target.to_dict(),
            "permissions": sorted(permission.value for permission in permissions_for(target.role)),
        })

    def _demo_totp(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self._require_demo(request)
        from fxars.identity.totp import totp

        username = request.one("username", "admin") or "admin"
        target = self.platform.users.get_by_username(username)
        if target is None or target.totp_secret_enc is None:
            from fxars.core.errors import NotFoundError

            raise NotFoundError(f"کاربر {username} با MFA یافت نشد.")
        secret = self.identity.totp_secret(target)
        moment = time.time()
        code = totp(secret, at=moment)
        expires_in = 30 - int(moment) % 30
        self.platform.audit.append(
            "DEMO_TOTP_ISSUED", "user", target.user_id, actor=username,
            payload={"ip": request.ip, "expires_in": expires_in},
        )
        return self._json(200, {"username": username, "code": code, "expires_in": expires_in})

    def _me(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        return self._json(200, {
            "user": user.to_dict(),
            "permissions": sorted(permission.value for permission in permissions_for(user.role)),
        })

    # ------------------------------------------------------------------ مستاجر و اشتراک
    def _tenant_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        return self._json(200, self.platform.quota.snapshot(user.tenant_id))

    def _tenants(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        items = []
        for tenant in self.platform.tenants.list():
            snapshot = self.platform.quota.snapshot(tenant.tenant_id)
            items.append(snapshot)
        return self._json(200, {"items": items, "count": len(items)})

    def _tenant_export(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        tenant_id = params.get("tenant_id") or user.tenant_id
        self.platform.quota.tenant(tenant_id)
        limit = request.integer("limit", 1000, minimum=1, maximum=5000)
        return self._json(200, self.platform.data_rights.export(tenant_id, limit=limit))

    def _tenant_retention(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        tenant_id = params.get("tenant_id") or user.tenant_id
        self.platform.quota.tenant(tenant_id)
        return self._json(200, self.platform.data_rights.retention_report(tenant_id))

    def _tenant_update(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.audit.audit import AuditAction
        from fxars.tenancy.plans import PLANS

        tenant = self.platform.tenants.get(params["tenant_id"])
        if tenant is None:
            raise NotFoundError(f"مستاجر {params['tenant_id']} یافت نشد.")
        body = request.json()
        changes: dict[str, Any] = {}

        if "plan" in body:
            plan = str(body["plan"])
            if plan not in PLANS:
                raise ValidationError(
                    f"پلن {plan} شناخته نشده است.", details={"allowed": sorted(PLANS)}
                )
            changes["plan"] = plan
        if "active" in body:
            changes["active"] = bool(body["active"])
        if "quota_overrides" in body:
            raw = body["quota_overrides"]
            if not isinstance(raw, dict):
                raise ValidationError("quota_overrides باید شیء باشد.")
            from fxars.tenancy.plans import QUOTA_KEYS

            overrides: dict[str, int] = {}
            for key, value in raw.items():
                if key not in QUOTA_KEYS:
                    raise ValidationError(f"کلید سهمیه {key} شناخته نشده است.", details={"allowed": list(QUOTA_KEYS)})
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    raise ValidationError(f"مقدار سهمیه {key} باید عدد صحیح باشد.") from None
                if number < -1:
                    raise ValidationError(f"مقدار سهمیه {key} نمی‌تواند کمتر از -۱ باشد.")
                overrides[key] = number
            changes["quota_overrides"] = overrides
        if not changes:
            raise ValidationError("حداقل یکی از plan/active/quota_overrides لازم است.")

        updated = replace(tenant, **changes)
        self.platform.tenants.save(updated)
        self.platform.audit.append(
            AuditAction.CONFIG_CHANGED, "tenant", tenant.tenant_id, actor=user.username,
            payload={"changes": {key: jsonable(value) for key, value in changes.items()}},
        )
        return self._json(200, self.platform.quota.snapshot(tenant.tenant_id))

    def _meta(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.analysis.modules import module_specs
        from fxars.version import CODE_VERSION, CONTRACT_VERSION, DOCUMENT_ID, RULES_VERSION

        return self._json(200, {
            "document_id": DOCUMENT_ID,
            "code_version": CODE_VERSION,
            "contract_version": CONTRACT_VERSION,
            "rules_version": RULES_VERSION,
            "config_hash": self.settings.config_hash(),
            "phase": self.settings.phase.value,
            "execution_enabled": self.settings.execution_enabled,
            "killswitch": self.platform.killswitch.status(),
            "risk_policy": self.settings.risk.to_dict(),
            "analysis": self.settings.analysis.to_dict(),
            "modules": module_specs(),
        })

    def _instruments(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        items = [instrument.to_dict() for instrument in self.platform.instruments.list()]
        return self._json(200, {"items": items, "count": len(items)})

    def _candles(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        instrument_id = request.one("instrument_id")
        timeframe = request.one("timeframe", "H1")
        if not instrument_id:
            raise ValidationError("پارامتر instrument_id الزامی است.")
        try:
            from fxars.domain.enums import Timeframe as _TF
            _TF.parse(timeframe)
        except ValueError:
            raise ValidationError(f"timeframe نامعتبر است: {timeframe!r}") from None

        source_id = request.one("source_id")
        if not source_id:
            try:
                source_id = self.platform.instruments.primary_source(instrument_id, timeframe)
            except Exception:
                source_id = None

        start = None
        if request.one("start"):
            try:
                start = parse_ts(request.one("start"))
            except ValueError as exc:
                raise ValidationError(f"start نامعتبر است: {exc}") from None
        end = None
        if request.one("end"):
            try:
                end = parse_ts(request.one("end"))
            except ValueError as exc:
                raise ValidationError(f"end نامعتبر است: {exc}") from None

        limit, offset = self._page(request)
        limit = min(limit, 5000)

        candles = self.platform.candles.range(
            instrument_id, timeframe, source_id=source_id,
            start=start, end=end, closed_only=True,
        )
        total = len(candles)
        order = (request.one("order") or "desc").lower()
        if order == "asc":
            start_index = min(offset, total)
            end_index = min(offset + limit, total)
            selected = candles[start_index:end_index]
        else:
            end_index = max(0, total - offset)
            start_index = max(0, end_index - limit)
            selected = candles[start_index:end_index]
        return self._json(200, {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "source_id": source_id,
            "count": len(selected),
            "total": total,
            "order": order,
            "limit": limit,
            "offset": offset,
            "items": [candle.to_dict() for candle in selected],
        })

    def _dq_runs(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        limit, _ = self._page(request)
        runs = self.platform.quality_runs.list(instrument_id=request.one("instrument_id"), limit=limit)
        return self._json(200, {"items": [run.to_dict() for run in runs], "count": len(runs)})

    def _analysis_list(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        limit, offset = self._page(request)
        runs = self.platform.analyses.list_runs(
            instrument_id=request.one("instrument_id"), limit=limit, offset=offset,
            tenant_id=user.tenant_id,
        )
        return self._json(200, {"items": [run.to_dict() for run in runs], "count": len(runs)})

    def _analysis_create(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        instrument_id = body.get("instrument_id")
        timeframe = str(body.get("timeframe", "H1")).upper()
        if not instrument_id:
            raise ValidationError("instrument_id الزامی است.")
        from fxars.domain.enums import Timeframe as _TF
        try:
            _TF.parse(timeframe)
        except ValueError:
            raise ValidationError(
                f"timeframe نامعتبر است: {timeframe!r}",
                details={"allowed": [t.value for t in _TF]},
            ) from None
        as_of = None
        if body.get("as_of"):
            try:
                as_of = parse_ts(body["as_of"])
            except ValueError as exc:
                raise ValidationError(f"as_of نامعتبر است: {exc}") from None
        result = self.platform.run_analysis(instrument_id, timeframe, as_of=as_of,
                                            actor=user.username, tenant_id=user.tenant_id)
        return self._json(200, {
            "run": result.run.to_dict(),
            "decision": result.decision.to_dict(),
            "scenario": result.scenario.to_dict() if result.scenario else None,
            "scenario_reason": result.scenario_reason,
            "evidences": [evidence.to_dict() for evidence in result.evidences],
        })

    def _analysis_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        run = self.platform.analyses.get_run_for_tenant(params["run_id"], user.tenant_id)
        evidences = self.platform.analyses.evidence_for(run.run_id)
        scenario = self.platform.scenarios.find_by_run(run.run_id, tenant_id=user.tenant_id)
        return self._json(200, {
            "run": run.to_dict(),
            "evidences": [evidence.to_dict() for evidence in evidences],
            "scenario": scenario.to_dict() if scenario else None,
        })

    def _scenarios(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        limit, offset = self._page(request)
        status = request.one("status")
        scenarios = self.platform.scenarios.list(
            status=ScenarioStatus(status) if status else None,
            instrument_id=request.one("instrument_id"), limit=limit, offset=offset,
            tenant_id=user.tenant_id,
        )
        return self._json(200, {"items": [scenario.to_dict() for scenario in scenarios], "count": len(scenarios),
                                 "summary": self.platform.scenarios.count_by_status(tenant_id=user.tenant_id)})

    def _scenario_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        scenario = self.platform.scenarios.get_for_tenant(params["scenario_id"], user.tenant_id)
        transitions = self.platform.scenarios.transitions(scenario.scenario_id)
        decision = self.platform.decisions.latest_for_scenario(scenario.scenario_id)
        return self._json(200, {
            "scenario": scenario.to_dict(),
            "transitions": [transition.to_dict() for transition in transitions],
            "risk_decision": decision.to_dict() if decision else None,
        })

    def _scenario_evaluate(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self.platform.scenarios.get_for_tenant(params["scenario_id"], user.tenant_id)
        result = self.platform.evaluate_scenario(params["scenario_id"])
        return self._json(200, {
            "scenario": result.scenario.to_dict(),
            "transition": result.transition.to_dict() if result.transition else None,
            "reason": result.reason,
        })

    def _scenario_transition(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        status = body.get("status")
        reason = str(body.get("reason", "")).strip()
        if not status or not reason:
            raise ValidationError("status و reason الزامی هستند.")
        try:
            target = ScenarioStatus(str(status).upper())
        except ValueError:
            raise ValidationError("status نامعتبر است.") from None
        self.platform.scenarios.get_for_tenant(params["scenario_id"], user.tenant_id)
        result = self.platform.scenario_service.transition(
            params["scenario_id"], target, actor=user.username, reason=reason, now=self.platform.clock(),
        )
        return self._json(200, {
            "scenario": result.scenario.to_dict(),
            "transition": result.transition.to_dict() if result.transition else None,
        })

    def _risk_list(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        limit, offset = self._page(request)
        decisions = self.platform.decisions.list(limit=limit, offset=offset, tenant_id=user.tenant_id)
        return self._json(200, {"items": [decision.to_dict() for decision in decisions], "count": len(decisions)})

    def _risk_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        decision = self.platform.decisions.get_for_tenant(params["decision_id"], user.tenant_id)
        return self._json(200, {"decision": decision.to_dict()})

    def _risk_evaluate(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        scenario_id = body.get("scenario_id")
        if not scenario_id:
            raise ValidationError("scenario_id الزامی است.")
        decision = self.platform.evaluate_risk(
            str(scenario_id), body.get("account"), rates=body.get("rates"), actor=user.username,
            tenant_id=user.tenant_id,
        )
        return self._json(200, {"decision": decision.to_dict()})

    def _backtests(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        limit, _ = self._page(request)
        runs = self.platform.backtests.list(limit=limit)
        return self._json(200, {"items": [run.to_dict() for run in runs], "count": len(runs)})

    def _backtest_create(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        instrument_id = body.get("instrument_id")
        timeframe = body.get("timeframe", "H1")
        if not instrument_id:
            raise ValidationError("instrument_id الزامی است.")
        try:
            segment = BacktestSegment(str(body.get("segment", "ALL")).upper())
        except ValueError:
            raise ValidationError(
                f"segment نامعتبر است: {body.get('segment')!r}",
                details={"allowed": [s.value for s in BacktestSegment]},
            ) from None
        as_of = parse_ts(body["as_of"]) if body.get("as_of") else None
        overrides = dict(body.get("overrides") or {})
        strategy = body.get("strategy")
        if strategy is not None:
            overrides["strategy"] = strategy
        result = self.platform.research.run(
            instrument_id, timeframe, config_overrides=overrides,
            segment=segment, as_of=as_of, actor=user.username,
        )
        return self._json(200, {
            "run": result.run.to_dict(),
            "stats": result.output.stats,
        })

    def _backtest_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        run = self.platform.backtests.get(params["run_id"])
        return self._json(200, {"run": run.to_dict()})

    def _backtest_report(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.research.report import render_html, render_markdown

        run = self.platform.backtests.get(params["run_id"])
        fmt = (request.one("format") or "html").lower()
        if fmt == "md":
            return ApiResponse(200, render_markdown(run).encode("utf-8"), "text/markdown; charset=utf-8")
        return ApiResponse(200, render_html(run).encode("utf-8"), "text/html; charset=utf-8")

    def _audit(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        limit, offset = self._page(request)
        entries = self.platform.audit.list_entries(limit=limit, offset=offset, action=request.one("action"))
        return self._json(200, {
            "items": [entry.to_dict() for entry in entries],
            "count": len(entries),
            "verification": self.platform.audit.verify(),
        })

    def _outbox_stats(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """FIX-08-OUTBOX-API: آمار Outbox و مصرف."""
        repo = self.platform.outbox_repo
        pending = repo.pending(limit=10000)
        dead = repo.dead_letters(limit=10000)
        total_row = self.platform.db.scalar("SELECT COUNT(*) FROM outbox") or 0
        published_row = self.platform.db.scalar(
            "SELECT COUNT(*) FROM outbox WHERE published_at IS NOT NULL") or 0
        return self._json(200, {
            "pending_count": len(pending),
            "dead_letter_count": len(dead),
            "total": int(total_row),
            "published_count": int(published_row),
            "consumer": self.platform.outbox_stats.snapshot(),
        })

    def _outbox_publish(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """FIX-08-OUTBOX-API: پردازش pending events توسط consumerها."""
        body = request.json()
        limit = int(body.get("limit", 100))
        limit = max(1, min(1000, limit))
        stats = self.platform.outbox.publish_pending(
            self.platform.outbox_handlers, limit=limit,
        )
        return self._json(200, {
            "stats": stats,
            "consumer": self.platform.outbox_stats.snapshot(),
        })

    def _killswitch_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        scope = (request.one("scope") or "SYSTEM").upper()
        target = request.one("target") or ""
        return self._json(200, {
            "killswitch": self.platform.killswitch.status(scope, target),
            "scopes": self.platform.kill_switch_scopes(),
        })

    def _killswitch_set(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        reason = str(body.get("reason", "")).strip()
        if "active" not in body:
            raise ValidationError("فیلد active الزامی است.")
        status = self.platform.set_kill_switch(
            bool(body["active"]), actor=user.username, reason=reason,
            scope=str(body.get("scope", "SYSTEM")).upper(), target=str(body.get("target", "")),
        )
        return self._json(200, {"killswitch": status})

    # ---------------------------------------------------------- SUPPLEMENT-1.1
    def _journal_list(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        items = self.platform.intelligence.journal_list(
            tenant_id=user.tenant_id,
            analysis_run_id=request.one("analysis_run_id") or request.one("run_id"),
            scenario_id=request.one("scenario_id"),
            limit=request.integer("limit", 100, maximum=500),
        )
        return self._json(200, {"items": items, "count": len(items)})

    def _journal_add(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        entry = self.platform.intelligence.journal_add(
            kind=str(body.get("kind", "NOTE")), body=str(body.get("body", "")),
            actor=user.username, tenant_id=user.tenant_id,
            analysis_run_id=body.get("analysis_run_id"), scenario_id=body.get("scenario_id"),
            decision_id=body.get("decision_id"),
            payload=body.get("payload") if isinstance(body.get("payload"), dict) else None,
        )
        return self._json(201, {"entry": entry})

    def _heatmap(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        return self._json(200, self.platform.intelligence.heatmap(tenant_id=user.tenant_id))

    def _premortem(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        run = self.platform.analyses.get_run_for_tenant(params["run_id"], user.tenant_id)
        return self._json(200, self.platform.intelligence.premortem(run.run_id))

    def _counterfactual(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self.platform.scenarios.get_for_tenant(params["scenario_id"], user.tenant_id)
        max_bars = request.integer("max_bars", self.settings.backtest.max_bars_in_trade, maximum=500)
        return self._json(200, self.platform.intelligence.counterfactual(
            params["scenario_id"], max_bars=max_bars,
        ))

    def _challenges_list(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        self.platform.scenarios.get_for_tenant(params["scenario_id"], user.tenant_id)
        items = self.platform.intelligence.challenge_list(
            params["scenario_id"], limit=request.integer("limit", 100, maximum=500),
        )
        return self._json(200, {"items": items, "count": len(items)})

    def _challenge_add(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        challenge = self.platform.intelligence.challenge_add(
            params["scenario_id"], thesis=str(body.get("thesis", "")), actor=user.username,
            evidence=body.get("evidence") if isinstance(body.get("evidence"), list) else None,
            severity=str(body.get("severity", "MEDIUM")), tenant_id=user.tenant_id,
        )
        return self._json(201, {"challenge": challenge})

    def _provenance_run(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        run = self.platform.analyses.get_run_for_tenant(params["run_id"], user.tenant_id)
        records = self.platform.provenance_store.for_run(run.run_id, tenant_id=user.tenant_id)
        chain = self.platform.provenance_store.verify_chain(tenant_id=user.tenant_id)
        return self._json(200, {
            "run_id": run.run_id,
            "records": [record.to_dict() for record in records],
            "count": len(records),
            "chain": chain,
        })

    def _policies(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        kind = request.one("kind")
        items = self.platform.policy_registry.list(kind=kind.lower() if kind else None,
                                                  limit=request.integer("limit", 100, maximum=500))
        return self._json(200, {"items": [item.to_dict() for item in items], "count": len(items)})

    def _policy_write(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        action = str(body.get("action", "register")).strip().lower()
        if action == "activate":
            record = self.platform.policy_registry.activate(
                str(body.get("version", "")), kind=str(body.get("kind", "")).lower(),
                actor=user.username, approved_by=str(body.get("approved_by", "")),
                reason=str(body.get("reason", "")),
            )
        else:
            record = self.platform.policy_registry.register(
                str(body.get("kind", "")), body.get("values") or {},
                actor=user.username, version=body.get("version"),
                approved_by=str(body.get("approved_by", "")), notes=str(body.get("notes", "")),
                activate=bool(body.get("activate", False)),
            )
        return self._json(201, {"policy": record.to_dict()})

    def _models(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        items = self.platform.model_registry.list()
        return self._json(200, {"items": [card.to_dict() for card in items], "count": len(items)})

    def _model_write(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.governance.models import ModelCard

        body = request.json()
        action = str(body.get("action", "register")).strip().lower()
        if action == "promote":
            card = self.platform.model_registry.promote(
                str(body.get("model_id", "")), str(body.get("version", "")),
                str(body.get("target", "")), actor=user.username,
                approved_by=str(body.get("approved_by", "")), reason=str(body.get("reason", "")),
                shadow_completed=body.get("shadow_completed"),
                oos_passed=body.get("oos_passed"),
                independent_approval=body.get("independent_approval"),
                kill_switch_ready=body.get("kill_switch_ready"),
            )
        else:
            card = self.platform.model_registry.register(
                ModelCard(
                    model_id=str(body.get("model_id", "")),
                    version=str(body.get("version", "")),
                    tier=int(body.get("tier", 0)),
                    purpose=str(body.get("purpose", "")),
                    owner=str(body.get("owner", "")),
                    training_data=str(body.get("training_data", "")),
                    feature_schema=str(body.get("feature_schema", "")),
                    limitations=tuple(body.get("limitations", ()) or ()),
                    metrics=body.get("metrics") or {},
                    calibration=body.get("calibration") or {},
                    provides_probability=bool(body.get("provides_probability", False)),
                    dataset_snapshot=str(body.get("dataset_snapshot", "")),
                    code_hash=str(body.get("code_hash", "")),
                    config_hash=str(body.get("config_hash", "")),
                    valid_from=parse_ts(body["valid_from"]) if body.get("valid_from") else None,
                    valid_until=parse_ts(body["valid_until"]) if body.get("valid_until") else None,
                ),
                actor=user.username,
            )
        return self._json(201, {"model": card.to_dict()})

    def _acceptance(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.research.acceptance import evaluate_run

        run = self.platform.backtests.get(params["run_id"])
        report = evaluate_run(run, policy=self.settings.decision.acceptance)
        return self._json(200, report.to_dict())

    def _risk_lock_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        return self._json(200, {"risk_lock": self.platform.risk_lock_status()})

    def _risk_lock_set(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        result = self.platform.set_risk_lock_review(
            actor=user.username, reason=str(body.get("reason", "")),
            release=bool(body.get("release", False)),
        )
        return self._json(200, {"risk_lock": result})


    # ---------------------------------------------------------- FIX-TELEGRAM-CONFIG
    def _telegram_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.live.telegram_config import TelegramSettings
        settings = TelegramSettings.load()
        return self._json(200, {"settings": settings.masked()})

    def _telegram_set(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.live.telegram_config import TelegramSettings
        body = request.json()
        token = str(body.get("token", "")).strip()
        chat_id = str(body.get("chat_id", "")).strip()
        enabled = bool(body.get("enabled", False))
        if enabled and not chat_id:
            raise ValidationError("برای فعال‌سازی، chat_id الزامی است.")
        settings = TelegramSettings.load()
        if token:
            settings.token = token
        if chat_id:
            settings.chat_id = chat_id
        settings.enabled = enabled
        if enabled and (not settings.token or not settings.chat_id):
            raise ValidationError("برای فعال‌سازی، token و chat_id الزامی است.")
        settings.save()
        try:
            self.platform.audit.append(
                "TELEGRAM_CONFIG_CHANGED", "system", "telegram",
                actor=user.username,
                payload={"enabled": enabled, "chat_id": settings.chat_id},
            )
        except Exception:
            pass
        return self._json(200, {"settings": settings.masked()})

    def _telegram_test(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        from fxars.live.notifier import TelegramConfig, TelegramNotifier
        from fxars.live.telegram_config import TelegramSettings
        settings = TelegramSettings.load()
        if not settings.token or not settings.chat_id:
            raise ValidationError("telegram token/chat_id تنظیم نشده است.")
        try:
            cfg = TelegramConfig(token=settings.token, chat_id=settings.chat_id)
            notifier = TelegramNotifier(cfg)
            ok = notifier.send_message("✅ FX-ARS test message — settings works")
            return self._json(200 if ok else 502, {
                "ok": bool(ok), "chat_id": settings.chat_id,
            })
        except Exception as exc:
            logger.exception("telegram test failed")
            return self._json(502, {"ok": False, "error": str(exc)})


    def _desktop_test(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        try:
            from fxars.live.desktop_notify import DesktopNotifier
            notifier = DesktopNotifier(enabled=True)
            ok = notifier.send("FX-ARS", "Test desktop notification")
            return self._json(200, {
                "ok": bool(ok),
                "backend": notifier._backend,
                "available": notifier.is_available(),
            })
        except Exception as exc:
            logger.exception("desktop test failed")
            return self._json(502, {"ok": False, "error": str(exc)})


class _Handler(BaseHTTPRequestHandler):
    server_version = "FXARS/1.0"
    protocol_version = "HTTP/1.1"

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        max_bytes = self.server.app.settings.api.max_body_bytes  # type: ignore[attr-defined]
        if length > max_bytes:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
            self._send(ApiResponse(
                413,
                b'{"error":{"code":"PAYLOAD_TOO_LARGE","message":"Request body too large.","correlation_id":"","details":{}}}',
                headers={"Connection": "close"},
            ))
            return
        body = self.rfile.read(length) if length else b""
        request = ApiRequest(
            method=method,
            path=parsed.path.rstrip("/") or "/",
            query=parse_qs(parsed.query),
            headers={key.lower(): value for key, value in self.headers.items()},
            body=body,
            ip=self.client_address[0] if self.client_address else "",
        )
        response = self.server.app.handle(request)  # type: ignore[attr-defined]
        self._send(response)

    def _send(self, response: ApiResponse) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.end_headers()
        # FIX-04-HEAD-EMPTY-BODY: برای HEAD، body نوشته نمی‌شود (RFC 7231 §4.3.2)
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        cors = getattr(self.server.app.settings.api, 'cors_allow_origin', '')  # type: ignore[attr-defined]

# FIX-15-CORS-DEFAULT: پیش‌فرض same-origin (بدون ACAO)، نه *
        if cors:
            self.send_header('Access-Control-Allow-Origin', cors)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE, PUT, PATCH, HEAD")
        self.end_headers()

    def _method_not_allowed(self, method: str) -> None:
        body = json.dumps({
            "error": {
                "code": "METHOD_NOT_ALLOWED",
                "message": "متد مجاز نیست.",
                "correlation_id": "",
                "details": {"method": method, "allowed": ["GET", "POST", "OPTIONS", "HEAD"]},
            }
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(405)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Allow", "GET, POST, OPTIONS, HEAD")
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed("DELETE")

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed("PATCH")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle("HEAD")

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("http", extra={"data": {"client": self.client_address[0], "message": format % args}})


class FxarsServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], app: ApiApp) -> None:
        super().__init__(address, _Handler)
        self.app = app


def create_server(platform: Platform, host: str | None = None, port: int | None = None) -> FxarsServer:
    app = ApiApp(platform)
    bind_host = host if host is not None else platform.settings.api.host
    bind_port = port if port is not None else platform.settings.api.port
    return FxarsServer((bind_host, bind_port), app)


def serve(platform: Platform, host: str | None = None, port: int | None = None) -> None:
    server = create_server(platform, host, port)
    address = f"http://{server.server_address[0]}:{server.server_address[1]}"
    logger.info("api server starting", extra={"data": {"address": address}})
    print(f"FX-ARS API: {address}  (dashboard: {address}/)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        server.server_close()
# FIX-08-RATE-LIMIT

# FIX-08-OUTBOX-API


# FIX-15-CORS-DEFAULT

# FIX-21-TRADING-HISTORY
