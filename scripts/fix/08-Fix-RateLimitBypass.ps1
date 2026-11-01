#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\api\server.py'
Write-Host "[FIX-08] Rate limit bypass" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-08-RATE-LIMIT') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

# 8.1 کلید Rate Limit: ابتدا IP، بعد از احراز هویت user_id
$old = @'
            if method != request.method:
                continue
            key = self._rate_key(request)
            if not self.limiter.allow(key):
                raise RateLimitedError()
            user = None
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
'@
$new = @'
            if method != request.method:
                continue
            # FIX-08-RATE-LIMIT: قبل از احراز هویت با IP محدود می‌کنیم تا توکن جعلی
            # نتواند Bucket جدید بسازد. بعد از احراز هویت کلید به user_id تغییر می‌کند.
            ip_key = f"ip:{request.ip or 'unknown'}"
            if not self.limiter.allow(ip_key):
                raise RateLimitedError()
            user = None
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
                user_key = f"user:{user.user_id}"
                if not self.limiter.allow(user_key):
                    raise RateLimitedError()
'@
if (-not $content.Contains($old)) { throw "dispatch rate anchor not found" }
$content = $content.Replace($old, $new)

# 8.2 حذف _rate_key (دیگر لازم نیست)
if ($content -match 'def _rate_key') {
    $oldKey = @'
    def _rate_key(self, request: ApiRequest) -> str:
        header = request.headers.get("authorization", "")
        return header[7:][:24] if header else request.ip
'@
    $newKey = @'
    # FIX-08-RATE-LIMIT: _rate_key حذف شد؛ کلید در _dispatch ساخته می‌شود.
'@
    if ($content.Contains($oldKey)) {
        $content = $content.Replace($oldKey, $newKey)
    }
}

$content = $content + "`r`n# FIX-08-RATE-LIMIT`r`n"
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] rate limit patched (IP + user buckets)" -ForegroundColor Green