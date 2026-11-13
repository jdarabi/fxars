#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'cors-default' -ProjectRoot $ProjectRoot -DryRun:$DryRun
    $srv = Join-Path $ProjectRoot 'fxars\api\server.py'
    $text = Read-TextFile -FullPath $srv
    if ($text -match 'FIX-15-CORS-DEFAULT') { Write-Skip "از قبل patch شده"; return }
    $old = @'
        self.send_response(204)
        cors = getattr(self.server.app.settings.api, 'cors_allow_origin', '')  # type: ignore[attr-defined]
        if cors:
            self.send_header('Access-Control-Allow-Origin', cors)
        else:
            self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE, PUT, PATCH, HEAD")
        self.end_headers()
'@
    $new = @'
        # FIX-15-CORS-DEFAULT: پیش‌فرض same-origin (بدون ACAO)، نه *
        self.send_response(204)
        cors = getattr(self.server.app.settings.api, 'cors_allow_origin', '')
        if cors:
            self.send_header('Access-Control-Allow-Origin', cors)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE, PUT, PATCH, HEAD")
        self.end_headers()
'@
    if (-not $text.Contains($old)) {
        Write-Err "anchor پیدا نشد. بلوک do_OPTIONS فعلی:"
        $lines = $text -split "`r?`n", 0
        $optIdx = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match 'def do_OPTIONS') { $optIdx = $i; break }
        }
        if ($optIdx -ge 0) {
            for ($j = $optIdx; $j -lt [Math]::Min($optIdx + 25, $lines.Count); $j++) {
                Write-Host ("      {0,4}: {1}" -f ($j+1), $lines[$j]) -ForegroundColor DarkGray
            }
        }
        return
    }
    if ($DryRun) { Write-Warn2 "DRY-RUN"; return }
    Backup-File -FullPath $srv
    $patched = $text.Replace($old, $new.TrimEnd())
    $patched = $patched.TrimEnd() + "`n`n# FIX-15-CORS-DEFAULT`n"
    Write-TextFile -FullPath $srv -Content $patched
    if (Test-PyCompile -FullPath $srv) { Write-Ok "server.py patch شد" }
    else { Restore-File -FullPath $srv | Out-Null }
    Write-Host "`n===[ DONE: gam 15 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
