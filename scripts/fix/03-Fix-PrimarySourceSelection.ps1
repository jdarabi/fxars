#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
Write-Host "[FIX-03] Primary source selection" -ForegroundColor Cyan

# --- 3.1 افزودن helper در InstrumentRepository ---
$repoFile = Join-Path $ProjectRoot 'fxars\storage\repositories.py'
$content = Get-Content $repoFile -Raw -Encoding UTF8
if ($content -notmatch 'def primary_source\(') {
    $anchor = @'
    def seed_defaults(self, instruments: Iterable[Instrument], source: DataSource) -> int:
'@
    $patch = @'
    def primary_source(self, instrument_id: str, timeframe: str) -> str:
        """FIX-03-PRIMARY-SOURCE: انتخاب منبع اصلی برای تحلیل/بک‌تست.

        اگر فقط یک منبع وجود دارد همان برگردانده می‌شود؛ در غیر این صورت از
        DataSource.priority استفاده می‌شود؛ در نهایت نام منبع به‌صورت صریح خطا می‌دهد.
        """
        sources = self.db.query(
            "SELECT source_id FROM candles WHERE instrument_id=? AND timeframe=? "
            "GROUP BY source_id ORDER BY source_id",
            (instrument_id, Timeframe.parse(timeframe).value),
        )
        ids = [row["source_id"] for row in sources]
        if not ids:
            raise NotFoundError(
                f"هیچ منبع داده‌ای برای {instrument_id}/{timeframe} ثبت نشده است.",
                details={"instrument_id": instrument_id, "timeframe": timeframe},
            )
        if len(ids) == 1:
            return ids[0]
        # اولویت از data_sources
        priority_rows = self.db.query(
            "SELECT source_id, payload FROM data_sources WHERE source_id IN ({})".format(
                ",".join("?" for _ in ids)
            ),
            ids,
        )
        ranked: list[tuple[int, str]] = []
        for row in priority_rows:
            payload = _load(row["payload"])
            ranked.append((int(payload.get("priority", 100)), row["source_id"]))
        ranked.sort()
        for _, sid in ranked:
            if sid in ids:
                return sid
        return ids[0]

    def seed_defaults(self, instruments: Iterable[Instrument], source: DataSource) -> int:
'@
    $content = $content.Replace($anchor, $patch)
    Set-Content -Path $repoFile -Value $content -Encoding UTF8 -NoNewline
    Write-Host "  [OK] InstrumentRepository.primary_source added" -ForegroundColor Green
} else {
    Write-Host "  primary_source already present" -ForegroundColor Yellow
}

# --- 3.2 AnalysisService ---
$file = Join-Path $ProjectRoot 'fxars\services\analysis.py'
$content = Get-Content $file -Raw -Encoding UTF8
if ($content -notmatch 'PRIMARY_SOURCE') {
    $old = @'
        candles = [
            candle
            for candle in self.candles.range(instrument_id, tf.value, as_of=moment, closed_only=True)
            if candle.quality_status is not QualityStatus.INVALID
        ]
'@
    $new = @'
        # PRIMARY_SOURCE: تحلیل فقط روی منبع اصلی انجام می‌شود تا هم‌پوشانی منابع
        # باعث تولید کندل تکراری با قیمت‌های متفاوت و خرابی Swing/BOS نشود.
        primary_source = self.instruments.primary_source(instrument_id, tf.value)
        candles = [
            candle
            for candle in self.candles.range(
                instrument_id, tf.value, source_id=primary_source, as_of=moment, closed_only=True,
            )
            if candle.quality_status is not QualityStatus.INVALID
        ]
'@
    if (-not $content.Contains($old)) { throw "AnalysisService anchor not found" }
    $content = $content.Replace($old, $new)

    # reference هم باید منبع اصلی داشته باشد
    $oldRef = @'
        for reference_id in self.settings.analysis.intermarket_refs.get(instrument_id, []):
            candles = self.candles.range(reference_id, timeframe, as_of=moment, closed_only=True)
            if candles:
                references[reference_id] = candles
'@
    $newRef = @'
        for reference_id in self.settings.analysis.intermarket_refs.get(instrument_id, []):
            try:
                ref_source = self.instruments.primary_source(reference_id, timeframe)
            except Exception:
                continue
            candles = self.candles.range(
                reference_id, timeframe, source_id=ref_source, as_of=moment, closed_only=True,
            )
            if candles:
                references[reference_id] = candles
'@
    if (-not $content.Contains($oldRef)) { throw "AnalysisService reference anchor not found" }
    $content = $content.Replace($oldRef, $newRef)
    Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
    Write-Host "  [OK] AnalysisService uses primary_source" -ForegroundColor Green
} else {
    Write-Host "  AnalysisService already patched" -ForegroundColor Yellow
}

# --- 3.3 RiskService ---
$file = Join-Path $ProjectRoot 'fxars\risk\service.py'
$content = Get-Content $file -Raw -Encoding UTF8
if ($content -notmatch 'PRIMARY_SOURCE') {
    $old = @'
        candle = None
        if instrument is not None:
            candles = self.candles.range(scenario.instrument_id, scenario.timeframe, as_of=moment, closed_only=True)
            candle = candles[-1] if candles else None
'@
    $new = @'
        candle = None
        if instrument is not None:
            try:
                primary_source = self.instruments.primary_source(scenario.instrument_id, scenario.timeframe)
            except Exception:
                primary_source = None
            candles = self.candles.range(
                scenario.instrument_id, scenario.timeframe, source_id=primary_source,
                as_of=moment, closed_only=True,
            )
            candle = candles[-1] if candles else None
'@
    if (-not $content.Contains($old)) { throw "RiskService anchor not found" }
    $content = $content.Replace($old, $new)
    Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
    Write-Host "  [OK] RiskService uses primary_source" -ForegroundColor Green
}

# --- 3.4 ResearchService ---
$file = Join-Path $ProjectRoot 'fxars\research\service.py'
$content = Get-Content $file -Raw -Encoding UTF8
if ($content -notmatch 'PRIMARY_SOURCE') {
    $old = @'
        instrument = self.instruments.get(instrument_id)
        candles = [
            candle for candle in self.candles.range(instrument_id, timeframe, as_of=as_of, closed_only=True)
            if candle.quality_status is not QualityStatus.INVALID
        ]
'@
    $new = @'
        instrument = self.instruments.get(instrument_id)
        primary_source = self.instruments.primary_source(instrument_id, timeframe)
        candles = [
            candle for candle in self.candles.range(
                instrument_id, timeframe, source_id=primary_source, as_of=as_of, closed_only=True,
            )
            if candle.quality_status is not QualityStatus.INVALID
        ]
'@
    if (-not $content.Contains($old)) { throw "ResearchService anchor not found" }
    $content = $content.Replace($old, $new)
    Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
    Write-Host "  [OK] ResearchService uses primary_source" -ForegroundColor Green
}