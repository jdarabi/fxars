#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'pyproject-license' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $pp = Join-Path $ProjectRoot 'pyproject.toml'
    $text = Read-TextFile -FullPath $pp
    if ($text -match 'FIX-14-PEP639') { Write-Skip "از قبل patch شده"; return }
    $old = 'license = { text = "Proprietary" }'
    $new = @'
license = "Proprietary"  # FIX-14-PEP639
license-files = ["LICENSE"]
'@
    if (-not $text.Contains($old)) { Write-Skip "anchor پیدا نشد"; return }
    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $pp
    $text = $text.Replace($old, $new.TrimEnd())
    Write-TextFile -FullPath $pp -Content $text
    & python -c "import tomllib; tomllib.loads(open(r'$pp', 'rb').read().decode('utf-8'))" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Err "TOML نامعتبر — rollback"; Restore-File -FullPath $pp | Out-Null; return }
    Write-Ok "pyproject.toml patch شد"
    Write-Host "`n===[ DONE: gam 14 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
