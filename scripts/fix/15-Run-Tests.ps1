#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$PythonExe = "python",
    [switch]$SkipAcceptance
)

$ErrorActionPreference = 'Continue'
Push-Location $ProjectRoot

try {
    Write-Host "`n[TEST] Running full suite..." -ForegroundColor Cyan
    & $PythonExe -m unittest discover -s tests -v
    $suiteCode = $LASTEXITCODE

    if (-not $SkipAcceptance) {
        Write-Host "`n[TEST] Running acceptance suite..." -ForegroundColor Cyan
        & $PythonExe -m unittest tests.test_acceptance -v
        $acCode = $LASTEXITCODE
    } else {
        $acCode = 0
    }

    Write-Host "`n[TEST] Running new fix regression suite..." -ForegroundColor Cyan
    & $PythonExe -m unittest tests.test_fixes -v
    $fixCode = $LASTEXITCODE

    Write-Host "`n=========================" -ForegroundColor Yellow
    Write-Host " Full suite      : $suiteCode" -ForegroundColor $(if ($suiteCode -eq 0) { 'Green' } else { 'Red' })
    Write-Host " Acceptance suite: $acCode" -ForegroundColor $(if ($acCode -eq 0) { 'Green' } else { 'Red' })
    Write-Host " Fix regressions : $fixCode" -ForegroundColor $(if ($fixCode -eq 0) { 'Green' } else { 'Red' })
    Write-Host "=========================" -ForegroundColor Yellow

    exit ($suiteCode + $acCode + $fixCode)
}
finally {
    Pop-Location
}