"""زمینه اجرا: correlation_id و actor برای لاگ، ممیزی و Outbox."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from fxars.core.ids import correlation_id as new_correlation_id

_correlation: ContextVar[str | None] = ContextVar("fxars_correlation_id", default=None)
_actor: ContextVar[str] = ContextVar("fxars_actor", default="system")


def current_correlation_id() -> str:
    value = _correlation.get()
    if value is None:
        value = new_correlation_id()
        _correlation.set(value)
    return value


def set_correlation_id(value: str) -> None:
    _correlation.set(value)


def current_actor() -> str:
    return _actor.get()


def set_actor(value: str) -> None:
    _actor.set(value)


@contextmanager
def correlation_scope(correlation_id: str | None = None, actor: str | None = None) -> Iterator[str]:
    corr_token = _correlation.set(correlation_id or new_correlation_id())
    actor_token = _actor.set(actor) if actor else None
    try:
        yield current_correlation_id()
    finally:
        _correlation.reset(corr_token)
        if actor_token is not None:
            _actor.reset(actor_token)
