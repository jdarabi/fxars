#Requires -Version 7.0
<#
.SYNOPSIS
    گام 2 (نسخه 3): اصلاح Rate Limit با anchorهای کوچک و امن.
.DESCRIPTION
    فقط دو تغییر کوچک:
      1) جایگزینی دو خط در _dispatch:
             key = self._rate_key(request)
             if not self.limiter.allow(key):
         با منطق IP + user bucket.
      2) حذف کامل متد _rate_key (چون دیگر استفاده نمی‌شود).
    و یک اضافه:
      3) متد hits_for/snapshot در RateLimiter (اگر نبود).
      4) endpoint debug/rate-status (اختیاری، فقط dev).
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\FX',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$serverPath = Join-Path $ProjectRoot 'fxars\api\server.py'
if (-not (Test-Path $serverPath)) { throw "server.py not found: $serverPath" }

$utf8 = New-Object System.Text.UTF8Encoding($false)
$text = [System.IO.File]::ReadAllText($serverPath, [System.Text.Encoding]::UTF8)

Write-Host "`n===[ GAM 02-v3: Rate Limit Fix ]===" -ForegroundColor Cyan

if ($text -match 'FIX-08-RATE-LIMIT') {
    Write-Host "  [--] Already patched (FIX-08 marker present)." -ForegroundColor Yellow
    return
}

# ===========================================================================
# 1) _dispatch: تبدیل به IP + user bucket
# ===========================================================================
# anchor دقیق: دو خطی که در فایل شما هست
$oldDispatchPair = @'
            key = self._rate_key(request)
            if not self.limiter.allow(key):
                raise RateLimitedError()
'@
$newDispatchPair = @'
            # FIX-08-RATE-LIMIT: قبل از auth با IP، بعد از auth با user_id
            ip_key = f"ip:{request.ip or 'unknown'}"
            if not self.limiter.allow(ip_key):
                raise RateLimitedError()
'@
if (-not $text.Contains($oldDispatchPair)) {
    Write-Host "  [!!] _dispatch pair anchor not found" -ForegroundColor Red
    Write-Host "  Aborting. No changes were written." -ForegroundColor Red
    return
}
$text = $text.Replace($oldDispatchPair, $newDispatchPair)
Write-Host "  [OK] _dispatch now uses IP bucket" -ForegroundColor Green

# حالا بعد از authenticate، user bucket را اضافه کن
$oldAuthBlock = @'
            user = None
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
'@
$newAuthBlock = @'
            user = None
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
                # FIX-08-RATE-LIMIT: Bucket اختصاصی هر کاربر
                user_key = f"user:{user.user_id}"
                if not self.limiter.allow(user_key):
                    raise RateLimitedError()
'@
if (-not $text.Contains($oldAuthBlock)) {
    Write-Host "  [!!] auth block anchor not found" -ForegroundColor Red
    Write-Host "  Aborting. No changes were written." -ForegroundColor Red
    return
}
$text = $text.Replace($oldAuthBlock, $newAuthBlock)
Write-Host "  [OK] _dispatch now adds user bucket after auth" -ForegroundColor Green

# ===========================================================================
# 2) حذف متد _rate_key
# ===========================================================================
$oldRateKey = @'
    def _rate_key(self, request: ApiRequest) -> str:
        header = request.headers.get("authorization", "")
        return header[7:][:24] if header else request.ip
'@
$newRateKey = @'
    # FIX-08-RATE-LIMIT: _rate_key حذف شد؛ کلیدها در _dispatch ساخته می‌شوند.
'@
if ($text.Contains($oldRateKey)) {
    $text = $text.Replace($oldRateKey, $newRateKey)
    Write-Host "  [OK] _rate_key method removed" -ForegroundColor Green
} else {
    Write-Host "  [!] _rate_key pattern not found — check manually" -ForegroundColor Yellow
}

# ===========================================================================
# 3) hits_for + snapshot به RateLimiter (اگر نبود)
# ===========================================================================
$needsHitsFor = -not ($text -match 'def hits_for')
$needsSnapshot = -not ($text -match 'def snapshot')

