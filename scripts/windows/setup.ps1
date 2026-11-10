<#
.SYNOPSIS
    First install on Windows: checks Docker Desktop, writes deploy\.env with fresh secrets, optionally opens
    the firewall and starts the stack.

.DESCRIPTION
    Run from any folder, in Windows PowerShell 5.1 or PowerShell 7:

        powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1 -AdminEmail admin@example.org -Start

    The admin password is asked for (never on the command line). RESEARCH_SECRETS_KEY and DB_PASSWORD are
    generated here; keep a copy of deploy\.env somewhere safe (losing the key makes saved user keys unreadable).
    An existing deploy\.env is never overwritten unless -Force is given.

.PARAMETER SiteAddress
    Host names / IPs the browsers will use, comma separated. Default: this computer's name and LAN IPv4.

.PARAMETER OpenFirewall
    Allow inbound TCP on the HTTPS and HTTP ports for the Private and Domain profiles (needs an elevated shell).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $AdminEmail,
    [string] $SiteAddress = "",
    [string] $SignupDomains = "",
    [string] $ContactEmail = "",
    [int] $HttpsPort = 443,
    [int] $HttpPort = 80,
    [switch] $OpenFirewall,
    [switch] $Start,
    [switch] $Force
)

. (Join-Path $PSScriptRoot "common.ps1")

function Get-DefaultSiteAddress {
    $names = @($env:COMPUTERNAME.ToLower())
    try {
        $config = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
            Select-Object -First 1
        if ($config) { $names += @($config.IPv4Address | ForEach-Object { $_.IPAddress }) }
    } catch {
        Write-Warning "Could not read the LAN address; pass -SiteAddress if browsers use an IP."
    }
    return ($names -join ", ")
}

function Read-AdminPassword {
    while ($true) {
        $first = Read-Host "Password for $AdminEmail (12 characters or more)" -AsSecureString
        $second = Read-Host "Same password again" -AsSecureString
        $a = ConvertTo-Plain $first
        $b = ConvertTo-Plain $second
        if ($a -ne $b) { Write-Warning "The two passwords differ."; continue }
        if ($a.Length -lt 12) { Write-Warning "Use at least 12 characters."; continue }
        if ($a.Contains("'") -or $a.Contains("`n")) { Write-Warning "Do not use ' or line breaks."; continue }
        return $a
    }
}

function ConvertTo-Plain([Security.SecureString] $Secure) {
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Format-EnvValue([string] $Value) {
    # Single quotes: Compose takes the value literally (no $ interpolation, # kept).
    if ($Value -eq "") { return "" }
    return "'" + $Value + "'"
}

Assert-Docker
Assert-LfCheckout

if ((Test-Path -LiteralPath $EnvFile) -and -not $Force) {
    throw "deploy\.env already exists. Edit it by hand, or pass -Force to replace it (the old secrets are lost)."
}
foreach ($value in @($AdminEmail, $SiteAddress, $SignupDomains, $ContactEmail)) {
    if ($value.Contains("'")) { throw "Values must not contain a single quote: $value" }
}
if ($SiteAddress -eq "") { $SiteAddress = Get-DefaultSiteAddress }
$password = Read-AdminPassword

$values = @{
    RESEARCH_SECRETS_KEY        = New-FernetKey
    DB_PASSWORD                 = New-HexSecret 24
    RESEARCH_WEB_ADMIN_EMAIL    = $AdminEmail
    RESEARCH_WEB_ADMIN_PASSWORD = $password
    RESEARCH_WEB_SIGNUP_DOMAINS = $SignupDomains
    RESEARCH_WEB_CONTACT_EMAIL  = $ContactEmail
    SITE_ADDRESS                = $SiteAddress
}
$lines = foreach ($line in (Get-Content -LiteralPath (Join-Path $RepoRoot "deploy\.env.example"))) {
    if ($line -match "^([A-Z_]+)=") {
        $name = $Matches[1]
        if ($values.ContainsKey($name)) { "$name=$(Format-EnvValue $values[$name])"; continue }
        if ($name -eq "HTTPS_PORT") { "HTTPS_PORT=$HttpsPort"; continue }
        if ($name -eq "HTTP_PORT") { "HTTP_PORT=$HttpPort"; continue }
    }
    $line
}
Write-Utf8NoBom $EnvFile $lines
Protect-File $EnvFile
$password = $null
Write-Host "Wrote deploy\.env (readable by $env:USERNAME only). Back it up somewhere safe: it holds RESEARCH_SECRETS_KEY."
Write-Host "Site address: $SiteAddress"

if ($OpenFirewall) {
    if (-not (Test-Administrator)) { throw "-OpenFirewall needs an elevated PowerShell (Run as administrator)." }
    foreach ($rule in @(@{ Name = "Literature Radar HTTPS"; Port = $HttpsPort }, @{ Name = "Literature Radar HTTP"; Port = $HttpPort })) {
        Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Protocol TCP -LocalPort $rule.Port `
            -Action Allow -Profile Private, Domain | Out-Null
        Write-Host "Firewall: inbound TCP $($rule.Port) allowed (Private, Domain)."
    }
}

Invoke-Compose @("config", "-q")
if ($Start) {
    Write-Host "Building and starting (the first build takes several minutes)..."
    Invoke-Compose @("up", "-d", "--build", "--wait")
    Invoke-Compose @("ps")
    $first = ($SiteAddress.Split(",")[0]).Trim()
    $suffix = ""
    if ($HttpsPort -ne 443) { $suffix = ":$HttpsPort" }
    Write-Host ""
    Write-Host "Open https://$first$suffix/ and sign in as $AdminEmail."
    Write-Host "Then remove RESEARCH_WEB_ADMIN_PASSWORD from deploy\.env, and run scripts\windows\trust-caddy-root.ps1"
    Write-Host "on each computer that should trust the certificate (see docs\deployment-windows.md)."
} else {
    Write-Host "Configuration is valid. Start with: docker compose -f deploy\docker-compose.yml up -d --build --wait"
}
