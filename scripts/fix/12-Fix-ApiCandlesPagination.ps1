#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\api\server.py'
Write-Host "[FIX-12] API candles pagination" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-12-CANDLES-PAGINATION') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

$old = @'
    def _candles(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        instrument_id = request.one("instrument_id")
        timeframe = request.one("timeframe", "H1")
        if not instrument_id:
            raise ValidationError("پارامتر instrument_id الزامی است.")
        start = parse_ts(request.one("start")) if request.one("start") else None
        end = parse_ts(request.one("end")) if request.one("end") else None
        limit, _ = self._page(request)
        candles = self.platform.candles.range(instrument_id, timeframe, start=start, end=end, limit=None)
        selected = candles[-limit:]
        return self._json(200, {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "count": len(selected),
            "total": len(candles),
            "items": [candle.to_dict() for candle in selected],
        })
'@
$new = @'
    def _candles(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """FIX-12-CANDLES-PAGINATION: پشتیبانی صحیح از limit/offset/source_id.

        * offset از انتهای بازه اعمال می‌شود (کندل‌های جدیدتر اول).
        * source_id اختیاری؛ در صورت نبود، منبع اصلی با priority انتخاب می‌شود.
        * سقف مصرف حافظه: ۵۰۰۰ کندل در هر پاسخ.
        """
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
        # offset از انتهای بازه؛ سپس limit آخرین کندل‌ها
        end_index = max(0, total - offset)
        start_index = max(0, end_index - limit)
        selected = candles[start_index:end_index]
        return self._json(200, {
            "instrument_id": instrument_id,
            "timeframe": timeframe,
            "source_id": source_id,
            "count": len(selected),
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [candle.to_dict() for candle in selected],
        })
'@
if (-not $content.Contains($old)) { throw "_candles anchor not found" }
$content = $content.Replace($old, $new)
$content = $content + "`r`n# FIX-12-CANDLES-PAGINATION`r`n"
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] candles endpoint patched" -ForegroundColor Green