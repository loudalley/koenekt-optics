# Builds the Koenekt GREC Converter MSI into apps\grec_converter\dist.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File apps\grec_converter\build.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here '..\..')
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    & py -3.14 -m venv (Join-Path $root '.venv')
    & $python -m pip install -r (Join-Path $root 'requirements.txt')
}
Push-Location $here
try {
    if (Test-Path build) { Remove-Item -Recurse -Force build }
    & $python setup.py bdist_msi
    if ($LASTEXITCODE) { throw "cx_Freeze failed ($LASTEXITCODE)" }
    Get-ChildItem dist\*.msi | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
} finally {
    Pop-Location
}
