# Search Anything - one-step start for Windows (called by start.bat).
# First run installs what it needs into .venv (a few minutes). Later runs start at once.
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function Say($text) { Write-Host ""; Write-Host $text -ForegroundColor Cyan }

# 1) Python 3.10+  ("py -3" launcher first; "python" may be the Microsoft Store stub)
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

$py = Find-Python
if (-not $py) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say "Installing Python 3.12 with winget..."
        winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
        $py = Find-Python
    }
    if (-not $py) {
        Say "Python 3.10 or newer is needed. Install it (tick 'Add python.exe to PATH'), then run start.bat again."
        Start-Process "https://www.python.org/downloads/windows/"
        exit 1
    }
}

# 2) Private environment + packages (only re-installed when requirements.txt changes)
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Say "First run: preparing (this takes a few minutes)..."
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

# 3) Run (browser opens by itself; close this window or press Ctrl+C to stop)
Say "Starting Search Anything..."
& $venvPy -m search_anything --open-browser --default-folders @args
exit $LASTEXITCODE
