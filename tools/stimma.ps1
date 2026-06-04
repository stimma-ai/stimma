$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
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
