# PowerShell installer for the project's git hooks.
# Re-run after every fresh clone — git does not version-control hooks.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$hookSrc = Join-Path $root "scripts\pre-commit.sh"
$hookDst = Join-Path $root ".git\hooks\pre-commit"

if (-not (Test-Path (Join-Path $root ".git"))) {
    Write-Error "ERROR: $root is not a git repository."
    exit 1
}
if (-not (Test-Path $hookSrc)) {
    Write-Error "ERROR: hook source $hookSrc not found."
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $root ".git\hooks") | Out-Null
Copy-Item $hookSrc $hookDst -Force

Write-Host "[OK] Installed pre-commit hook -> $hookDst"
Write-Host "     Bypass with: `$env:ALLOW_SRC_ONLY=1; git commit ..."
