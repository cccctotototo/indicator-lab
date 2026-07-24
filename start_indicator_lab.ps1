param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$workspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
$appPath = Join-Path $workspaceRoot "app.py"
$logPath = Join-Path $workspaceRoot "launcher.log"
$appUrl = "http://localhost:8503"

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
    if (-not (Test-Path -LiteralPath $appPath)) {
        throw "Application file is missing: $appPath"
    }
    $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($null -eq $nodeCommand) {
        throw "Node.js 20 or newer is required for the PineTS indicator engine."
    }
    $nodeMajor = [int]((& $nodeCommand.Source --version).TrimStart("v").Split(".")[0])
    if ($nodeMajor -lt 20) {
        throw "Node.js 20 or newer is required. Current version: $(& $nodeCommand.Source --version)"
    }
    $pineTsPackage = Join-Path $workspaceRoot "node_modules\pinets\package.json"
    if (-not (Test-Path -LiteralPath $pineTsPackage)) {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($null -eq $npmCommand) {
            throw "npm.cmd is missing; PineTS could not be installed."
        }
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

    $ready = $false
    $streamlitProcess = $null
    try {
        $probe = Invoke-WebRequest -UseBasicParsing -Uri $appUrl -TimeoutSec 1
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
        $startInfo.Arguments = '-m streamlit run app.py --server.port 8503 --server.headless true --browser.gatherUsageStats false'
        $startInfo.WorkingDirectory = $workspaceRoot
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $streamlitProcess = [System.Diagnostics.Process]::Start($startInfo)
        if ($null -eq $streamlitProcess) {
            throw "The Streamlit process could not be created."
        }
        Write-LauncherLog "Started Streamlit process $($streamlitProcess.Id)."

        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 500
            if ($streamlitProcess.HasExited) {
                throw "Streamlit exited early with code $($streamlitProcess.ExitCode)."
            }
            try {
                $probe = Invoke-WebRequest -UseBasicParsing -Uri $appUrl -TimeoutSec 1
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
    Write-LauncherLog "Health check passed at $appUrl."

    if (-not $NoBrowser) {
        $browserInfo = New-Object System.Diagnostics.ProcessStartInfo
        $browserInfo.FileName = $appUrl
        $browserInfo.UseShellExecute = $true
        [System.Diagnostics.Process]::Start($browserInfo) | Out-Null
        Write-LauncherLog "Opened the default browser."
    }

    Write-Host "Indicator Lab is ready: $appUrl"
    if (($null -ne $streamlitProcess) -and (-not $NoBrowser)) {
        Write-Host "Keep this window open while using Indicator Lab. Close it to stop the server."
        Wait-Process -Id $streamlitProcess.Id
    }
    exit 0
}
catch {
    Write-LauncherLog "ERROR: $($_.Exception.Message)"
    Write-Error $_.Exception.Message
    exit 1
}
