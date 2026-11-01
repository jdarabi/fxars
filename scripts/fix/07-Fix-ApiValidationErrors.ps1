#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\api\server.py'
Write-Host "[FIX-07] API Validation errors" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-07-API-VALIDATION') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

# 7.1 catch ValueError ⇒ ValidationError
$old = @'
            try:
                return self._dispatch(request)
            except FxarsError as exc:
                exc.correlation_id = exc.correlation_id or current_correlation_id()
                return self._json(exc.http_status, exc.to_dict())
            except Exception:
                logger.exception("unhandled api error", extra={"data": {"path": request.path}})
                from fxars.core.errors import FxarsError as Base

                error = Base("خطای داخلی سامانه رخ داد.", correlation_id=current_correlation_id())
                return self._json(500, error.to_dict())
'@
$new = @'
            try:
                return self._dispatch(request)
            except FxarsError as exc:
                exc.correlation_id = exc.correlation_id or current_correlation_id()
                return self._json(exc.http_status, exc.to_dict())
            except (ValueError, TypeError, KeyError) as exc:
                # FIX-07-API-VALIDATION: ورودی نامعتبر (timeframe, as_of, enum) ⇒ 400 نه 500
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
'@
if (-not $content.Contains($old)) { throw "handle() anchor not found" }
$content = $content.Replace($old, $new)

# 7.2 اعتبارسنجی صریح timeframe در endpoint تحلیل
$oldAnalyze = @'
    def _analysis_create(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        instrument_id = body.get("instrument_id")
        timeframe = body.get("timeframe", "H1")
        if not instrument_id:
            raise ValidationError("instrument_id الزامی است.")
        as_of = parse_ts(body["as_of"]) if body.get("as_of") else None
'@
$newAnalyze = @'
    def _analysis_create(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        body = request.json()
        instrument_id = body.get("instrument_id")
        timeframe = str(body.get("timeframe", "H1")).upper()
        if not instrument_id:
            raise ValidationError("instrument_id الزامی است.")
        # FIX-07-API-VALIDATION: اعتبارسنجی صریح timeframe پیش از رسیدن به دامنه
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
'@
if (-not $content.Contains($oldAnalyze)) { throw "_analysis_create anchor not found" }
$content = $content.Replace($oldAnalyze, $newAnalyze)

# 7.3 اعتبارسنجی segment در backtest_create
$oldBt = @'
        segment = BacktestSegment(str(body.get("segment", "ALL")).upper())
'@
$newBt = @'
        try:
            segment = BacktestSegment(str(body.get("segment", "ALL")).upper())
        except ValueError:
            raise ValidationError(
                f"segment نامعتبر است: {body.get('segment')!r}",
                details={"allowed": [s.value for s in BacktestSegment]},
            ) from None
'@
if (-not $content.Contains($oldBt)) { throw "backtest segment anchor not found" }
$content = $content.Replace($oldBt, $newBt)

$content = $content + "`r`n# FIX-07-API-VALIDATION`r`n"
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] api/server.py patched (400 for invalid input)" -ForegroundColor Green