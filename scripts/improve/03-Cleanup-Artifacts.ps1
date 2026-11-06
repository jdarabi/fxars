#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot='C:\project\FX',[switch]$DryRun)
$ErrorActionPreference='Stop'
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $ProjectRoot ".fix-backups\cleanup-artifacts-$stamp"
if(-not $DryRun){ New-Item -ItemType Directory -Path $backup -Force | Out-Null }
$skipDirs=@('.git','.fix-backups','.cleanup-backups')
function Test-Skip($p){ foreach($d in $script:skipDirs){ if($p -match [regex]::Escape("\$d\")){ return $true } }; return $false }
$count=0
foreach($pat in @('*.pre-fix-*','*.bak','*.orig')){
  Get-ChildItem -Path $ProjectRoot -Recurse -File -Filter $pat -ErrorAction SilentlyContinue | Where-Object { -not (Test-Skip $_.FullName) } | ForEach-Object {
    if(-not $DryRun){ Copy-Item $_.FullName (Join-Path $backup $_.Name) -Force -ErrorAction SilentlyContinue; Remove-Item $_.FullName -Force }
    $script:count++
  }
}
Get-ChildItem -Path $ProjectRoot -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Where-Object { -not (Test-Skip $_.FullName) } | ForEach-Object {
  if(-not $DryRun){ Remove-Item $_.FullName -Recurse -Force }
  $script:count++
}
foreach($d in @('.hypothesis','.pytest_cache','.mypy_cache','.ruff_cache','.tox','build','dist')){
  $f=Join-Path $ProjectRoot $d
  if(Test-Path $f){ if(-not $DryRun){ Remove-Item $f -Recurse -Force }; $script:count++ }
}
$reports=Join-Path $ProjectRoot 'reports'
if(Test-Path $reports){
  Get-ChildItem -Path $reports -Recurse -File -Include '*.html','*.md' -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne '.gitkeep' } | ForEach-Object {
    if(-not $DryRun){ Remove-Item $_.FullName -Force }
    $script:count++
  }
}
Write-Host "Removed items: $count" -ForegroundColor Green
