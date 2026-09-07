param(
    [Parameter(Mandatory = $true)][string]$InstallDirectory,
    [switch]$Check
)

# Old watchdogs could leave Python alive after Electron was terminated.
# Scope cleanup to this installation, including its command-line launcher
# when Python itself lives in the shared runtime outside the install tree.
$ErrorActionPreference = 'Stop'
$installationRoot = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\') + '\'
$backendEntry = $installationRoot + 'resources\stimma-backend\backend\main.py'
$backendLauncher = $installationRoot + 'resources\stimma-backend\run.cmd'
function Get-InstallationProcesses {
    @(Get-CimInstance Win32_Process | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($installationRoot, [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.Name -in @('python.exe', 'pythonw.exe', 'cmd.exe') -and $_.CommandLine -and
            ($_.CommandLine.IndexOf('"' + $backendEntry + '"', [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
             $_.CommandLine.IndexOf('"' + $backendLauncher + '"', [StringComparison]::OrdinalIgnoreCase) -ge 0))
    })
}

$processes = Get-InstallationProcesses
if ($Check) {
    if ($processes.Count -gt 0) { exit 0 }
    exit 1
}
foreach ($target in $processes) {
    # /T captures multiprocessing children before an intermediate parent exits.
    $ErrorActionPreference = 'Continue'
    & "$env:SystemRoot\System32\taskkill.exe" /PID $target.ProcessId /T /F 2>&1 | Out-Null
    $ErrorActionPreference = 'Stop'
}
if ((Get-InstallationProcesses).Count -gt 0) { exit 2 }
exit 0
