#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\project\FX', [switch]$DryRun, [switch]$NoPause)
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\_common.ps1"
try {
    Assert-Pwsh7
    Initialize-Script -Name 'license-security' -ProjectRoot $ProjectRoot -DryRun:$DryRun

    $license = @"
FX-ARS - Proprietary License
================================

Copyright (c) 2026 FX-ARS Technical Team. All rights reserved.

This software is proprietary and confidential. Unauthorized copying,
modification, distribution, or use is strictly prohibited without the
express written permission of the copyright holder.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"@

    $security = @"
# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.5.x   | :white_check_mark: |
| < 1.5   | :x:                |

## Reporting a Vulnerability

Do NOT open a public issue. Report privately to security@example.com.

## Known Limitations

See docs/LIMITATIONS.md.
"@

    foreach ($pair in @(
        @{ Path = (Join-Path $ProjectRoot 'LICENSE');     Content = $license },
        @{ Path = (Join-Path $ProjectRoot 'SECURITY.md'); Content = $security }
    )) {
        if (Test-Path $pair.Path) { Write-Skip "$(Split-Path -Leaf $pair.Path) موجود"; continue }
        if ($DryRun) { Write-Warn2 "DRY-RUN: $(Split-Path -Leaf $pair.Path)"; continue }
        Set-Content -Path $pair.Path -Value $pair.Content -Encoding UTF8 -NoNewline
        Write-Ok "created $(Split-Path -Leaf $pair.Path)"
    }
    Write-Host "`n===[ DONE: gam 03 ]===" -ForegroundColor Green
}
catch { Write-Err "خطا: $_"; Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray }
finally { Pause-IfNeeded -NoPause:$NoPause }
