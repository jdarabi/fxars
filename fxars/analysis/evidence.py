"""کارخانه Evidence: شناسه پایدار، پارامتر‌هش و اعتبارسنجی قرارداد."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from fxars.analysis.context import AnalysisContext
from fxars.core.numerics import clamp
from fxars.domain.enums import Direction, EvidenceFamily
from fxars.domain.models import Evidence, PriceZone


class EvidenceFactory:
    def __init__(self, context: AnalysisContext, run_id: str) -> None:
        self.context = context
        self.run_id = run_id
        self._counter = 0
        self._param_cache: dict[tuple, str] = {}
        self.created: list[Evidence] = []

    def _parameters_hash(self, module_id: str, params: dict[str, Any] | None) -> str:
        key = (module_id, tuple(sorted((str(k), str(v)) for k, v in (params or {}).items())))
        cached = self._param_cache.get(key)
        if cached is None:
            cached = "sha256:" + hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:16]
            self._param_cache[key] = cached
        return cached

    def create(
        self,
        *,
        module_id: str,
        module_version: str,
        family: EvidenceFamily,
        direction: Direction,
        strength: float,
        confidence: float,
        observed_at: datetime,
        available_at: datetime,
        explanation: str,
        zone: PriceZone | None = None,
        invalidation: dict[str, Any] | None = None,
        expiry: datetime | None = None,
        source_refs: tuple[str, ...] = (),
        params: dict[str, Any] | None = None,
    ) -> Evidence:
        self._counter += 1
        strength = round(clamp(float(strength), 0.0, 1.0), 6)
        confidence = round(clamp(float(confidence), 0.0, 1.0), 6)
        fingerprint = (
            f"{self.run_id}|{module_id}|{observed_at.isoformat()}|{self._counter}|"
            f"{direction.value}|{strength:.6f}|{family.value}"
        )
        evidence_id = "ev_" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
        evidence = Evidence(
            evidence_id=evidence_id,
            analysis_run_id=self.run_id,
            module_id=module_id,
            module_version=module_version,
            instrument_id=self.context.instrument.instrument_id,
            timeframe=self.context.timeframe,
            observed_at=observed_at,
            available_at=available_at,
            direction=direction,
            strength=strength,
            confidence_raw=confidence,
            family=family,
            explanation=explanation,
            price_zone=zone,
            invalidation=invalidation,
            expiry=expiry,
            parameters_hash=self._parameters_hash(module_id, params),
            source_refs=source_refs,
        )
        self.created.append(evidence)
        return evidence
