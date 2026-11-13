#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'password-length' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $pw = Join-Path $ProjectRoot 'fxars\identity\passwords.py'
    $text = Read-TextFile -FullPath $pw
    if ($text -match 'FIX-08-MAX-PASSWORD') { Write-Skip "از قبل patch شده"; return }

    $oldHash = @'
def hash_password(password: str, *, iterations: int = 210_000) -> str:
    if len(password) < 10:
        raise ValueError("رمز عبور باید حداقل ۱۰ کاراکتر باشد.")
'@
    $newHash = @'
MAX_PASSWORD_LENGTH = 256  # FIX-08-MAX-PASSWORD

def hash_password(password: str, *, iterations: int = 210_000) -> str:
    if len(password) < 10:
        raise ValueError("رمز عبور باید حداقل ۱۰ کاراکتر باشد.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"رمز عبور نمی‌تواند بیش از {MAX_PASSWORD_LENGTH} کاراکتر باشد.")
'@
    if (-not $text.Contains($oldHash)) { Write-Err "hash_password anchor پیدا نشد"; return }
    $text = $text.Replace($oldHash, $newHash.TrimEnd())

    $oldVerify = @'
def verify_password(password: str, encoded: str) -> bool:
    try:
'@
    $newVerify = @'
def verify_password(password: str, encoded: str) -> bool:
    # FIX-08-MAX-PASSWORD
    if not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
'@
    if (-not $text.Contains($oldVerify)) { Write-Err "verify_password anchor پیدا نشد"; return }
    $text = $text.Replace($oldVerify, $newVerify.TrimEnd())

    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $pw
    $text = $text.TrimEnd() + "`n`n# FIX-08-MAX-PASSWORD`n"
    Write-TextFile -FullPath $pw -Content $text
    if (Test-PyCompile -FullPath $pw) { Write-Ok "passwords.py patch شد" }
    else { Restore-File -FullPath $pw | Out-Null }
    Write-Host "`n===[ DONE: gam 08 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
