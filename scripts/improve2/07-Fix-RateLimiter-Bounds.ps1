#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'ratelimit-bounds' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $rl = Join-Path $ProjectRoot 'fxars\api\rate_limit.py'
    $text = Read-TextFile -FullPath $rl
    if ($text -match 'FIX-07-MAX-BUCKETS') { Write-Skip "از قبل patch شده"; return }

    $oldInit = @'
class MemoryRateLimiter:
    def __init__(self, limit, window_seconds=60):
        self.limit = limit
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
'@
    $newInit = @'
class MemoryRateLimiter:
    # FIX-07-MAX-BUCKETS
    DEFAULT_MAX_BUCKETS = 10000

    def __init__(self, limit, window_seconds=60, *, max_buckets=None):
        self.limit = limit
        self.window = window_seconds
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_buckets = max_buckets or self.DEFAULT_MAX_BUCKETS
        self._eviction_count = 0
'@
    if (-not $text.Contains($oldInit)) { Write-Err "init anchor پیدا نشد"; return }
    $text = $text.Replace($oldInit, $newInit.TrimEnd())

    $oldAllow = @'
    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True
'@
    $newAllow = @'
    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            # FIX-07-MAX-BUCKETS
            if key not in self._hits and len(self._hits) >= self._max_buckets:
                self._evict_oldest()
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def _evict_oldest(self):
        if not self._hits:
            return
        oldest_key = min(self._hits.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0)[0]
        del self._hits[oldest_key]
        self._eviction_count += 1

    @property
    def eviction_count(self):
        return self._eviction_count
'@
    if (-not $text.Contains($oldAllow)) { Write-Err "allow anchor پیدا نشد"; return }
    $text = $text.Replace($oldAllow, $newAllow.TrimEnd())

    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $rl
    $text = $text.TrimEnd() + "`n`n# FIX-07-MAX-BUCKETS`n"
    Write-TextFile -FullPath $rl -Content $text
    if (Test-PyCompile -FullPath $rl) { Write-Ok "rate_limit.py patch شد" }
    else { Restore-File -FullPath $rl | Out-Null }
    Write-Host "`n===[ DONE: gam 07 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
