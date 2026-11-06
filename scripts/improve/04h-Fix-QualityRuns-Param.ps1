#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\FX')

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)

Write-Host "===[ GAM 04h: Add quality_runs param ]===" -ForegroundColor Cyan

$anPath = Join-Path $ProjectRoot 'fxars\services\analysis.py'
$lines = [System.IO.File]::ReadAllLines($anPath, [System.Text.Encoding]::UTF8)

# پیدا کردن class AnalysisService
$classStart = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^class AnalysisService') { $classStart = $i; break }
}
if ($classStart -lt 0) { Write-Host "[FAIL] class not found" -ForegroundColor Red; return }

$initStart = -1
for ($i = $classStart; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^    def __init__\(') { $initStart = $i; break }
}
if ($initStart -lt 0) { Write-Host "[FAIL] __init__ not found" -ForegroundColor Red; return }

$parenEnd = -1
for ($i = $initStart; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^    \) -> None:') { $parenEnd = $i; break }
}
if ($parenEnd -lt 0) { Write-Host "[FAIL] ') -> None:' not found" -ForegroundColor Red; return }

Write-Host "  __init__: lines $($initStart+1)..$($parenEnd+1)"

$paramExists = $false
for ($i = $initStart; $i -lt $parenEnd; $i++) {
    if ($lines[$i] -match 'quality_runs:') { $paramExists = $true; break }
}

if ($paramExists) {
    Write-Host "  [SKIP A] param already exists" -ForegroundColor DarkGray
} else {
    if ($lines[$parenEnd - 1] -notmatch ',\s*$') {
        $lines[$parenEnd - 1] = $lines[$parenEnd - 1] + ','
    }
    $newLines = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -le $parenEnd; $i++) {
        if ($i -eq $parenEnd) {
            $newLines.Add('        quality_runs: DataQualityRepository,')
        }
        $newLines.Add($lines[$i])
    }
    for ($i = $parenEnd + 1; $i -lt $lines.Count; $i++) {
        $newLines.Add($lines[$i])
    }
    $lines = $newLines.ToArray()
    Write-Host "  [PATCH A] quality_runs param inserted" -ForegroundColor Green
}

$fullText = $lines -join "`r`n"
if ($fullText -match 'DataQualityRepository') {
    Write-Host "  [SKIP B] DataQualityRepository already imported" -ForegroundColor DarkGray
} else {
    $importStart = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^from fxars\.storage\.repositories import \(') { $importStart = $i; break }
    }
    if ($importStart -ge 0) {
        $newLines = New-Object System.Collections.Generic.List[string]
        $inserted = $false
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $newLines.Add($lines[$i])
            if ($i -gt $importStart -and $lines[$i] -match '^\s+CandleRepository,\s*$' -and -not $inserted) {
                $newLines.Add('    DataQualityRepository,')
                $inserted = $true
            }
        }
        if ($inserted) {
            $lines = $newLines.ToArray()
            Write-Host "  [PATCH B] DataQualityRepository imported" -ForegroundColor Green
        }
    }
}

[System.IO.File]::WriteAllLines($anPath, $lines, $utf8)
Write-Host "  [WROTE] analysis.py" -ForegroundColor Green

$pPath = Join-Path $ProjectRoot 'fxars\platform.py'
$plines = [System.IO.File]::ReadAllLines($pPath, [System.Text.Encoding]::UTF8)
$ptext = $plines -join "`r`n"

if ($ptext -match 'quality_runs=self\.quality_runs') {
    Write-Host "  [SKIP C] Platform already passes" -ForegroundColor DarkGray
} else {
    $anStart = -1
    for ($i = 0; $i -lt $plines.Count; $i++) {
        if ($plines[$i] -match 'self\.analysis = AnalysisService\(') { $anStart = $i; break }
    }
    if ($anStart -ge 0) {
        $anEnd = -1
        for ($i = $anStart + 1; $i -lt $plines.Count; $i++) {
            if ($plines[$i] -match '^\s*\)\s*$') { $anEnd = $i; break }
        }
        if ($anEnd -ge 0) {
            if ($plines[$anEnd - 1] -notmatch ',\s*$') {
                $plines[$anEnd - 1] = $plines[$anEnd - 1] + ','
            }
            $newPLines = New-Object System.Collections.Generic.List[string]
            for ($i = 0; $i -le $anEnd; $i++) {
                if ($i -eq $anEnd) {
                    $newPLines.Add('            quality_runs=self.quality_runs,')
                }
                $newPLines.Add($plines[$i])
            }
            for ($i = $anEnd + 1; $i -lt $plines.Count; $i++) {
                $newPLines.Add($plines[$i])
            }
            [System.IO.File]::WriteAllLines($pPath, $newPLines.ToArray(), $utf8)
            Write-Host "  [PATCH C] Platform passes quality_runs" -ForegroundColor Green
        }
    }
}

Write-Host "--- Syntax ---" -ForegroundColor Yellow
& python -m py_compile $anPath
if ($LASTEXITCODE -ne 0) { throw "analysis.py syntax error" }
Write-Host "  [OK] analysis.py" -ForegroundColor Green
& python -m py_compile $pPath
if ($LASTEXITCODE -ne 0) { throw "platform.py syntax error" }
Write-Host "  [OK] platform.py" -ForegroundColor Green

$fa = [System.IO.File]::ReadAllText($anPath, [System.Text.Encoding]::UTF8)
$fp = [System.IO.File]::ReadAllText($pPath, [System.Text.Encoding]::UTF8)
Write-Host "  analysis param          : $([bool]($fa -match 'quality_runs:\s*DataQualityRepository'))"
Write-Host "  analysis self assignment: $($fa.Contains('self.quality_runs = quality_runs'))"
Write-Host "  analysis import         : $($fa.Contains('DataQualityRepository'))"
Write-Host "  platform pass           : $($fp.Contains('quality_runs=self.quality_runs'))"
Write-Host "===[ DONE: gam 04h ]===" -ForegroundColor Green
