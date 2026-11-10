<#
.SYNOPSIS
    Throw-away smoke test of the Docker stack on Windows: own project name, own ports, own volumes; removed at
    the end. The Windows twin of scripts/docker_smoke.sh.

.DESCRIPTION
    powershell -ExecutionPolicy Bypass -File scripts\windows\smoke.ps1 [-HttpsPort 18443] [-HttpPort 18080]

    Leaves the real deployment (project "research-agent") untouched. Uses curl.exe (part of Windows 10 1803+).
#>
[CmdletBinding()]
param([int] $HttpsPort = 18443, [int] $HttpPort = 18080)

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Docker
Assert-LfCheckout

$work = Join-Path ([IO.Path]::GetTempPath()) ("radar-smoke-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
$smokeEnv = Join-Path $work "env"
$before = @("-p", "research-smoke", "--env-file", $smokeEnv)
$password = "smoke-" + (New-HexSecret 8)
Write-Utf8NoBom $smokeEnv @(
    "RESEARCH_SECRETS_KEY=$(New-FernetKey)",
    "DB_PASSWORD=$(New-HexSecret 16)",
    "RESEARCH_WEB_ADMIN_EMAIL=admin@example.org",
    "RESEARCH_WEB_ADMIN_PASSWORD=$password",
    "RESEARCH_WEB_SIGNUP_DOMAINS=example.org",
    "SITE_ADDRESS=localhost",
    "CADDY_TLS=internal",
    "HTTPS_PORT=$HttpsPort",
    "HTTP_PORT=$HttpPort",
    # a different edge subnet, so the smoke stack can run beside the real one
    "EDGE_SUBNET=172.31.251.0/24"
)

$base = "https://localhost:$HttpsPort"
try {
    Invoke-Compose @("config", "-q") $before
    Invoke-Compose @("up", "-d", "--build", "--wait") $before
    $health = Get-NativeOutput "curl.exe" @("-fsSk", "$base/api/v1/health")
    if ($health.Code -ne 0 -or "$($health.Output)" -notmatch '"ok"') { throw "health check failed" }
    Write-Host "health ok"
    $page = Get-NativeOutput "curl.exe" @("-fsSk", "$base/login")
    if ($page.Code -ne 0 -or "$($page.Output)" -notmatch "<html") { throw "login page failed" }
    Write-Host "login page ok"
    $body = Join-Path $work "login.json"
    Write-Utf8NoBom $body @("{""email"":""admin@example.org"",""password"":""$password""}")
    $login = Get-NativeOutput "curl.exe" @("-sSk", "-o", "NUL", "-w", "%{http_code}", "-X", "POST",
        "-H", "content-type: application/json", "--data-binary", "@$body", "$base/api/v1/auth/login")
    if ("$($login.Output)".Trim() -ne "200") { throw "login POST answered $($login.Output)" }
    Write-Host "login POST: 200"
    Invoke-Compose @("ps") $before
    Write-Host "smoke passed; tearing down"
} finally {
    $null = Get-NativeOutput "docker" (@("compose") + $before + @("-f", $ComposeFile, "down", "-v", "--remove-orphans"))
    Remove-Item -Recurse -Force -LiteralPath $work
}
