$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create build environment' }
    }
    & .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Could not install build dependencies' }
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm xiaoguo.spec
    if ($LASTEXITCODE -ne 0) { throw 'EXE build failed' }
} finally {
    Pop-Location
}
