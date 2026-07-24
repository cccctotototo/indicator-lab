param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$workspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
$apiPath = Join-Path $workspaceRoot "src\quant_labeler\api.py"
$frontendPath = Join-Path $workspaceRoot "frontend"
$frontendPackage = Join-Path $frontendPath "package.json"
$frontendBuild = Join-Path $frontendPath "dist\index.html"
$logPath = Join-Path $workspaceRoot "launcher.log"
$appUrl = "http://127.0.0.1:8503"
$healthUrl = "$appUrl/api/health"

function Write-LauncherLog {
    param([string]$Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$stamp] $Message" -Encoding UTF8
}

try {
    Set-Content -LiteralPath $logPath -Value "Indicator Lab launcher" -Encoding UTF8
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "Python environment is missing: $pythonPath"
    }
    if (-not (Test-Path -LiteralPath $apiPath)) {
        throw "API application file is missing: $apiPath"
    }
    & $pythonPath -c "import fastapi, uvicorn, quant_labeler" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-LauncherLog "Installing Python API dependencies."
        & $pythonPath -m pip install -e $workspaceRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Python API dependency installation failed with code $LASTEXITCODE."
        }
    }
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($null -eq $nodeCommand) {
        throw "Node.js 20 or newer is required for the PineTS indicator engine."
    }
    $nodeMajor = [int]((& $nodeCommand.Source --version).TrimStart("v").Split(".")[0])
    if ($nodeMajor -lt 20) {
        throw "Node.js 20 or newer is required. Current version: $(& $nodeCommand.Source --version)"
    }
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npmCommand) {
        throw "npm.cmd is missing; frontend dependencies could not be installed."
    }
    $pineTsPackage = Join-Path $workspaceRoot "node_modules\pinets\package.json"
    if (-not (Test-Path -LiteralPath $pineTsPackage)) {
        Write-LauncherLog "Installing PineTS dependencies."
        Push-Location -LiteralPath $workspaceRoot
        try {
            & $npmCommand.Source install --ignore-scripts --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) {
                throw "PineTS dependency installation failed with code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }
    if (-not (Test-Path -LiteralPath $frontendPackage)) {
        throw "Frontend package file is missing: $frontendPackage"
    }
    $frontendModules = Join-Path $frontendPath "node_modules\react\package.json"
    if (-not (Test-Path -LiteralPath $frontendModules)) {
        Write-LauncherLog "Installing React frontend dependencies."
        Push-Location -LiteralPath $frontendPath
        try {
            & $npmCommand.Source install --ignore-scripts --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) {
                throw "React dependency installation failed with code $LASTEXITCODE."
            }
        }
        finally {
            Pop-Location
        }
    }
    Write-LauncherLog "Building React frontend."
    Push-Location -LiteralPath $frontendPath
    try {
        & $npmCommand.Source run build
        if ($LASTEXITCODE -ne 0) {
            throw "React build failed with code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $frontendBuild)) {
        throw "React build output is missing: $frontendBuild"
    }

    $ready = $false
    $apiProcess = $null
    try {
        $probe = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1
        $ready = $probe.StatusCode -eq 200
        if ($ready) {
            Write-LauncherLog "Existing server is healthy."
        }
    }
    catch {
        $ready = $false
    }

    if (-not $ready) {
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $pythonPath
        $startInfo.Arguments = '-m uvicorn quant_labeler.api:app --host 127.0.0.1 --port 8503'
        $startInfo.WorkingDirectory = $workspaceRoot
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $apiProcess = [System.Diagnostics.Process]::Start($startInfo)
        if ($null -eq $apiProcess) {
            throw "The FastAPI process could not be created."
        }
        Write-LauncherLog "Started FastAPI process $($apiProcess.Id)."

        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 500
            if ($apiProcess.HasExited) {
                throw "FastAPI exited early with code $($apiProcess.ExitCode)."
            }
            try {
                $probe = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 1
                if ($probe.StatusCode -eq 200) {
                    $ready = $true
                    break
                }
            }
            catch {
                $ready = $false
            }
        }
    }

    if (-not $ready) {
        throw "The server did not become ready within 20 seconds."
    }
    Write-LauncherLog "Health check passed at $healthUrl."

    if (-not $NoBrowser) {
        $browserInfo = New-Object System.Diagnostics.ProcessStartInfo
        $browserInfo.FileName = $appUrl
        $browserInfo.UseShellExecute = $true
        [System.Diagnostics.Process]::Start($browserInfo) | Out-Null
        Write-LauncherLog "Opened the default browser."
    }

    Write-Host "Indicator Lab is ready: $appUrl"
    if (($null -ne $apiProcess) -and (-not $NoBrowser)) {
        Write-Host "Keep this window open while using Indicator Lab. Close it to stop the server."
        Wait-Process -Id $apiProcess.Id
    }
    exit 0
}
catch {
    Write-LauncherLog "ERROR: $($_.Exception.Message)"
    Write-Error $_.Exception.Message
    exit 1
}
