"""HTTP API با کتابخانه استاندارد (بدون وابستگی خارجی).

قرارداد: مسیرهای نسخه‌دار /api/v1، خطای ساختاریافته، RBAC سمت سرور، rate limit،
Idempotency-Key برای عملیات حساس و correlation_id در همه پاسخ‌ها.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from fxars.api.openapi import docs_html, openapi_spec
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
from fxars.api.metrics import get_registry
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


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


class ApiApp:
    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.settings = platform.settings
        self.identity = platform.identity
        self.limiter = RateLimiter(self.settings.api.rate_limit_per_minute, 60)
        self.routes: list[tuple[str, re.Pattern[str], Callable[..., ApiResponse], Permission | None, bool]] = []
        self.metrics = get_registry()
        self._register()

    def _register(self) -> None:
        def add(method: str, pattern: str, handler: Callable[..., ApiResponse],
                permission: Permission | None = None, public: bool = False) -> None:
            self.routes.append((method, re.compile(pattern), handler, permission, public))

        add("GET", r"^/api/v1/health$", self._health, public=True)
        add("GET", r"^/api/v1/health/live$", self._health_live, public=True)
        add("GET", r"^/api/v1/health/ready$", self._health_ready, public=True)
        add("GET", r"^/api/v1/metrics$", self._metrics_endpoint, public=True)
        add("POST", r"^/api/v1/auth/login$", self._login, public=True)
        add("POST", r"^/api/v1/auth/demo-login$", self._demo_login, public=True)
        add("GET", r"^/api/v1/auth/demo-totp$", self._demo_totp, public=True)
        add("POST", r"^/api/v1/auth/logout$", self._logout)
        add("GET", r"^/api/v1/auth/me$", self._me)
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
        add("POST", r"^/api/v1/killswitch$", self._killswitch_set, Permission.KILLSWITCH_TOGGLE)

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
            key = self._rate_key(request)
            if not self.limiter.allow(key):
                raise RateLimitedError()
            user = None
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
            if request.method == "POST" and not public:
                return self._with_idempotency(request, user, lambda: handler(request, match.groupdict(), user))
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

    def _rate_key(self, request: ApiRequest) -> str:
        header = request.headers.get("authorization", "")
        return header[7:][:24] if header else request.ip

    def _token(self, request: ApiRequest) -> str:
        return request.headers.get("authorization", "")[7:].strip()

    def _with_idempotency(self, request: ApiRequest, user, action: Callable[[], ApiResponse]) -> ApiResponse:
        key = request.headers.get("idempotency-key", "").strip()
        if not key:
            if self.settings.api.require_idempotency:
                raise ValidationError("برای عملیات POST هدر Idempotency-Key الزامی است.")
            return action()
        request_hash = sha256_obj({"path": request.path, "body": request.body.decode("utf-8", "replace")})
        existing = self.platform.idempotency.get(key, user.user_id)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                from fxars.core.errors import IdempotencyConflictError

                raise IdempotencyConflictError(details={"key": key})
            return self._json(existing["status"], existing["response"])
        response = action()
        payload = json.loads(response.body.decode("utf-8")) if response.body else {}
        self.platform.idempotency.put(key, user.user_id, request.path, request_hash, response.status, payload)
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

    def _health(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        db_ok = self.platform.db.query_one("SELECT 1 AS ok") is not None
        return self._json(200, {
            "status": "ok" if db_ok else "degraded",
            "phase": self.settings.phase.value,
            "time": format_ts(self.platform.clock()),
            "audit": self.platform.audit.verify()["valid"],
            "killswitch": self.platform.killswitch.is_active(),
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
        return self.settings.environment == "dev" and request.ip in ("127.0.0.1", "::1", "")

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
        runs = self.platform.analyses.list_runs(instrument_id=request.one("instrument_id"), limit=limit, offset=offset)
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
        result = self.platform.run_analysis(instrument_id, timeframe, as_of=as_of, actor=user.username)
        return self._json(200, {
            "run": result.run.to_dict(),
            "decision": result.decision.to_dict(),
            "scenario": result.scenario.to_dict() if result.scenario else None,
            "scenario_reason": result.scenario_reason,
            "evidences": [evidence.to_dict() for evidence in result.evidences],
        })

    def _analysis_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        run = self.platform.analyses.get_run(params["run_id"])
        evidences = self.platform.analyses.evidence_for(run.run_id)
        scenario = self.platform.scenarios.find_by_run(run.run_id)
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
        )
        return self._json(200, {"items": [scenario.to_dict() for scenario in scenarios], "count": len(scenarios),
                                 "summary": self.platform.scenarios.count_by_status()})

    def _scenario_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        scenario = self.platform.scenarios.get(params["scenario_id"])
        transitions = self.platform.scenarios.transitions(scenario.scenario_id)
        decision = self.platform.decisions.latest_for_scenario(scenario.scenario_id)
        return self._json(200, {
            "scenario": scenario.to_dict(),
            "transitions": [transition.to_dict() for transition in transitions],
            "risk_decision": decision.to_dict() if decision else None,
        })

    def _scenario_evaluate(self, request: ApiRequest, params: dict, user) -> ApiResponse:
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
        result = self.platform.scenario_service.transition(
            params["scenario_id"], target, actor=user.username, reason=reason, now=self.platform.clock(),
        )
        return self._json(200, {
            "scenario": result.scenario.to_dict(),
            "transition": result.transition.to_dict() if result.transition else None,
        })

    def _risk_list(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        limit, offset = self._page(request)
        decisions = self.platform.decisions.list(limit=limit, offset=offset)
        return self._json(200, {"items": [decision.to_dict() for decision in decisions], "count": len(decisions)})

    def _risk_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        decision = self.platform.decisions.get(params["decision_id"])
        return self._json(200, {"decision": decision.to_dict()})

    def _risk_evaluate(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        scenario_id = body.get("scenario_id")
        if not scenario_id:
            raise ValidationError("scenario_id الزامی است.")
        decision = self.platform.evaluate_risk(
            str(scenario_id), body.get("account"), rates=body.get("rates"), actor=user.username,
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
        result = self.platform.research.run(
            instrument_id, timeframe, config_overrides=body.get("overrides") or {},
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

    def _killswitch_get(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        return self._json(200, {"killswitch": self.platform.killswitch.status()})

    def _killswitch_set(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        reason = str(body.get("reason", "")).strip()
        if "active" not in body:
            raise ValidationError("فیلد active الزامی است.")
        status = self.platform.set_kill_switch(bool(body["active"]), actor=user.username, reason=reason)
        return self._json(200, {"killswitch": status})


class _Handler(BaseHTTPRequestHandler):
    server_version = "FXARS/1.0"
    protocol_version = "HTTP/1.1"

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        max_bytes = self.server.app.settings.api.max_body_bytes  # type: ignore[attr-defined]
        if length > max_bytes:
            # FIX-P2-3: drain body so client can finish sending and read the 413 response
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
        self.wfile.write(response.body)

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
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
