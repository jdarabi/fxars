"""RBAC: نقش‌ها و مجوزهای پایه (بخش ۳ سند)."""

from __future__ import annotations

from fxars.domain.enums import Permission, Role

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.ANALYST: frozenset({
        Permission.DATA_READ,
        Permission.ANALYSIS_RUN,
        Permission.SCENARIO_READ,
        Permission.SCENARIO_TRANSITION,
        Permission.RISK_EVALUATE,
        Permission.REPORT_READ,
    }),
    Role.RESEARCHER: frozenset({
        Permission.DATA_READ,
        Permission.ANALYSIS_RUN,
        Permission.SCENARIO_READ,
        Permission.BACKTEST_RUN,
        Permission.REPORT_READ,
    }),
    Role.RISK_MANAGER: frozenset({
        Permission.DATA_READ,
        Permission.SCENARIO_READ,
        Permission.RISK_EVALUATE,
        Permission.RISK_POLICY_WRITE,
        Permission.EXECUTION_APPROVE,
        Permission.KILLSWITCH_TOGGLE,
        Permission.AUDIT_READ,
        Permission.REPORT_READ,
    }),
    Role.OPERATOR: frozenset({
        Permission.DATA_READ,
        Permission.SCENARIO_READ,
        Permission.RISK_EVALUATE,
        Permission.EXECUTION_ORDER,
        Permission.KILLSWITCH_TOGGLE,
    }),
    Role.TENANT_USER: frozenset({
        Permission.DATA_READ,
        Permission.SCENARIO_READ,
        Permission.REPORT_READ,
    }),
    Role.AUDITOR: frozenset({
        Permission.AUDIT_READ,
        Permission.DATA_READ,
        Permission.SCENARIO_READ,
        Permission.REPORT_READ,
    }),
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in permissions_for(role)


def require_permission(role: Role, permission: Permission) -> None:
    from fxars.core.errors import AuthorizationError

    if not has_permission(role, permission):
        raise AuthorizationError(
            f"نقش {role.value} مجوز {permission.value} را ندارد.",
            details={"role": role.value, "permission": permission.value},
        )
