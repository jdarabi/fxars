#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\data\quality.py'
if (-not (Test-Path $file)) { throw "Not found: $file" }
Write-Host "[FIX-02] Patching $file" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-02-VERDICT-SEVERITY') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

$oldBlock = @'
        if invalid or stale:
            verdict = "FAIL"
        elif suspect or missing:
            verdict = "WARN"
        else:
            verdict = "PASS"
'@

$newBlock = @'
        # FIX-02-VERDICT-SEVERITY: verdict بر اساس شدت Issueها
        severities = {issue.severity for issue in issues}
        if invalid > 0 or stale or "ERROR" in severities:
            verdict = "FAIL"
        elif suspect > 0 or missing > 0 or "WARN" in severities:
            verdict = "WARN"
        else:
            verdict = "PASS"
'@

if (-not $content.Contains($oldBlock)) {
    throw "Original verdict block not found — file may have changed. Aborting."
}
$content = $content.Replace($oldBlock, $newBlock)
Set-Content -Path $file -Value $content -Encoding UTF8 -NoNewline
Write-Host "  [OK] quality.py patched (severity-based verdict)" -ForegroundColor Green