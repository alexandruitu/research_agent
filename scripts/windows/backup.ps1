<#
.SYNOPSIS
    Back up the Docker deployment on Windows: a pg_dump of the database plus tarballs of the data volumes.

.DESCRIPTION
    powershell -ExecutionPolicy Bypass -File scripts\windows\backup.ps1 [-OutDir D:\backups\radar]

    Default folder: deploy\backups\<yyyyMMdd-HHmmss>. The dump is written inside the db container and copied
    out with "docker compose cp" (a PowerShell '>' redirect would re-encode the binary dump and corrupt it).
    deploy\.env is not included: keep RESEARCH_SECRETS_KEY in a separate safe place.
    Restore: scripts\windows\restore.ps1.
#>
[CmdletBinding()]
param([string] $OutDir = "")

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Docker

if ($OutDir -eq "") { $OutDir = Join-Path $RepoRoot ("deploy\backups\" + (Get-Date -Format "yyyyMMdd-HHmmss")) }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

Write-Host "database -> $OutDir\db.dump"
Invoke-Compose @("exec", "-T", "db", "pg_dump", "-U", "research", "-d", "research", "--format=custom", "-f", "/tmp/db.dump")
try {
    Invoke-Compose @("cp", "db:/tmp/db.dump", (Join-Path $OutDir "db.dump"))
} finally {
    Invoke-Compose @("exec", "-T", "db", "rm", "-f", "/tmp/db.dump")
}

foreach ($volume in $Volumes) {
    $name = "${Project}_$volume"
    $probe = Get-NativeOutput "docker" @("volume", "inspect", $name)
    if ($probe.Code -ne 0) { continue }
    Write-Host "volume $volume -> $OutDir\$volume.tgz"
    Invoke-Native "docker" @("run", "--rm", "-v", "${name}:/v:ro", "-v", "${OutDir}:/backup", "alpine",
        "tar", "czf", "/backup/$volume.tgz", "-C", "/v", ".")
}
Write-Host "done: $OutDir (keep a copy of deploy\.env elsewhere: saved user keys need RESEARCH_SECRETS_KEY)"
