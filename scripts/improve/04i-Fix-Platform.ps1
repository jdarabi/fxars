#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\FX')

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)

Write-Host "===[ GAM 04i: Platform quality_runs ]===" -ForegroundColor Cyan

$pPath = Join-Path $ProjectRoot 'fxars\platform.py'
$lines = [System.IO.File]::ReadAllLines($pPath, [System.Text.Encoding]::UTF8)

# پیدا کردن "self.analysis = AnalysisService("
$anStart = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'self\.analysis = AnalysisService\(') {
        $anStart = $i
        break
    }
}
if ($anStart -lt 0) { Write-Host "  [FAIL] AnalysisService( not found" -ForegroundColor Red; return }
Write-Host "  AnalysisService( at line $($anStart+1)"

# پیدا کردن خط بستن ")": اولین خط بعدی که فقط "        )" است
$anEnd = -1
for ($i = $anStart + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*\)\s*$') {
        $anEnd = $i
        break
    }
}
if ($anEnd -lt 0) { Write-Host "  [FAIL] close paren not found" -ForegroundColor Red; return }
Write-Host "  closing ) at line $($anEnd+1)"

# چک اگر قبلاً هست
$alreadyHas = $false
for ($i = $anStart; $i -lt $anEnd; $i++) {
    if ($lines[$i] -match 'quality_runs=self\.quality_runs') {
        $alreadyHas = $true
        break
    }
}

if ($alreadyHas) {
    Write-Host "  [SKIP] already passed" -ForegroundColor DarkGray
} else {
    # چک خط قبل از ) کاما دارد؟
    if ($lines[$anEnd - 1] -notmatch ',\s*$') {
        Write-Host "  [FIX] adding trailing comma to line $($anEnd)" -ForegroundColor DarkGray
        $lines[$anEnd - 1] = $lines[$anEnd - 1] + ','
    }

    # درج کیفیت قبل از خط )
    $newLines = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($i -eq $anEnd) {
            $newLines.Add('            quality_runs=self.quality_runs,')
        }
        $newLines.Add($lines[$i])
    }
    [System.IO.File]::WriteAllLines($pPath, $newLines.ToArray(), $utf8)
    Write-Host "  [PATCH] quality_runs added at line $($anEnd+1)" -ForegroundColor Green
}

Write-Host "--- Syntax ---" -ForegroundColor Yellow
& python -m py_compile $pPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [FAIL] syntax error" -ForegroundColor Red
    throw "platform.py syntax error"
}
Write-Host "  [OK] platform.py compiles" -ForegroundColor Green

$fp = [System.IO.File]::ReadAllText($pPath, [System.Text.Encoding]::UTF8)
Write-Host "  platform pass quality_runs : $($fp.Contains('quality_runs=self.quality_runs'))"
Write-Host "===[ DONE: gam 04i ]===" -ForegroundColor Green
