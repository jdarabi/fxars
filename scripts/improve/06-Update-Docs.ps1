#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot='C:\project\FX',[switch]$DryRun,[switch]$SkipTests)
$ErrorActionPreference='Stop'
$testCount=$null
if(-not $SkipTests){
  Push-Location $ProjectRoot
  try {
    $out = & python -B -m unittest discover -s tests 2>&1 | Out-String
    if($out -match 'Ran\s+(\d+)\s+tests'){ $testCount=[int]$Matches[1]; Write-Host "Ran $testCount tests" -ForegroundColor Green }
    if($out -match 'FAILED'){ Write-Host "TESTS FAILED" -ForegroundColor Red }
  } finally { Pop-Location }
}
if($null -ne $testCount){
  foreach($f in @('README.md','docs\PHASES.md','docs\IMPLEMENTATION_REPORT.md')){
    $full=Join-Path $ProjectRoot $f
    if(-not (Test-Path $full)){ continue }
    $t=Get-Content $full -Raw -Encoding UTF8
    $orig=$t
    $t=$t -replace '\*\*363\s+تست\*\*',"**$testCount تست**"
    $t=$t -replace '\*\*۳۶۳\s+تست\*\*',"**$testCount تست**"
    $t=$t -replace '\(338 تست\)',"($testCount تست)"
    $t=$t -replace '\(۳۳۸ تست\)',"($testCount تست)"
    if($t -ne $orig){
      if(-not $DryRun){ Set-Content -Path $full -Value $t -Encoding UTF8 -NoNewline }
      Write-Host "updated: $f" -ForegroundColor Green
    }
  }
}
$settings=Join-Path $ProjectRoot 'config\settings.json'
if(Test-Path $settings){
  $s=Get-Content $settings -Raw -Encoding UTF8
  if($s -match '"phase"\s*:\s*"DEMO"'){
    if(-not $DryRun){ $s=$s -replace '"phase"\s*:\s*"DEMO"','"phase": "READ_ONLY"'; Set-Content -Path $settings -Value $s -Encoding UTF8 -NoNewline }
    Write-Host "settings.json: DEMO -> READ_ONLY" -ForegroundColor Green
  }
}
Write-Host "DONE" -ForegroundColor Cyan
