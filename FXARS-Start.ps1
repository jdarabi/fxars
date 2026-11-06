# FX-ARS Startup Script
Set-Location "C:\FX"

# Load env
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') {
        $name = $matches[1]
        $value = $matches[2].Trim('"', "'")
        if ($value) { Set-Item -Path "Env:$name" -Value $value }
    }
}

# Start server (background)
Start-Process -FilePath "python" -ArgumentList "-m", "fxars", "serve", "--port", "8080" -WindowStyle Hidden

# Wait for server
Start-Sleep -Seconds 4

# Open dashboard
Start-Process "http://127.0.0.1:8080/"

# Start consultant (background)
Start-Process -FilePath "python" -ArgumentList "-m", "fxars.live.consult", "--interval", "300" -WindowStyle Hidden

Write-Host "FX-ARS started (server + consultant)" -ForegroundColor Green
