# Install on a Windows machine

The same Docker Compose stack as on Linux (`docs/deployment-docker.md`), run by Docker Desktop with the
WSL 2 backend. The scripts in `scripts\windows\` replace the Linux shell steps; they run in the Windows
PowerShell 5.1 that ships with Windows, or in PowerShell 7.

## 1. Requirements

- Windows 10 22H2 or Windows 11 (Pro, Enterprise or Home), x86_64, 4 CPU / 8 GB RAM / 30 GB free disk or more
  (Docker Desktop's WSL 2 VM takes up to half the RAM by default).
- Virtualisation enabled in the BIOS/UEFI; WSL 2: `wsl --install` in an elevated PowerShell, then reboot.
- [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) 4.27 or newer (Compose
  2.24+), "Use the WSL 2 based engine" on, **Linux containers** (the default; the tray menu offers "Switch to
  Linux containers..." if it was changed). Note Docker Desktop's licence terms for larger organisations.
- Git for Windows.
- A name or IP the browsers will use (e.g. `research.lan` in the LAN DNS, or the machine's fixed IP).
- Outbound HTTPS to the LLM providers and search APIs (directly or via a proxy, see section 8).

Windows Server is not supported by Docker Desktop. There, or for a machine without a desktop session, run
Docker Engine inside a WSL 2 Ubuntu and follow the Linux guide in that shell (section 9).

## 2. Get the code

```powershell
git clone <repo-url> research_agent
cd research_agent
```

The repository's `.gitattributes` keeps the files used inside containers (Caddyfile, compose file,
Dockerfile, shell scripts) at LF line endings whatever `core.autocrlf` says; the scripts check this and stop
with the fix if a checkout has CRLF.

## 3. Configure and start

In a PowerShell **Run as administrator** (needed only for `-OpenFirewall`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1 -AdminEmail admin@example.org -SignupDomains example.org -ContactEmail research@example.org -OpenFirewall -Start
```

What it does:

1. Checks Docker Desktop (engine running, Linux containers, Compose 2.24+) and the line endings.
2. Asks for the first admin's password (twice, 12 characters or more; never on the command line).
3. Writes `deploy\.env` from `deploy\.env.example` with a fresh `RESEARCH_SECRETS_KEY` (Fernet key) and
   `DB_PASSWORD`, UTF-8 without byte-order mark, readable by the current user only. `-SiteAddress` defaults to
   this computer's name and LAN IPv4 (e.g. `radar-pc, 192.168.1.20`). An existing `deploy\.env` is kept unless
   `-Force`.
4. `-OpenFirewall`: inbound TCP 443 and 80 allowed for the Private and Domain profiles (not Public). Set the
   LAN connection to Private in Settings -> Network.
5. `-Start`: builds the image and starts the stack (`up -d --build --wait`; the first build takes minutes).

**Back up `deploy\.env`** somewhere safe (a password manager or an encrypted share): losing
`RESEARCH_SECRETS_KEY` makes every saved user key unreadable.

Other options: `-HttpsPort 8443 -HttpPort 8080` when IIS or another program holds 443/80, `-SiteAddress
"research.lan, 192.168.1.20"`. Edit `deploy\.env` later in any editor that saves UTF-8 without BOM (VS
Code, Notepad on Windows 11), then `docker compose -f deploy\docker-compose.yml up -d`.

Then, as on Linux: open `https://<site address>/`, sign in as the admin, remove `RESEARCH_WEB_ADMIN_PASSWORD`
from `deploy\.env`, and check the sign-up domains and contact address in the app (`docs/deployment-docker.md`,
sections 3 and 4).

## 4. Certificates

With `CADDY_TLS=internal` (default) Caddy issues its own certificate; browsers warn until its root is trusted.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\trust-caddy-root.ps1
```

exports the root to `deploy\caddy-root.crt` (git-ignored) and trusts it on the server (machine store when
elevated, otherwise the current user's store). On every other Windows client, copy the `.crt` and the script
and run `trust-caddy-root.ps1 -CertFile .\caddy-root.crt`, or distribute the certificate by Group Policy or
Intune. macOS: double-click the `.crt` and set it to "Always Trust" in Keychain Access.

Your own certificate instead: put `cert.pem` (full chain) and `key.pem` in `deploy\certs\`, set
`CADDY_TLS='/certs/cert.pem /certs/key.pem'` in `deploy\.env`, then `docker compose -f deploy\docker-compose.yml up -d proxy`.

## 5. Keep it running

- Docker Desktop -> Settings -> General: **Start Docker Desktop when you sign in**. The services have
  `restart: unless-stopped`, so they come back with Docker Desktop.
- Docker Desktop runs in a user session: the computer needs that user signed in (a locked screen is fine).
  Turn off sleep for the server (Settings -> System -> Power: Never) and keep Windows Update's active hours
  in mind; after a reboot sign in once (or configure automatic sign-in by policy) for the stack to start.
- Resources: Docker Desktop -> Settings -> Resources (or `%UserProfile%\.wslconfig`, `[wsl2] memory=6GB`).
  The containers' limits are `API_MEMORY` (1g) and `WORKER_MEMORY` (2g) in `deploy\.env`.

## 6. Upgrade, backup, restore, smoke test

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\backup.ps1
git pull
docker compose -f deploy\docker-compose.yml up -d --build --wait
docker compose -f deploy\docker-compose.yml logs migrate
```