if ($needsHitsFor -or $needsSnapshot) {
    # anchor: خط "return True" که بعد از bucket.append(now) می‌آید
    # در فایل شما این دو خط در RateLimiter.allow هستند
    $anchor = @'
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True
'@
    $addition = @'
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def hits_for(self, key: str) -> int:
        """FIX-08-RATE-LIMIT: تعداد Hits معتبر فعلی یک کلید در پنجره."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                return 0
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            return len(bucket)

    def snapshot(self) -> dict[str, int]:
        """FIX-08-RATE-LIMIT: عکس فوری از همه Bucketهای غیرخالی."""
        now = time.monotonic()
        with self._lock:
            result: dict[str, int] = {}
            for key, bucket in list(self._hits.items()):
                while bucket and now - bucket[0] > self.window:
                    bucket.popleft()
                if bucket:
                    result[key] = len(bucket)
            return result
'@
    if ($text.Contains($anchor)) {
        $text = $text.Replace($anchor, $addition)
        Write-Host "  [OK] RateLimiter: hits_for + snapshot added" -ForegroundColor Green
    } else {
        Write-Host "  [!] RateLimiter.allow anchor not found — hits_for/snapshot not added" -ForegroundColor Yellow
        Write-Host "      (این دو متد فقط برای تست/dev هستند و مانع اجرا نیستند)" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  [--] RateLimiter already has hits_for + snapshot" -ForegroundColor DarkGray
}

# ===========================================================================
# 4) endpoint debug/rate-status (فقط dev)
# ===========================================================================
if ($text -notmatch '/debug/rate-status') {
    $oldRoute = '        add("GET", r"^/api/v1/health$", self._health, public=True)'
    $newRoute = @'
        add("GET", r"^/api/v1/health$", self._health, public=True)
        add("GET", r"^/api/v1/debug/rate-status$", self._rate_status, public=True)
'@
    if ($text.Contains($oldRoute)) {
        $text = $text.Replace($oldRoute, $newRoute)
        Write-Host "  [OK] route /api/v1/debug/rate-status registered" -ForegroundColor Green
    } else {
        Write-Host "  [!] health route anchor not found" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [--] debug route already registered" -ForegroundColor DarkGray
}

# handler _rate_status قبل از _login
if ($text -notmatch 'def _rate_status') {
    $oldLogin = '    def _login(self, request: ApiRequest, params: dict, user) -> ApiResponse:'
    $handler = @'
    def _rate_status(self, request: ApiRequest, params: dict, user) -> ApiResponse:
        """FIX-08-RATE-LIMIT: وضعیت Rate Limit (فقط dev + localhost)."""
        if self.settings.environment != "dev":
            raise NotFoundError("مسیر درخواستی یافت نشد.", details={"path": request.path})
        if request.ip not in ("127.0.0.1", "::1", ""):
            raise NotFoundError("مسیر درخواستی یافت نشد.", details={"path": request.path})
        return self._json(200, {
            "limit_per_minute": self.limiter.limit,
            "window_seconds": self.limiter.window,
            "buckets": self.limiter.snapshot(),
        })

    def _login(self, request: ApiRequest, params: dict, user) -> ApiResponse:
'@
    if ($text.Contains($oldLogin)) {
        $text = $text.Replace($oldLogin, $handler)
        Write-Host "  [OK] _rate_status handler added" -ForegroundColor Green
    } else {
        Write-Host "  [!] _login anchor not found — handler not added" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [--] _rate_status already exists" -ForegroundColor DarkGray
}

# ===========================================================================
# ذخیره
# ===========================================================================
if ($DryRun) {
    Write-Host "`n[DryRun] No file written." -ForegroundColor Yellow
    return
}

$text = $text + "`r`n# FIX-08-RATE-LIMIT`r`n"
[System.IO.File]::WriteAllText($serverPath, $text, $utf8)
Write-Host "`n  [WROTE] $serverPath" -ForegroundColor Green

# ===========================================================================
# Syntax check
# ===========================================================================
Write-Host "`n--- Syntax check ---" -ForegroundColor Yellow
& python -m py_compile $serverPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [FAIL] syntax error" -ForegroundColor Red
    Write-Host "  Restore from backup:" -ForegroundColor Yellow
    Write-Host "    Copy-Item 'C:\FX\.fix-backups\improve-14050812-170631\fxars\api\server.py' 'C:\FX\fxars\api\server.py' -Force" -ForegroundColor Yellow
    throw "syntax error"
}
Write-Host "  [OK] server.py compiles" -ForegroundColor Green

# ===========================================================================
# Verify
# ===========================================================================
Write-Host "`n--- Verify ---" -ForegroundColor Yellow
$final = [System.IO.File]::ReadAllText($serverPath, [System.Text.Encoding]::UTF8)
Write-Host ("  FIX-08 marker           : {0}" -f ($final -match 'FIX-08-RATE-LIMIT'))
Write-Host ("  hits_for method         : {0}" -f ($final -match 'def hits_for'))
Write-Host ("  snapshot method         : {0}" -f ($final -match 'def snapshot'))
Write-Host ("  _rate_key method (old)  : {0}   (باید False باشد)" -f ($final -match 'def _rate_key'))
Write-Host ("  debug/rate-status route : {0}" -f ($final -match '/debug/rate-status'))
Write-Host ("  rate_status handler     : {0}" -f ($final -match 'def _rate_status'))
Write-Host ("  ip bucket              : {0}" -f ($final -match 'ip:\{request\.ip'))
Write-Host ("  user bucket            : {0}" -f ($final -match 'user:\{user\.user_id'))

Write-Host "`n===[ DONE: gam 02-v3 ]===" -ForegroundColor Green
Write-Host "`nNext: pwsh -File .\scripts\improve\02b-Test-RateLimit.ps1" -ForegroundColor Cyan
