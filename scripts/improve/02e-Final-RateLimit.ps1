#Requires -Version 7.0
<#
.SYNOPSIS
    گام 2e: نهایی‌سازی FIX-08 با anchorهای دقیق از دیاگنوز.
.DESCRIPTION
    چهار patch مستقل:
      A) RateLimiter: افزودن hits_for + snapshot
      B) _dispatch: IP bucket قبل از auth، user bucket بعد از auth، حذف _rate_key
      C) حذف متد _rate_key
      D) پاک‌سازی/نگه‌داشتن marker در انتها
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\FX'
)

$ErrorActionPreference = 'Stop'
$serverPath = Join-Path $ProjectRoot 'fxars\api\server.py'
$utf8 = New-Object System.Text.UTF8Encoding($false)

$text = [System.IO.File]::ReadAllText($serverPath, [System.Text.Encoding]::UTF8)
Write-Host "`n===[ GAM 02e: Final Rate Limit Fix ]===" -ForegroundColor Cyan

# شناسه‌های هر patch برای گزارش
$applied = @()

# =====================================================================
# A) RateLimiter: hits_for + snapshot
# =====================================================================
if ($text -match 'def hits_for' -and $text -match 'def snapshot') {
    Write-Host "  [SKIP A] hits_for/snapshot already present" -ForegroundColor DarkGray
} else {
    # Anchor دقیق: خطوط ۹۴-۹۷ از دیاگنوز
    $anchorA = @'
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True
'@
    $newA = @'
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def hits_for(self, key: str) -> int:
        """FIX-08: تعداد Hits معتبر فعلی یک کلید در پنجره."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                return 0
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            return len(bucket)

    def snapshot(self) -> dict[str, int]:
        """FIX-08: عکس فوری از Bucketهای غیرخالی."""
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
    if ($text.Contains($anchorA)) {
        $text = $text.Replace($anchorA, $newA)
        Write-Host "  [PATCH A] RateLimiter: hits_for + snapshot ✅" -ForegroundColor Green
        $applied += 'A'
    } else {
        Write-Host "  [FAIL A] RateLimiter.allow anchor still not matching" -ForegroundColor Red
        Write-Host "  File will NOT be written. Send this context:" -ForegroundColor Yellow
        $lines = $text -split "`r?`n", 0
        for ($i = 87; $i -lt 100 -and $i -lt $lines.Count; $i++) {
            Write-Host ("    {0,4}: {1}" -f ($i+1), $lines[$i])
        }
        return
    }
}

# =====================================================================
# B) _dispatch: IP + user bucket
# =====================================================================
# Anchor دقیق: 5 خط از ۱۸۹-۱۹۶
$anchorB1 = @'
            key = self._rate_key(request)
            if not self.limiter.allow(key):
                raise RateLimitedError()
'@
$newB1 = @'
            # FIX-08: Rate limit قبل از auth با IP
            ip_key = f"ip:{request.ip or 'unknown'}"
            if not self.limiter.allow(ip_key):
                raise RateLimitedError()
'@
if ($text.Contains($anchorB1)) {
    $text = $text.Replace($anchorB1, $newB1)
    Write-Host "  [PATCH B1] _dispatch: IP bucket ✅" -ForegroundColor Green
    $applied += 'B1'
} elseif ($text -match 'ip:\{request') {
    Write-Host "  [SKIP B1] IP bucket already applied" -ForegroundColor DarkGray
} else {
    Write-Host "  [FAIL B1] _rate_key usage anchor not found" -ForegroundColor Red
    $lines = $text -split "`r?`n", 0
    for ($i = 185; $i -lt 200 -and $i -lt $lines.Count; $i++) {
        Write-Host ("    {0,4}: {1}" -f ($i+1), $lines[$i])
    }
    return
}

# B2: user bucket بعد از authenticate
$anchorB2 = @'
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
'@
$newB2 = @'
            if not public:
                user = self._authenticate(request)
                if permission is not None:
                    require_permission(user.role, permission)
                # FIX-08: Rate limit بعد از auth با user_id
                user_key = f"user:{user.user_id}"
                if not self.limiter.allow(user_key):
                    raise RateLimitedError()
'@
if ($text.Contains($anchorB2)) {
    $text = $text.Replace($anchorB2, $newB2)
    Write-Host "  [PATCH B2] _dispatch: user bucket ✅" -ForegroundColor Green
    $applied += 'B2'
} elseif ($text -match 'user:\{user') {
    Write-Host "  [SKIP B2] user bucket already applied" -ForegroundColor DarkGray
} else {
    Write-Host "  [FAIL B2] auth block anchor not found" -ForegroundColor Red
    $lines = $text -split "`r?`n", 0
    for ($i = 190; $i -lt 200 -and $i -lt $lines.Count; $i++) {
        Write-Host ("    {0,4}: {1}" -f ($i+1), $lines[$i])
    }
    return
}

# =====================================================================
# C) حذف متد _rate_key
# =====================================================================
$anchorC = @'
    def _rate_key(self, request: ApiRequest) -> str:
        header = request.headers.get("authorization", "")
        return header[7:][:24] if header else request.ip
'@
$newC = '    # FIX-08: _rate_key حذف شد؛ کلیدها در _dispatch ساخته می‌شوند.'
if ($text.Contains($anchorC)) {
    $text = $text.Replace($anchorC, $newC)
    Write-Host "  [PATCH C] _rate_key removed ✅" -ForegroundColor Green
    $applied += 'C'
} elseif ($text -notmatch 'def _rate_key') {
    Write-Host "  [SKIP C] _rate_key already absent" -ForegroundColor DarkGray
} else {
    Write-Host "  [WARN C] _rate_key exists but not exactly as expected" -ForegroundColor Yellow
    Write-Host "           Trying regex removal..." -ForegroundColor Yellow
    $newText = $text -replace "(?ms)^    def _rate_key\(self, request: ApiRequest\) -> str:\r?\n(?:        .*\r?\n)+", $newC + "`r`n"
    if ($newText -ne $text) {
        $text = $newText
        Write-Host "  [PATCH C-regex] _rate_key removed via regex ✅" -ForegroundColor Green
        $applied += 'C'
    }
}

# =====================================================================
# ذخیره
# =====================================================================
if ($applied.Count -eq 0) {
    Write-Host "`n[!] No changes applied. File not written." -ForegroundColor Yellow
    return
}

[System.IO.File]::WriteAllText($serverPath, $text, $utf8)
Write-Host "`n  [WROTE] $serverPath" -ForegroundColor Green
Write-Host "  Applied: $($applied -join ', ')" -ForegroundColor Green

# =====================================================================
# Syntax check
# =====================================================================
Write-Host "`n--- Syntax check ---" -ForegroundColor Yellow
& python -m py_compile $serverPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [FAIL] syntax error" -ForegroundColor Red
    Write-Host "  Restore: Copy-Item 'C:\FX\.fix-backups\improve-14050812-170631\fxars\api\server.py' 'C:\FX\fxars\api\server.py' -Force" -ForegroundColor Yellow
    throw "syntax error"
}
Write-Host "  [OK] server.py compiles" -ForegroundColor Green

# =====================================================================
# Verify
# =====================================================================
Write-Host "`n--- Verify ---" -ForegroundColor Yellow
$final = [System.IO.File]::ReadAllText($serverPath, [System.Text.Encoding]::UTF8)
$v = [ordered]@{
    'def hits_for('           = 'def hits_for\('
    'def snapshot('           = 'def snapshot\('
    'def _rate_key('          = 'def _rate_key\('
    'self._rate_key('         = 'self\._rate_key\('
    'ip:\{request'            = 'ip:\{request'
    'user:\{user'             = 'user:\{user'
    'debug/rate-status route' = '/debug/rate-status'
    'def _rate_status'        = 'def _rate_status'
}
$allGood = $true
foreach ($k in $v.Keys) {
    $isTrue = [bool]($final -match $v[$k])
    $expected = if ($k -like '_rate_key*') { $false } else { $true }
    $ok = ($isTrue -eq $expected)
    if (-not $ok) { $allGood = $false }
    $color = if ($ok) { 'Green' } else { 'Red' }
    Write-Host ("  {0,-26} : {1}   (باید {2})" -f $k, $isTrue, $expected) -ForegroundColor $color
}

if ($allGood) {
    Write-Host "`n===[ DONE: gam 02e — SUCCESS ]===" -ForegroundColor Green
    Write-Host "`nNext: run regression tests:" -ForegroundColor Cyan
    Write-Host "  python -B -m unittest tests.test_security tests.test_api tests.test_http_integration -v" -ForegroundColor Cyan
} else {
    Write-Host "`n===[ PARTIAL: gam 02e ]===" -ForegroundColor Yellow
    Write-Host "Some checks failed — send full output" -ForegroundColor Yellow
}