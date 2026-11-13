#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\project\FX',
    [switch]$DryRun,
    [switch]$SkipTests,
    [switch]$NoPause
)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"

try {
    Assert-Pwsh7
    Assert-Python | Out-Null

    $steps = @(
        @{ Name = '01b-Redact-Token-All';      Path = '01b-Redact-Token-All.ps1'; Optional = $true },
        @{ Name = '02-Phase-ReadOnly';         Path = '02-Phase-ReadOnly.ps1' },
        @{ Name = '03-Add-License-Security';   Path = '03-Add-License-Security.ps1' },
        @{ Name = '04-Fix-CLI-Duplicate';      Path = '04-Fix-CLI-Duplicate.ps1' },
        @{ Name = '05-Fix-RiskLimits';         Path = '05-Fix-RiskLimits.ps1' },
        @{ Name = '06-Fix-AccountSnapshot';    Path = '06-Fix-AccountSnapshot.ps1' },
        @{ Name = '07-Fix-RateLimiter-Bounds'; Path = '07-Fix-RateLimiter-Bounds.ps1' },
        @{ Name = '08-Fix-Password-Length';    Path = '08-Fix-Password-Length.ps1' },
        @{ Name = '09-Fix-Intermarket-Return'; Path = '09-Fix-Intermarket-Return.ps1' },
        @{ Name = '10-Fix-Print-To-Logger';    Path = '10-Fix-Print-To-Logger.ps1' },
        @{ Name = '11-Fix-Datetime-UTC';       Path = '11-Fix-Datetime-UTC.ps1' },
        @{ Name = '12-Fix-Precompute-Comment'; Path = '12-Fix-Precompute-Comment.ps1' },
        @{ Name = '13-Fix-FloorToTimeframe-W1';Path = '13-Fix-FloorToTimeframe-W1.ps1' },
        @{ Name = '14-Fix-Pyproject-License';  Path = '14-Fix-Pyproject-License.ps1' },
        @{ Name = '15-Fix-CORS-Default';       Path = '15-Fix-CORS-Default.ps1' }
    )

    $results = @()
    foreach ($step in $steps) {
        $scriptPath = Join-Path $PSScriptRoot $step.Path
        if (-not (Test-Path $scriptPath)) {
            if ($step.Optional) { Write-Skip "$($step.Name) (optional, not found)"; continue }
            Write-Err "$($step.Name): پیدا نشد"
            $results += [PSCustomObject]@{ Step = $step.Name; ExitCode = 'MISSING' }
            continue
        }
        Write-Host "`n" + ("=" * 70) -ForegroundColor DarkGray
        Write-Host ">> $($step.Name)" -ForegroundColor Magenta
        Write-Host ("=" * 70) -ForegroundColor DarkGray

        $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $scriptPath, '-ProjectRoot', $ProjectRoot, '-NoPause')
        if ($DryRun) { $args += '-DryRun' }

        & pwsh @args
        $results += [PSCustomObject]@{ Step = $step.Name; ExitCode = $LASTEXITCODE }
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "$($step.Name) exit $LASTEXITCODE — ادامه می‌دهیم" }
    }

    if (-not $SkipTests) {
        $testsPath = Join-Path $PSScriptRoot '18-Run-All-Tests.ps1'
        if (Test-Path $testsPath) {
            Write-Host "`n>> 18-Run-All-Tests" -ForegroundColor Magenta
            & pwsh -NoProfile -ExecutionPolicy Bypass -File $testsPath -ProjectRoot $ProjectRoot -NoPause
            $results += [PSCustomObject]@{ Step = '18-Run-All-Tests'; ExitCode = $LASTEXITCODE }
        }
    }

    Write-Host "`n`n=== خلاصه ===" -ForegroundColor Cyan
    $results | Format-Table -AutoSize | Out-String | Write-Host
    $failed = $results | Where-Object { $_.ExitCode -ne 0 -and $_.ExitCode -ne 'MISSING' }
    if ($failed.Count -eq 0) { Write-Ok "همه گام‌ها موفق" }
    else { Write-Warn2 "$($failed.Count) گام با خطا" }
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
