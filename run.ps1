param(
    [switch]$ShowLibrary,
    [string]$Model,
    [string]$Hotkey
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot

$cmdArgs = @()
if ($ShowLibrary) { $cmdArgs += "--show-library" }
if ($Model) { $cmdArgs += "--model", $Model }
if ($Hotkey) { $cmdArgs += "--hotkey", $Hotkey }

# 1. Use project virtual environment if present
$VenvTucknote = Join-Path $ScriptDir ".venv\Scripts\tucknote.exe"
if (Test-Path $VenvTucknote) {
    & $VenvTucknote @cmdArgs
    exit $LASTEXITCODE
}

# 2. Use uv if available
$UvExe = "$HOME\.local\bin\uv.exe"
if (Test-Path $UvExe) {
    & $UvExe run tucknote @cmdArgs
    exit $LASTEXITCODE
}

# 3. Fallback to Python launcher
py -3.12 -m tucknote @cmdArgs
