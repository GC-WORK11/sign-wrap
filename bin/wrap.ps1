# wrap — PowerShell shim, same routing as wrap.cmd/wrap.js.
$ROOT = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) { & node "$ROOT\bin\wrap.js" @args; exit $LASTEXITCODE }
# `--version` filters out the Microsoft Store alias stub (on PATH, fails)
foreach ($cand in @("python", "python3")) {
  if ((Get-Command $cand -ErrorAction SilentlyContinue) -and
      ($null -ne (& $cand --version 2>$null)) -and $LASTEXITCODE -eq 0) {
    & $cand "$ROOT\server\wrap_cli.py" @args; exit $LASTEXITCODE
  }
}
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 "$ROOT\server\wrap_cli.py" @args; exit $LASTEXITCODE
}
Write-Error "wrap: node or python required"
exit 1
