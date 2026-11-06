#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot='C:\project\FX',[switch]$DryRun)
$ErrorActionPreference='Stop'
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$archive=Join-Path $ProjectRoot "scripts\archive\$stamp"
$logs=Join-Path $ProjectRoot "scripts\archive\logs-$stamp"
if(-not $DryRun){ New-Item -ItemType Directory -Path $archive -Force | Out-Null; New-Item -ItemType Directory -Path $logs -Force | Out-Null }
$n=0
foreach($pat in @('add_*.py','fix_*.py','install_*.py','check_*.py','debug_*.py','seed_*.py','apply-*.ps1','test_mt5.py','test_analysis_mt5.py','FXARS-Start.ps1','live.local.ps1','get_chat_id.py','.consult-job-id','.consult-process-id')){
  Get-ChildItem -Path $ProjectRoot -File -Filter $pat -ErrorAction SilentlyContinue | ForEach-Object {
    if(-not $DryRun){ Move-Item $_.FullName (Join-Path $archive $_.Name) -Force; Write-Host "moved: $($_.Name)" -ForegroundColor Green }
    $script:n++
  }
}
Get-ChildItem -Path $ProjectRoot -File -Filter '*.log' -ErrorAction SilentlyContinue | ForEach-Object {
  if(-not $DryRun){ Move-Item $_.FullName (Join-Path $logs $_.Name) -Force; Write-Host "moved-log: $($_.Name)" -ForegroundColor Green }
  $script:n++
}
Write-Host "Total moved: $n" -ForegroundColor Green
