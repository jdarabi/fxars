#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\data\ingestion.py'
if (-not (Test-Path $file)) { throw "Not found: $file" }

Write-Host "[FIX-01] Patching $file" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8

# نگهداری patch برای idempotency
if ($content -match 'FIX-01-INGESTION-TX') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

# --- اصلاح main method `ingest` ---
# ورودی: کل روش را با نسخه اتمیک جایگزین می‌کنیم.
$oldMethod = @'
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
'@

$newMethod = @'
        # FIX-01-INGESTION-TX: کل چرخه در یک تراکنش واحد.
        # اعتبارسنجی، قرنطینه، Upsert کندل، QualityRun، Audit و Outbox اتمیک می‌شوند.
        accepted: list[Candle] = []
        quarantine_items: list[tuple[Candle, tuple[str, ...]]] = []
        for candle in candles:
            assessment = validator.assess(candle)
            if assessment.status.value == "INVALID":
                quarantine_items.append((candle, tuple(assessment.reasons or assessment.flags)))
            else:
                stored = candle
                if assessment.status.value == "SUSPECT" and not candle.quality_flags:
                    stored = replace(candle, quality_status="SUSPECT", quality_flags=assessment.flags)
                accepted.append(stored)

        stats = {"inserted": 0, "duplicate": 0, "revised": 0}
        quality_run: DataQualityRun | None = None
        snapshot = ""
        raw_id: str | None = None

        with self.db.transaction():
            # 1) قرنطینه
            for candle, reasons in quarantine_items:
                self.candles.quarantine(candle, reasons)
            quarantined = len(quarantine_items)

            # 2) Upsert کندل‌ها
            if accepted:
                stats = self.candles.bulk_upsert(accepted)

            # 3) Raw payload (فقط‌افزودنی، اما در تراکنش برای ثبت هم‌زمان)
            if raw_content is not None:
                raw_id = self.raw_payloads.store(
                    source_id, "candles_csv", raw_content,
                    meta=raw_meta or {}, received_at=moment,
                )

            # 4) کیفیت روی کل سری ذخیره‌شده همان منبع
            series = self.candles.range(instrument_id, tf, source_id=source_id, closed_only=False)
            reference_series = None
            if evaluate_reference:
                other_sources = [s for s in self.candles.sources(instrument_id, tf) if s != source_id]
                if other_sources:
                    reference_series = self.candles.range(
                        instrument_id, tf, source_id=other_sources[0], closed_only=False,
                    )
            quality_run = self.quality.evaluate(
                instrument=instrument, timeframe=tf, source_id=source_id, candles=series,
                now=moment, reference_candles=reference_series,
            )
            self.quality_runs.save(quality_run)
            snapshot = snapshot_id(series, instrument_id, tf)

            # 5) Audit + Outbox
            self.audit.append(
                AuditAction.DATA_INGESTED, "candle_batch", snapshot,
                payload={
                    "instrument_id": instrument_id, "timeframe": tf, "source_id": source_id,
                    "accepted": len(accepted), "quarantined": quarantined, **stats,
                    "quality_run_id": quality_run.run_id, "quality_verdict": quality_run.verdict,
                },
            )
            if quarantined:
                self.audit.append(
                    AuditAction.DATA_QUARANTINED, "candle_batch", snapshot,
                    payload={"instrument_id": instrument_id, "count": quarantined},
                )
            self.outbox.emit(
                EventType.CANDLES_INGESTED,
                {"instrument_id": instrument_id, "timeframe": tf, "source_id": source_id,
                 "accepted": len(accepted), "quarantined": quarantined, "snapshot_id": snapshot},
                occurred_at=moment,
            )
            self.outbox.emit(
                EventType.DATA_QUALITY_COMPLETED,
                {"run_id": quality_run.run_id, "verdict": quality_run.verdict, "stale": quality_run.stale},
                occurred_at=moment,
            )

        return IngestionResult(
            instrument_id=instrument_id, timeframe=tf, source_id=source_id,
            accepted=len(accepted), quarantined=len(quarantine_items),
            duplicates=stats["duplicate"], revised=stats["revised"],
            quality=quality_run, raw_payload_id=raw_id,
        )
'@

if (-not $content.Contains($oldMethod)) {
    throw "Original ingest() body not found — file may have changed. Aborting."
}

$content = $content.Replace($oldMethod, $newMethod)

# اطمینان از import DataQualityRun
if ($content -notmatch 'from fxars\.domain\.models import .*DataQualityRun') {
    $content = $content.Replace(
        'from fxars.domain.models import Candle, DataQualityRun, Instrument',
        'from fxars.domain.models import Candle, DataQualityRun, Instrument'
    )
}

Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] ingestion.py patched (atomic transaction)" -ForegroundColor Green