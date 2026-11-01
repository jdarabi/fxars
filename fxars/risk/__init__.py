"""مدیریت ریسک و دروازه ایمنی."""

from fxars.risk.account import demo_account, parse_account_snapshot
from fxars.risk.gate import RiskContext, RiskGate
from fxars.risk.killswitch import KillSwitch
from fxars.risk.sizing import SizingInput, SizingResult, calculate_position_size

__all__ = [
    "RiskContext",
    "RiskGate",
    "KillSwitch",
    "SizingInput",
    "SizingResult",
    "calculate_position_size",
    "parse_account_snapshot",
    "demo_account",
]
