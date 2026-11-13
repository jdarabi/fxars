#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$ProjectRoot = 'C:\project\FX',
    [switch]$DryRun,
    [switch]$NoPause
)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'phase-readonly' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $settings = Join-Path $ProjectRoot 'config\settings.json'
    if (-not (Test-Path -LiteralPath $settings)) { Write-Err "settings.json پیدا نشد"; return }
    $text = Get-Content $settings -Raw -Encoding UTF8
    if ($text -match '"phase"\s*:\s*"READ_ONLY"') { Write-Skip "phase از قبل READ_ONLY"; return }
    if ($text -notmatch '"phase"\s*:\s*"[^"]+"') { Write-Err "phase پیدا نشد"; return }
    $newText = $text -replace '"phase"\s*:\s*"[^"]+"', '"phase": "READ_ONLY"'
    if ($DryRun) { Write-Warn2 "DRY-RUN: phase → READ_ONLY"; return }
    Backup-File -FullPath $settings
    Set-Content -Path $settings -Value $newText -Encoding UTF8 -NoNewline
    try { Get-Content $settings -Raw | ConvertFrom-Json | Out-Null; Write-Ok "phase → READ_ONLY" }
    catch { Write-Err "JSON نامعتبر: $_"; Restore-File -FullPath $settings | Out-Null; return }
    Write-Host "`n===[ DONE: gam 02 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
