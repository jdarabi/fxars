#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\FX')

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)

Write-Host "===[ GAM 04c: Validation.py Fix ]===" -ForegroundColor Cyan

$valPath = Join-Path $ProjectRoot 'fxars\data\validation.py'
$lines = [System.IO.File]::ReadAllLines($valPath, [System.Text.Encoding]::UTF8)

$triggerIdx = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\s*if candle\.is_closed and candle\.available_at < candle\.close_time:\s*$') {
        $triggerIdx += $i
    }
}

$triggerLineNumbers = ($triggerIdx | ForEach-Object { $_ + 1 }) -join ', '
Write-Host "  Found $($triggerIdx.Count) trigger line(s) at: $triggerLineNumbers"

if ($triggerIdx.Count -eq 0) {
    Write-Host "  [FAIL] No trigger line found" -ForegroundColor Red
    return
}

$blocksToRemove = @()
foreach ($idx in $triggerIdx) {
    $n1 = $idx + 1
    $n2 = $idx + 2
    if ($n1 -lt $lines.Count -and $n2 -lt $lines.Count) {
        if ($lines[$n1] -match '^\s*(soft|hard)\.append\("available_at_before_close"\)\s*$') {
            if ($lines[$n2] -match '^\s*reasons\.append\(') {
                $blocksToRemove += [PSCustomObject]@{ Start = $idx; End = $n2 }
            }
        }
    }
}

Write-Host "  Will remove $($blocksToRemove.Count) complete block(s)"

$replacement = @(
    '        # FIX-P0-SUSPECT-HARD: اگر is_closed=true ولی available_at قبل از close_time است،',
    '        # یعنی داده قبل از بسته‌شدن کندل در دسترس بوده → Look-ahead → INVALID',
    '        if candle.is_closed and candle.available_at < candle.close_time:',
    '            hard.append("available_at_before_close")',
    '            reasons.append("کندل به‌عنوان بسته اعلام شده ولی available_at قبل از close_time است (Look-ahead).")'
)

$newLines = New-Object System.Collections.Generic.List[string]
$insertedHard = $false
$current = 0

foreach ($block in ($blocksToRemove | Sort-Object Start)) {
    while ($current -lt $block.Start) {
        $newLines.Add($lines[$current])
        $current++
    }
    if (-not $insertedHard) {
        foreach ($r in $replacement) {
            $newLines.Add($r)
        }
        $insertedHard = $true
    }
    $current = $block.End + 1
}

while ($current -lt $lines.Count) {
    $newLines.Add($lines[$current])
    $current++
}

[System.IO.File]::WriteAllLines($valPath, $newLines, $utf8)
Write-Host "  [PATCH] $($blocksToRemove.Count) block(s) replaced with 1 clean hard block" -ForegroundColor Green

Write-Host "--- Syntax check ---" -ForegroundColor Yellow
& python -m py_compile $valPath
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [FAIL] syntax error" -ForegroundColor Red
    $final = [System.IO.File]::ReadAllLines($valPath, [System.Text.Encoding]::UTF8)
    $start = [Math]::Max(0, $final.Count - 100)
    for ($j = $start; $j -lt $final.Count; $j++) {
        Write-Host ("    {0,4}: {1}" -f ($j+1), $final[$j])
    }
    throw "syntax error"
}
Write-Host "  [OK] validation.py compiles" -ForegroundColor Green

$ft = [System.IO.File]::ReadAllText($valPath, [System.Text.Encoding]::UTF8)
$hc = ([regex]::Matches($ft, 'hard\.append\("available_at_before_close"\)')).Count
$sc = ([regex]::Matches($ft, 'soft\.append\("available_at_before_close"\)')).Count
Write-Host "  hard blocks (must be 1): $hc"
Write-Host "  soft blocks (must be 0): $sc"
Write-Host "===[ DONE: gam 04c ]===" -ForegroundColor Green
