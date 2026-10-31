# Search Anything - one-step start for Windows (called by start.bat).
#
# Runs in Docker when Docker Desktop is installed and running, otherwise in a
# Python virtual environment (.venv). Options (also via start.bat):
#   --docker          use Docker (fail if it is not available)
#   --no-docker       always use Python/.venv
#   --folder PATH     folder to search (repeatable; default: Documents, Desktop, Downloads)
#   anything else is passed to the app
# Environment: SA_PORT (default 8765).
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function Say($text) { Write-Host ""; Write-Host $text -ForegroundColor Cyan }
$Port = if ($env:SA_PORT) { $env:SA_PORT } else { "8765" }
$Url = "http://localhost:$Port"
$Name = "search-anything"
$Image = "search-anything:local"

$Use = "auto"
$Folders = @()
$AppArgs = @()
for ($i = 0; $i -lt $args.Count; $i++) {
    $a = [string]$args[$i]
    if ($a -eq "--docker") { $Use = "docker" }
    elseif ($a -eq "--no-docker") { $Use = "venv" }
    elseif ($a -eq "--folder" -and $i + 1 -lt $args.Count) { $i++; $Folders += [string]$args[$i] }
    elseif ($a.StartsWith("--folder=")) { $Folders += $a.Substring(9) }
    else { $AppArgs += $a }
}

function Wait-AndOpen {
    for ($k = 0; $k -lt 120; $k++) {
        try {
            Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "$Url/api/status" | Out-Null
            Start-Process $Url
            return
        } catch { Start-Sleep -Milliseconds 500 }
    }
    Write-Host "The app did not answer at $Url yet."
}

function Test-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    docker info *> $null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $old
    return $ok
}

# ------------------------------------------------------------------ venv
$candidates = @(
    @{ Exe = "py";      Args = @("-3") },
    @{ Exe = "python";  Args = @() },
    @{ Exe = "python3"; Args = @() }
)
function Find-Python {
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            & $c.Exe @($c.Args + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)")) 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $c }
        } catch { }
    }
    return $null
}

function Start-Venv {
    $py = Find-Python
    if (-not $py) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Say "Installing Python 3.12 with winget..."
            winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
            $py = Find-Python
        }
        if (-not $py) {
            Say "Python 3.10 or newer is needed. Install it (tick 'Add python.exe to PATH') or Docker Desktop, then run start.bat again."
            Start-Process "https://www.python.org/downloads/windows/"
            exit 1
        }
    }
    $venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Say "First run: preparing Python environment (a few minutes)..."
        & $py.Exe @($py.Args + @("-m", "venv", ".venv"))
        if ($LASTEXITCODE -ne 0) { exit 1 }
    }
    $hash = (Get-FileHash -LiteralPath "requirements.txt" -Algorithm SHA256).Hash
    $stamp = Join-Path $PSScriptRoot ".venv\.requirements.sha"
    $old = if (Test-Path $stamp) { (Get-Content -LiteralPath $stamp -Raw).Trim() } else { "" }
    if ($old -ne $hash) {
        Say "Installing packages..."
        & $venvPy -m pip install --quiet --upgrade pip
        & $venvPy -m pip install --quiet -r requirements.txt
        if ($LASTEXITCODE -ne 0) { exit 1 }
        Set-Content -LiteralPath $stamp -Value $hash
    }
    Say "Starting Search Anything (Python)...   data: .\data   stop: close this window or Ctrl+C"
    $runArgs = @("-m", "search_anything", "--port", $Port, "--open-browser")
    if ($Folders.Count -eq 0) { $runArgs += "--default-folders" } else { foreach ($f in $Folders) { $runArgs += @("--folder", $f) } }
    & $venvPy @($runArgs + $AppArgs)
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------- docker
function Start-Docker {
    Say "Building the Docker image (quick after the first time)..."
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    docker build -q -t $Image . | Out-Null
    $built = ($LASTEXITCODE -eq 0)
    docker image inspect $Image *> $null
    $haveImage = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $old
    if (-not $built) {
        if ($haveImage) { Say "Build failed (offline?) - using the image built earlier." }
        elseif ($Use -eq "docker") { Say "Docker build failed."; exit 1 }
        else { Say "Docker build failed - starting with Python instead."; Start-Venv }
    }

    # Folders to search: mounted read-only at /host/<name>.
    if ($Folders.Count -eq 0) {
        foreach ($d in @("Documents", "Desktop", "Downloads")) {
            $p = Join-Path $env:USERPROFILE $d
            if (Test-Path -LiteralPath $p -PathType Container) { $script:Folders += $p }
        }
    }
    $mounts = @(); $inner = @(); $map = ""
    foreach ($f in $Folders) {
        if (-not (Test-Path -LiteralPath $f -PathType Container)) { Write-Host "Skipping missing folder: $f"; continue }
        $abs = (Resolve-Path -LiteralPath $f).ProviderPath
        $leaf = Split-Path -Leaf $abs
        $target = "/host/$leaf"; $n = 2
        while ($inner -contains $target) { $target = "/host/$leaf-$n"; $n++ }
        $inner += $target
        $mounts += @("--mount", "type=bind,source=$abs,target=$target,readonly")
        $map += "$target=$abs;"
    }

    $ErrorActionPreference = "Continue"
    docker rm -f $Name *> $null
    Say "Starting Search Anything (Docker)...   data: Docker volume search-anything-data   stop: close this window or Ctrl+C"
    # Port published on 127.0.0.1 only: reachable from this computer, not the network.
    $runArgs = @("run", "-d", "--rm", "--init", "--name", $Name, "-p", "127.0.0.1:${Port}:8765",
        "-v", "search-anything-data:/data",
        "-e", "SA_MODE=local", "-e", "SA_HOST=0.0.0.0", "-e", "SA_IN_CONTAINER=1",
        "-e", "SA_FOLDERS=$($inner -join ':')", "-e", "SA_PATH_MAP=$map") + $mounts + @($Image, "python", "-m", "search_anything") + $AppArgs
    docker @runArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { Say "Could not start the container."; exit 1 }
    try {
        Wait-AndOpen
        docker logs -f $Name
    } finally {
        # Runs on Ctrl+C and when the window is closed normally.
        Say "Stopping..."
        docker stop $Name *> $null
    }
    exit 0
}

if ($Use -eq "venv") { Start-Venv }
elseif (Test-Docker) { Start-Docker }
elseif ($Use -eq "docker") { Say "Docker is not installed or not running. Start Docker Desktop, or run without --docker."; exit 1 }
else { Say "Docker not found or not running - using Python instead."; Start-Venv }
