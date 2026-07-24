param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$backendDir = Join-Path $ProjectRoot "backend"
$python = Join-Path $backendDir ".venv\Scripts\python.exe"
$launcher = Join-Path $backendDir "tools\run_backend_windowless.py"

if (-not (Test-Path $python)) {
    throw "Backend virtual environment not found: $python"
}

if ($Restart) {
    $pids = netstat -ano |
        Select-String -Pattern "LISTENING" |
        Select-String -Pattern ":(5000|9000)\s" |
        ForEach-Object {
            $parts = ($_.Line -split "\s+") | Where-Object { $_ }
            if ($parts.Length -ge 5) { [int]$parts[-1] }
        } |
        Sort-Object -Unique
    foreach ($pidToStop in $pids) {
        Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
    }
}

$pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
if (-not $pathValue) {
    $pathValue = $env:Path
}
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
$env:FLASK_DEBUG = "0"

$process = Start-Process `
    -FilePath $python `
    -ArgumentList "`"$launcher`"" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 3
Write-Output "Backend process started: $($process.Id)"
Write-Output "Flask: http://127.0.0.1:5000"
Write-Output "Pi TCP: 0.0.0.0:9000"
Write-Output "Logs: $backendDir\logs\backend_stdout.log, $backendDir\logs\backend_stderr.log"
