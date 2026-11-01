"""سرویس هویت: کاربر، رمز، MFA، نشست و محدودیت تلاش ورود."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from fxars.audit.audit import AuditAction, AuditLog
from fxars.config.settings import Settings
from fxars.core.errors import AuthenticationError, RateLimitedError, ValidationError
from fxars.core.ids import new_id
from fxars.core.timeutil import utcnow
from fxars.domain.enums import Role
from fxars.domain.models import SessionRecord, User
from fxars.identity.passwords import SecretBox, hash_password, verify_password
from fxars.identity.totp import generate_secret, verify_totp
from fxars.storage.repositories import LoginAttemptRepository, SessionRepository, UserRepository

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@dataclass
class AuthResult:
    user: User
    token: str
    session: SessionRecord


class IdentityService:
    def __init__(
        self,
        *,
        settings: Settings,
        clock: Callable[[], datetime],
        users: UserRepository,
        sessions: SessionRepository,
        attempts: LoginAttemptRepository,
        audit: AuditLog,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.users = users
        self.sessions = sessions
        self.attempts = attempts
        self.audit = audit
        self.secrets = SecretBox(settings.security.secret_key)

    # ------------------------------------------------------------------ کاربران
    def create_user(
        self,
        username: str,
        role: Role | str,
        password: str,
        *,
        totp_enabled: bool = False,
        display_name: str = "",
        actor: str = "system",
    ) -> tuple[User, str | None]:
        if not USERNAME_RE.match(username):
            raise ValidationError("نام کاربری باید ۳ تا ۳۲ کاراکتر و شامل حروف/اعداد/._- باشد.")
        role = Role(role)
        if self.users.get_by_username(username) is not None:
            raise ValidationError(f"نام کاربری {username} قبلاً ثبت شده است.")
        try:
            encoded = hash_password(password, iterations=self.settings.security.pbkdf2_iterations)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        secret: str | None = None
        encrypted: str | None = None
        if totp_enabled:
            secret = generate_secret()
            encrypted = self.secrets.encrypt(secret)
        user = User(
            user_id=new_id("usr", 16),
            username=username,
            role=role,
            password_hash=encoded,
            totp_secret_enc=encrypted,
            active=True,
            created_at=self.clock(),
            tenant_id="default",
            display_name=display_name or username,
        )
        self.users.save(user)
        self.audit.append(
            AuditAction.USER_CREATED, "user", user.user_id, actor=actor,
            payload={"username": username, "role": role.value, "mfa": totp_enabled, "tenant_id": user.tenant_id},
        )
        return user, secret

    def set_password(self, user_id: str, password: str, *, actor: str) -> None:
        user = self.users.get(user_id)
        if user is None:
            raise ValidationError("کاربر یافت نشد.")
        encoded = hash_password(password, iterations=self.settings.security.pbkdf2_iterations)
        from dataclasses import replace

        self.users.save(replace(user, password_hash=encoded))
        self.sessions.revoke_all(user_id) if hasattr(self.sessions, "revoke_all") else None
        self.audit.append("USER_PASSWORD_CHANGED", "user", user_id, actor=actor, payload={})

    def list_users(self) -> list[User]:
        return self.users.list()

    # ------------------------------------------------------------------ ورود
    def login(self, username: str, password: str, *, totp_code: str | None = None, ip: str = "") -> AuthResult:
        moment = self.clock()
        user = self.users.get_by_username(username)
        if user is None or not user.active:
            self._failed(username, ip)
            raise AuthenticationError("نام کاربری یا رمز عبور نادرست است.")
        since = moment - timedelta(seconds=self.settings.security.login_window_seconds)
        if self.attempts.failures_since(username, since) >= self.settings.security.login_max_attempts:
            raise RateLimitedError("تلاش‌های ناموفق ورود بیش از حد مجاز است؛ بعداً تلاش کنید.")
        if not verify_password(password, user.password_hash):
            self._failed(username, ip)
            raise AuthenticationError("نام کاربری یا رمز عبور نادرست است.")
        if user.role in self.settings.security.mfa_roles:
            if not user.totp_secret_enc:
                raise AuthenticationError("برای این نقش MFA الزامی است و هنوز پیکربندی نشده است.")
            secret = self.secrets.decrypt(user.totp_secret_enc)
            if not totp_code or not verify_totp(secret, totp_code, at=moment.timestamp()):
                self._failed(username, ip)
                raise AuthenticationError("کد MFA نامعتبر است.")
        self.attempts.add(username, ip, True)
        self.audit.append(AuditAction.USER_LOGIN, "user", user.user_id, actor=username,
                          payload={"ip": ip, "role": user.role.value})
        return self.start_session(user, ip=ip)

    def start_session(self, user: User, *, ip: str = "") -> AuthResult:
        moment = self.clock()
        token = secrets.token_urlsafe(self.settings.security.session_token_bytes)
        session = SessionRecord(
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            user_id=user.user_id,
            created_at=moment,
            expires_at=moment + timedelta(minutes=self.settings.api.session_ttl_minutes),
            ip=ip,
            revoked=False,
        )
        self.sessions.save(session)
        return AuthResult(user=user, token=token, session=session)

    def resolve_session(self, token: str) -> tuple[User, SessionRecord] | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        session = self.sessions.get(token_hash)
        if session is None or not session.is_valid(self.clock()):
            return None
        user = self.users.get(session.user_id)
        if user is None or not user.active:
            return None
        return user, session

    def logout(self, token: str, *, actor: str = "system") -> None:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.sessions.revoke(token_hash)
        self.audit.append(AuditAction.USER_LOGOUT, "session", token_hash[:12], actor=actor, payload={})

    def totp_secret(self, user: User) -> str | None:
        if not user.totp_secret_enc:
            return None
        return self.secrets.decrypt(user.totp_secret_enc)

    def _failed(self, username: str, ip: str) -> None:
        self.attempts.add(username, ip, False)
        self.audit.append(AuditAction.USER_LOGIN_FAILED, "user", username, actor=username, payload={"ip": ip})
