$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# WinGet updates the persistent user PATH but not the shell that performed the
# install. Discover uv's package directory as a first-run fallback so this
# command works immediately after bootstrapping a Windows workstation.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  $UvExe = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') `
    -Filter uv.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object FullName -Like '*astral-sh.uv*' |
    Select-Object -First 1
  if ($UvExe) {
    $env:PATH = "$($UvExe.DirectoryName);$env:PATH"
  }
}

# Native Rust dependencies need the MSVC compiler environment. A regular
# PowerShell/Windows Terminal session does not inherit it, so import the Visual
# Studio developer environment automatically instead of requiring a special
# "Developer PowerShell" window for `stimma dev all` or `stimma app build`.
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
  $VsDevCandidates = @(
    'C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\Common7\Tools\VsDevCmd.bat',
    'C:\Program Files\Microsoft Visual Studio\18\BuildTools\Common7\Tools\VsDevCmd.bat',
    'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat',
    'C:\Program Files\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat'
  )
  $VsDevCmd = $VsDevCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if ($VsDevCmd) {
    $EnvDump = cmd.exe /d /s /c "`"$VsDevCmd`" -arch=x64 -host_arch=x64 >nul && set"
    if ($LASTEXITCODE -eq 0) {
      $EnvDump | ForEach-Object {
        if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
          Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2]
        }
      }
    }
  }
}

$DenoCmd = Get-Command deno -ErrorAction SilentlyContinue

if (-not $DenoCmd) {
  Write-Host "Deno is not installed. Installing Deno..."
  irm https://deno.land/install.ps1 | iex
  $DenoInstall = if ($env:DENO_INSTALL) { $env:DENO_INSTALL } else { Join-Path $env:USERPROFILE ".deno" }
  $DenoBin = Join-Path $DenoInstall "bin\deno.exe"
  $env:PATH = "$($DenoInstall)\bin;$($env:PATH)"
} else {
  $DenoBin = $DenoCmd.Path
}

& $DenoBin run --allow-read --allow-write --allow-env --allow-run --allow-net (Join-Path $ScriptDir "stimma.ts") @args
exit $LASTEXITCODE