- `backup.ps1 [-OutDir D:\backups\radar]` writes `db.dump` and one `.tgz` per volume (default
  `deploy\backups\<stamp>`). Copy the folder off the machine; keep `deploy\.env` separately.
- `restore.ps1 -BackupDir <folder>` replaces the database and volumes (asks first; needs the same
  `deploy\.env`). Backups from `scripts/backup.sh` on Linux restore here too, and the other way round.
- `smoke.ps1` starts a throw-away copy of the stack on ports 18443/18080 (project `research-smoke`, its own
  volumes and network), checks health, the login page and a sign-in, and removes it. It can run beside the real
  deployment.
- A scheduled backup: Task Scheduler -> Create Task, "Run whether user is logged on or not" off (Docker
  Desktop needs the session), action `powershell.exe -ExecutionPolicy Bypass -File C:\path\research_agent\scripts\windows\backup.ps1 -OutDir \\nas\backups\radar`.

The other commands of `docs/deployment-docker.md` (import, create-admin, logs) work unchanged in
PowerShell with `deploy\docker-compose.yml`.

## 7. Host folders for evals and gold files (optional)

Set absolute paths with forward slashes in `deploy\.env`, e.g. `EVALS_DIR=C:/research/evals` and
`GOLD_DIR=C:/research/gold`. Folders on the Windows drive are slower inside containers than the default named
volumes; use them only for files you edit on Windows.

## 8. Troubleshooting (Windows)

- **`The Docker engine is not running`:** start Docker Desktop and wait for "Engine running".
- **Port 443 or 80 in use:** `netstat -ano | findstr ":443 "` shows the owning PID (often IIS, "World Wide
  Web Publishing Service"). Stop it or use other ports (`-HttpsPort`/`-HttpPort`, then `https://host:<port>/`).
- **`ports are not available` / `An attempt was made to access a socket in a way forbidden`:** Hyper-V
  reserved the port; `netsh interface ipv4 show excludedportrange protocol=tcp` lists the ranges. Pick a port
  outside them.
- **Other computers cannot connect:** the network profile must be Private (or Domain) for the firewall rules;
  check from a client with `Test-NetConnection <server> -Port 443`. A VPN client on the server can block LAN
  traffic.
- **`Pool overlaps with other one on this address space`:** another network uses `172.31.250.0/24`; set
  `EDGE_SUBNET` in `deploy\.env` to a free `/24`.
- **Outbound proxy:** set `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY=localhost,127.0.0.1,db,api` in
  `deploy\.env` (the worker uses them), and the same proxy in Docker Desktop -> Settings -> Resources -> Proxies
  for image pulls and the build.
- **`deploy\.env` edited and now every variable is "not set":** the file was saved with a byte-order mark or
  as UTF-16. Save it again as "UTF-8" (not "UTF-8 with BOM").
- **Line-ending error from a script:** the message gives the commands to re-checkout with LF.
- Everything in `docs/deployment-docker.md` section 9 applies as well.

## 9. Without Docker Desktop (WSL 2 Ubuntu)

For Windows Server, or to avoid Docker Desktop: `wsl --install -d Ubuntu`, install Docker Engine inside
Ubuntu (docs.docker.com/engine/install/ubuntu), clone the repository **inside the Linux file system**
(`~/research_agent`, not `/mnt/c`), and follow `docs/deployment-docker.md` with the bash scripts. For LAN
access turn on mirrored networking (`%UserProfile%\.wslconfig`: `[wsl2]` `networkingMode=mirrored`, then
`wsl --shutdown`) and open 443/80 in the Windows firewall. WSL starts a distribution only on demand and may
stop it when idle: enable systemd in the distribution so Docker starts with it, arrange for it to start at
boot (see Microsoft's WSL documentation for the current options), and check after a reboot that the site
answers.
