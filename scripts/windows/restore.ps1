<#
.SYNOPSIS
    Restore a backup made by backup.ps1 (or scripts/backup.sh) into this machine's Docker deployment.

.DESCRIPTION
    powershell -ExecutionPolicy Bypass -File scripts\windows\restore.ps1 -BackupDir deploy\backups\20261110-093000

    Needs the same deploy\.env as the backed-up machine (RESEARCH_SECRETS_KEY decrypts the saved user keys).
    REPLACES the database and the contents of every volume found in the backup. Asks before doing so unless
    -Yes is given. The database refers to run folders by path, so database and runs are restored together.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string] $BackupDir,
    [switch] $Yes
)

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Docker

$BackupDir = (Resolve-Path $BackupDir).Path
$dump = Join-Path $BackupDir "db.dump"
if (-not (Test-Path -LiteralPath $dump)) { throw "No db.dump in $BackupDir" }
if (-not (Test-Path -LiteralPath $EnvFile)) { throw "deploy\.env is missing: restore it first (same RESEARCH_SECRETS_KEY)." }
if (-not $Yes) {
    $answer = Read-Host "This replaces the current database and volumes with $BackupDir. Type RESTORE to continue"
    if ($answer -ne "RESTORE") { Write-Host "Cancelled."; exit 1 }
}

Invoke-Compose @("up", "-d", "--wait", "db")
Invoke-Compose @("stop", "api", "worker", "proxy")
Invoke-Compose @("cp", $dump, "db:/tmp/db.dump")
try {
    Invoke-Compose @("exec", "-T", "db", "pg_restore", "-U", "research", "-d", "research", "--clean", "--if-exists",
        "--no-owner", "/tmp/db.dump")
} finally {
    Invoke-Compose @("exec", "-T", "db", "rm", "-f", "/tmp/db.dump")
}

foreach ($volume in $Volumes) {
    $archive = Join-Path $BackupDir "$volume.tgz"
    if (-not (Test-Path -LiteralPath $archive)) { continue }
    Write-Host "volume $volume <- $archive"
    # app volumes belong to the image's user (uid 10001); Caddy runs as root and keeps root ownership
    $owner = "10001:10001"
    if ($volume -eq "caddydata") { $owner = "0:0" }
    Invoke-Native "docker" @("run", "--rm", "-v", "${Project}_${volume}:/v", "-v", "${BackupDir}:/b:ro", "alpine",
        "sh", "-c", "find /v -mindepth 1 -delete && tar xzf /b/$volume.tgz -C /v && chown -R $owner /v")
}
Invoke-Compose @("up", "-d", "--wait")
Write-Host "Restored from $BackupDir."
