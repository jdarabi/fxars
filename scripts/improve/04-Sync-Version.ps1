#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot='C:\project\FX',[switch]$DryRun)
$ErrorActionPreference='Stop'
$vp=Join-Path $ProjectRoot 'fxars\version.py'
if(-not (Test-Path $vp)){ throw "version.py not found" }
$c=Get-Content $vp -Raw -Encoding UTF8
if($c -notmatch 'CODE_VERSION\s*=\s*"([^"]+)"'){ throw "CODE_VERSION not found" }
$ver=$Matches[1]
Write-Host "Source: $ver" -ForegroundColor Green
$pp=Join-Path $ProjectRoot 'pyproject.toml'
if(Test-Path $pp){
  $t=Get-Content $pp -Raw -Encoding UTF8
  if($t -match '(?m)^version\s*=\s*"([^"]+)"'){
    $old=$Matches[1]
    if($old -ne $ver){
      $new=$t -replace '(?m)^version\s*=\s*"[^"]+"',"version = `"$ver`""
      if(-not $DryRun){ Set-Content -Path $pp -Value $new -Encoding UTF8 -NoNewline }
      Write-Host "  pyproject: $old -> $ver" -ForegroundColor Green
    }
  }
}
