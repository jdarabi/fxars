"""خط لوله دریافت داده: اعتبارسنجی، قرنطینه، ذخیره، گزارش کیفیت و رویدادها."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from fxars.audit.audit import AuditAction, AuditLog
from fxars.audit.outbox import EventType, Outbox
from fxars.core.errors import DataInvalidError
from fxars.core.timeutil import format_ts, utcnow
from fxars.data.providers import read_candle_csv
from fxars.data.quality import DataQualityEngine
from fxars.data.snapshot import snapshot_id
from fxars.data.validation import CandleValidator
from fxars.domain.models import Candle, DataQualityRun, Instrument
from fxars.storage.db import Database
from fxars.storage.repositories import (
    CandleRepository,
    DataQualityRepository,
    InstrumentRepository,
    RawPayloadRepository,
)


@dataclass
class IngestionResult:
    instrument_id: str
    timeframe: str
    source_id: str
    accepted: int
    quarantined: int
    duplicates: int
    revised: int
    quality: DataQualityRun | None
    raw_payload_id: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)


class IngestionService:
    def __init__(
        self,
        *,
        db: Database,
        candles: CandleRepository,
        instruments: InstrumentRepository,
        quality_runs: DataQualityRepository,
        raw_payloads: RawPayloadRepository,
        quality: DataQualityEngine,
        audit: AuditLog,
        outbox: Outbox,
    ) -> None:
        self.db = db
        self.candles = candles
        self.instruments = instruments
        self.quality_runs = quality_runs
        self.raw_payloads = raw_payloads
        self.quality = quality
        self.audit = audit
        self.outbox = outbox

    def ingest(
        self,
        candles: list[Candle],
        *,
        instrument_id: str,
        source_id: str,
        raw_content: bytes | None = None,
        raw_meta: dict[str, Any] | None = None,
        now: datetime | None = None,
        evaluate_reference: bool = True,
    ) -> IngestionResult:
        if not candles:
            raise DataInvalidError("فهرست کندل‌ها خالی است.")
        instrument = self.instruments.get(instrument_id)
        tf = candles[0].timeframe
        if any(candle.timeframe != tf for candle in candles):
            raise DataInvalidError("کندل‌های یک دسته باید تایم‌فریم یکسان داشته باشند.")
        if any(candle.instrument_id != instrument_id for candle in candles):
            raise DataInvalidError("کندل‌ها با instrument_id درخواست سازگار نیستند.")

        moment = now or utcnow()
        validator = CandleValidator(instrument, now=moment)
        accepted: list[Candle] = []
        quarantined = 0
        for candle in candles:
            assessment = validator.assess(candle)
            if assessment.status.value == "INVALID":
                self.candles.quarantine(candle, assessment.reasons or assessment.flags)
                quarantined += 1
            else:
                stored = candle
                if assessment.status.value == "SUSPECT" and not candle.quality_flags:
                    stored = replace(candle, quality_status="SUSPECT", quality_flags=assessment.flags)
                accepted.append(stored)

        stats = self.candles.bulk_upsert(accepted) if accepted else {"inserted": 0, "duplicate": 0, "revised": 0}

        # کیفیت روی کل سری ذخیره‌شده همان منبع سنجیده می‌شود، نه فقط دسته جدید.
        series = self.candles.range(instrument_id, tf, source_id=source_id, closed_only=False)
        reference_series = None
        if evaluate_reference:
            other_sources = [source for source in self.candles.sources(instrument_id, tf) if source != source_id]
            if other_sources:
                reference_series = self.candles.range(instrument_id, tf, source_id=other_sources[0], closed_only=False)
        quality_run = self.quality.evaluate(
            instrument=instrument, timeframe=tf, source_id=source_id, candles=series,
            now=moment, reference_candles=reference_series,
        )

        raw_id = None
        if raw_content is not None:
            raw_id = self.raw_payloads.store(source_id, "candles_csv", raw_content, meta=raw_meta or {}, received_at=moment)

        with self.db.transaction():
            self.quality_runs.save(quality_run)
            snapshot = snapshot_id(series, instrument_id, tf)
            self.audit.append(
                AuditAction.DATA_INGESTED,
                "candle_batch",
                snapshot,
                payload={
                    "instrument_id": instrument_id,
                    "timeframe": tf,
                    "source_id": source_id,
                    "accepted": len(accepted),
                    "quarantined": quarantined,
                    **stats,
                    "quality_run_id": quality_run.run_id,
                    "quality_verdict": quality_run.verdict,
                },
            )
            if quarantined:
                self.audit.append(
                    AuditAction.DATA_QUARANTINED,
                    "candle_batch",
                    snapshot,
                    payload={"instrument_id": instrument_id, "count": quarantined},
                )
            self.outbox.emit(
                EventType.CANDLES_INGESTED,
                {
                    "instrument_id": instrument_id,
                    "timeframe": tf,
                    "source_id": source_id,
                    "accepted": len(accepted),
                    "quarantined": quarantined,
                    "snapshot_id": snapshot,
                },
                occurred_at=moment,
            )
            self.outbox.emit(
                EventType.DATA_QUALITY_COMPLETED,
                {"run_id": quality_run.run_id, "verdict": quality_run.verdict, "stale": quality_run.stale},
                occurred_at=moment,
            )

        return IngestionResult(
            instrument_id=instrument_id,
            timeframe=tf,
            source_id=source_id,
            accepted=len(accepted),
            quarantined=quarantined,
            duplicates=stats["duplicate"],
            revised=stats["revised"],
            quality=quality_run,
            raw_payload_id=raw_id,
        )

    def ingest_csv(
        self,
        path: str | Path,
        *,
        instrument_id: str,
        source_id: str,
        timeframe: str,
        now: datetime | None = None,
    ) -> IngestionResult:
        loaded = read_candle_csv(path, instrument_id=instrument_id, source_id=source_id, timeframe=timeframe, now=now)
        if not loaded.candles:
            raise DataInvalidError("هیچ ردیف معتبری در فایل CSV یافت نشد.", details={"errors": loaded.errors[:10]})
        content = Path(path).read_bytes()
        result = self.ingest(
            loaded.candles,
            instrument_id=instrument_id,
            source_id=source_id,
            raw_content=content,
            raw_meta={"path": str(path), "content_hash": loaded.content_hash, "rows": loaded.rows},
            now=now,
        )
        result.errors = loaded.errors
        return result

    def verify_available(self, instrument_id: str, timeframe: str, as_of: datetime, *, source_id: str | None = None) -> list[Candle]:
        """کندل‌های قابل استفاده در زمان as_of (قرارداد بازتولید بدون نگاه به آینده)."""
        return self.candles.range(
            instrument_id, timeframe, source_id=source_id, closed_only=True, as_of=as_of,
        )
