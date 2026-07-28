# Get the directory where the script is located
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "      YTStar Local Server + Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check if python is installed
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "[-] Python was not found on your system." -ForegroundColor Red
    Write-Host "Please download and install Python from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Make sure to check the option 'Add Python to PATH' during installation." -ForegroundColor Yellow
    Exit
}

# 2. Install requirements
Write-Host "[*] Installing/updating Python dependencies..." -ForegroundColor Cyan
pip install -r backend/requirements.txt

# 3. Check for cloudflared.exe
$cloudflaredPath = Join-Path $ScriptDir "cloudflared.exe"
if (-not (Test-Path $cloudflaredPath)) {
    Write-Host "[*] cloudflared.exe not found. Downloading the latest version from Cloudflare..." -ForegroundColor Cyan
    $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
        Invoke-WebRequest -Uri $url -OutFile $cloudflaredPath -UserAgent "Mozilla/5.0"
        Write-Host "[+] Downloaded cloudflared.exe successfully." -ForegroundColor Green
    } catch {
        Write-Host "[-] Failed to download cloudflared.exe automatically." -ForegroundColor Red
        Write-Host "Please download it manually from:" -ForegroundColor Yellow
        Write-Host "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -ForegroundColor Yellow
        Write-Host "And place it in this directory: $ScriptDir" -ForegroundColor Yellow
        Exit
    }
}

# 4. Start the FastAPI backend server in a new window
Write-Host "[*] Starting FastAPI backend server in a new window..." -ForegroundColor Cyan
Start-Process cmd -ArgumentList "/k", "cd backend && python main.py" -WorkingDirectory $ScriptDir -WindowStyle Normal

# Wait for server to start up
Write-Host "[*] Waiting for server to initialize on http://localhost:8000..." -ForegroundColor Cyan
Start-Sleep -Seconds 3

# 5. Start Cloudflare Tunnel
Write-Host "[*] Launching Cloudflare Tunnel..." -ForegroundColor Cyan
Write-Host "==========================================================================" -ForegroundColor Yellow
Write-Host " LOOK FOR THE TAFEL / URL ENDING IN .trycloudflare.com BELOW!" -ForegroundColor Yellow
Write-Host " Share that URL with others or use it on your devices to access your site." -ForegroundColor Yellow
Write-Host " Press Ctrl+C in this terminal window to stop the tunnel." -ForegroundColor Yellow
Write-Host "==========================================================================" -ForegroundColor Yellow
Write-Host ""

& $cloudflaredPath tunnel --url http://localhost:8000
