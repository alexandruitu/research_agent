# Shared helpers for the Windows scripts (dot-sourced). Windows PowerShell 5.1 compatible, ASCII only.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 3.0

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile = Join-Path $RepoRoot "deploy\docker-compose.yml"
$EnvFile = Join-Path $RepoRoot "deploy\.env"
$Project = "research-agent"
$Volumes = @("runs", "cache", "uploads", "evals", "gold", "caddydata")

function Invoke-Native {
    # Run a native command and stop on a non-zero exit code (PowerShell 5.1 does not do this by itself).
    param([Parameter(Mandatory = $true)][string] $Command, [string[]] $Arguments = @())
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Command $($Arguments -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Compose {
    param([string[]] $Arguments, [string[]] $Before = @())
    Invoke-Native "docker" (@("compose") + $Before + @("-f", $ComposeFile) + $Arguments)
}

function Get-NativeOutput {
    # Output and exit code of a native command, stderr dropped. In PowerShell 5.1 a redirected stderr line
    # becomes an error record, which "Stop" would turn into an exception, hence the local preference.
    param([Parameter(Mandatory = $true)][string] $Command, [string[]] $Arguments = @())
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command @Arguments 2>$null
        return @{ Output = $output; Code = $LASTEXITCODE }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Assert-Docker {
    # Docker Desktop must run Linux containers (WSL 2 backend), and Compose must read env_file "required".
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker was not found. Install Docker Desktop (WSL 2 backend) and open a new terminal."
    }
    $os = Get-NativeOutput "docker" @("version", "--format", "{{.Server.Os}}")
    if ($os.Code -ne 0) { throw "The Docker engine is not running. Start Docker Desktop and wait until it is ready." }
    if ("$($os.Output)".Trim() -ne "linux") {
        throw "Docker runs Windows containers. In the Docker Desktop tray menu choose 'Switch to Linux containers...'."
    }
    $compose = Get-NativeOutput "docker" @("compose", "version", "--short")
    if ($compose.Code -ne 0) { throw "The Docker Compose plugin is missing. Update Docker Desktop." }
    $version = "$($compose.Output)".Trim()
    $parts = ($version -replace "^v", "").Split(".")
    if ([int]$parts[0] -lt 2 -or ([int]$parts[0] -eq 2 -and [int]$parts[1] -lt 24)) {
        throw "Docker Compose $version is too old (2.24 or newer is needed). Update Docker Desktop."
    }
}

function Assert-LfCheckout {
    # These files are read inside Linux containers; a CRLF checkout breaks them in confusing ways.
    foreach ($name in @("deploy\Caddyfile", "deploy\docker-compose.yml", "deploy\Dockerfile")) {
        $bytes = [System.IO.File]::ReadAllBytes((Join-Path $RepoRoot $name))
        if ([Array]::IndexOf($bytes, [byte]13) -ge 0) {
            throw ("$name has Windows (CRLF) line endings. Re-checkout with the repository's .gitattributes: " +
                "git config core.autocrlf false; git rm -rq --cached .; git reset -q --hard " +
                "(this discards uncommitted changes in the clone).")
        }
    }
}

function New-RandomBytes([int] $Count) {
    $bytes = New-Object byte[] $Count
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return , $bytes
}

function New-FernetKey {
    # A Fernet key is 32 random bytes in url-safe base64 (with padding), as Fernet.generate_key() makes it.
    return [Convert]::ToBase64String((New-RandomBytes 32)).Replace("+", "-").Replace("/", "_")
}

function New-HexSecret([int] $Bytes = 24) {
    return -join ((New-RandomBytes $Bytes) | ForEach-Object { $_.ToString("x2") })
}

function Write-Utf8NoBom([string] $Path, [string[]] $Lines) {
    # Compose reads the first variable name wrong if the file starts with a byte-order mark, and
    # Set-Content -Encoding UTF8 in PowerShell 5.1 writes one. LF line endings, like the template.
    $text = ($Lines -join "`n") + "`n"
    [System.IO.File]::WriteAllText($Path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Protect-File([string] $Path) {
    # Only the current user (and SYSTEM, for backups) may read the file: it holds the database password and the
    # key that encrypts every saved user key.
    $user = "$env:USERDOMAIN\$env:USERNAME"
    Invoke-Native "icacls" @($Path, "/inheritance:r", "/grant:r", "${user}:(R,W)", "/grant:r", "*S-1-5-18:(R)") | Out-Null
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}
