#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Push-Location $ProjectRoot
    try {
        Write-Host "`n===[ gam 18: تست کامل ]===" -ForegroundColor Cyan
        Write-Host "cwd: $(Get-Location)"
        Write-Host "`n--- discover ---" -ForegroundColor Yellow
        & python -B -m unittest discover -s tests -v
        $code = $LASTEXITCODE
        Write-Host "`nexit code: $code" -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Red' })
        if ($code -eq 0) { Write-Ok "همه تست‌ها موفق" } else { Write-Err "تست‌ها شکست خوردند" }
        return $code
    } finally { Pop-Location }
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
