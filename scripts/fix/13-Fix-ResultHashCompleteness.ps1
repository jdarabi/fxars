#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..\..").Path)

$ErrorActionPreference = 'Stop'
$file = Join-Path $ProjectRoot 'fxars\services\analysis.py'
Write-Host "[FIX-13] Result hash completeness" -ForegroundColor Cyan

$content = Get-Content $file -Raw -Encoding UTF8
if ($content -match 'FIX-13-RESULT-HASH') {
    Write-Host "  Already patched. Skipping." -ForegroundColor Yellow
    return
}

$old = @'
        signature = sorted(
            (
                {
                    "module_id": evidence.module_id,
                    "family": evidence.family.value,
                    "observed_at": format_ts(evidence.observed_at),
                    "available_at": format_ts(evidence.available_at),
                    "direction": evidence.direction.value,
                    "strength": evidence.strength,
                    "confidence_raw": evidence.confidence_raw,
                }
                for evidence in evidences
            ),
            key=lambda item: (item["observed_at"], item["module_id"], item["direction"], item["strength"]),
        )
'@
$new = @'
        # FIX-13-RESULT-HASH: امضای کامل شامل zone/invalidation/expiry/params_hash
        # تا تغییر در ابطال یا ناحیه قیمتی هم result_hash را تغییر دهد.
        signature = sorted(
            (
                {
                    "module_id": evidence.module_id,
                    "module_version": evidence.module_version,
                    "family": evidence.family.value,
                    "observed_at": format_ts(evidence.observed_at),
                    "available_at": format_ts(evidence.available_at),
                    "direction": evidence.direction.value,
                    "strength": evidence.strength,
                    "confidence_raw": evidence.confidence_raw,
                    "price_zone": (
                        {"low": format(evidence.price_zone.low, "f"),
                         "high": format(evidence.price_zone.high, "f")}
                        if evidence.price_zone else None
                    ),
                    "invalidation": evidence.invalidation,
                    "expiry": format_ts(evidence.expiry) if evidence.expiry else None,
                    "parameters_hash": evidence.parameters_hash,
                    "source_refs": list(evidence.source_refs),
                }
                for evidence in evidences
            ),
            key=lambda item: (item["observed_at"], item["module_id"], item["direction"], item["strength"]),
        )
'@
if (-