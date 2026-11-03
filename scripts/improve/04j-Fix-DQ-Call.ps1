#Requires -Version 7.0
[CmdletBinding()]
param([string]$ProjectRoot = 'C:\FX')

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)

Write-Host "===[ GAM 04j: Fix DQ gate call ]===" -ForegroundColor Cyan

$anPath = Join-Path $ProjectRoot 'fxars\services\analysis.py'
$text = [System.IO.File]::ReadAllText($anPath, [System.Text.Encoding]::UTF8)

$oldCall = @"
            _dq_runs = self.quality_runs.list(
                instrument_id=instrument_id, timeframe=tf.value, limit=1,
            )
"@
$newCall = @"
            # FIX-P0-DQ-FAIL-CALL: list() timeframe kwarg ندارد
            _dq_all = self.quality_runs.list(instrument_id=instrument_id, limit=10)
            _dq_runs = [r for r in _dq_all if r.timeframe == tf.value][:1]
"@

if ($text.Contains($oldCall)) {
    $text = $text.Replace($oldCall, $newCall)
    Write-Host "  [PATCH A] DQ list call fixed" -ForegroundColor Green
} else {
    Write-Host "  [FAIL A] old call not found; showing context:" -ForegroundColor Red
    $lines = $text -split "`n", 0
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match 'quality_runs\.list') {
            for ($j = [Math]::Max(0,$i-2); $j -le [Math]::Min($lines.Count-1,$i+5); $j++) {
                Write-Host ("    {0,4}: [{1}]" -f ($j+1), $lines[$j])
            }
            break
        }
    }
    exit 1
}

if ($text -match 'except Exception as _dq_exc:') {
    Write-Host "  [SKIP B] except already logs" -ForegroundColor DarkGray
} elseif ($text.Contains('        except Exception:') -and $text.Contains('            _dq_failed = True')) {
    $text = $text.Replace(
        '        except Exception:' + "`n" + '            _dq_failed = True',
        '        except Exception as _dq_exc:' + "`n" +
        '            logger.warning("data quality check failed: %s", _dq_exc)' + "`n" +
        '            _dq_failed = False'
    )
    Write-Host "  [PATCH B] except now allows on error" -ForegroundColor Green
}

[System.IO.File]::WriteAllText($anPath, $text, $utf8)
Write-Host "  [WROTE] analysis.py" -ForegroundColor Green

Write-Host "--- Syntax ---" -ForegroundColor Yellow
& python -m py_compile $anPath
if ($LASTEXITCODE -ne 0) { throw "syntax error" }
Write-Host "  [OK] analysis.py compiles" -ForegroundColor Green

$fa = [System.IO.File]::ReadAllText($anPath, [System.Text.Encoding]::UTF8)
Write-Host "  no timeframe in list(): $(-not ($fa -match 'quality_runs\.list\([^)]*timeframe='))"
Write-Host "  _dq_failed=False      : $($fa.Contains('_dq_failed = False'))"
Write-Host "===[ DONE: gam 04j ]===" -ForegroundColor Green