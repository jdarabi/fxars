#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot='C:\project\FX',[string]$TokenPrefix='8571434332',[switch]$DryRun)
$ErrorActionPreference='Stop'
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $ProjectRoot ".fix-backups\remove-secrets-$stamp"
if (-not $DryRun) { New-Item -ItemType Directory -Path $backup -Force | Out-Null }
$gitAvailable=[bool](Get-Command git -ErrorAction SilentlyContinue)
$isGitRepo=Test-Path (Join-Path $ProjectRoot '.git')
$removed=@()
foreach($file in @('.env','live.local.ps1','.env.local')) {
  $full=Join-Path $ProjectRoot $file
  if(-not (Test-Path $full)) { continue }
  $tracked=$false
  if($gitAvailable -and $isGitRepo){ $null=git -C $ProjectRoot ls-files --error-unmatch -- $file 2>$null; $tracked=($LASTEXITCODE -eq 0) }
  if(-not $DryRun){ Copy-Item $full (Join-Path $backup $file) -Force; Remove-Item $full -Force; if($tracked){ $null=git -C $ProjectRoot rm --cached --ignore-unmatch -- $file 2>$null } }
  $removed+=$file
}
$envEx=Join-Path $ProjectRoot '.env.example'
if(-not (Test-Path $envEx) -and -not $DryRun){ "FXARS_TELEGRAM_TOKEN=`nFXARS_TELEGRAM_CHAT_ID=`n" | Set-Content -Path $envEx -Encoding UTF8 }
Write-Host "Removed: $($removed -join ', ')" -ForegroundColor Green
if(-not $DryRun){ Write-Host "Backup: $backup" -ForegroundColor Green }
Write-Host "⚠️  Revoke Telegram tokens via @BotFather now!" -ForegroundColor Yellow
