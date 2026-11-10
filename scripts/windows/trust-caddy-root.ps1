<#
.SYNOPSIS
    Make Windows trust the certificate Caddy issues with CADDY_TLS=internal, so browsers stop warning.

.DESCRIPTION
    On the server (exports the root from the running proxy, then trusts it):
        powershell -ExecutionPolicy Bypass -File scripts\windows\trust-caddy-root.ps1

    On another Windows computer (copy deploy\caddy-root.crt there first):
        powershell -ExecutionPolicy Bypass -File trust-caddy-root.ps1 -CertFile .\caddy-root.crt

    In an elevated shell the root goes to the machine store (every user, Edge and Chrome); otherwise to the
    current user's store (Windows asks for confirmation). Firefox uses the Windows store when
    security.enterprise_roots.enabled is true (the default on Windows in recent versions).
    Trust only a root you exported yourself from your own server.
#>
[CmdletBinding()]
param([string] $CertFile = "")

$ErrorActionPreference = "Stop"

if ($CertFile -eq "") {
    # on the server: needs the repository; with -CertFile this script also runs alone on a client
    . (Join-Path $PSScriptRoot "common.ps1")
    Assert-Docker
    $CertFile = Join-Path $RepoRoot "deploy\caddy-root.crt"
    Invoke-Compose @("cp", "proxy:/data/caddy/pki/authorities/local/root.crt", $CertFile)
    Write-Host "Exported Caddy's root certificate to $CertFile (copy it to the other computers)."
}
$CertFile = (Resolve-Path $CertFile).Path

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$elevated = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
$store = "Cert:\CurrentUser\Root"
if ($elevated) { $store = "Cert:\LocalMachine\Root" }
$cert = Import-Certificate -FilePath $CertFile -CertStoreLocation $store
Write-Host "Trusted '$($cert.Subject)' (thumbprint $($cert.Thumbprint)) in $store. Restart the browser."
