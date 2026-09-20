# Stimma Server

Stimma Server runs on Linux without a desktop shell. Connect using the
Stimma desktop app on the same account and a reachable LAN or tailnet route.

Use the [Docker setup and downloadable Compose file](https://docs.stimma.ai/docker/).
Both Linux amd64 and arm64 use `ghcr.io/stimma-ai/stimma-server:latest`.
The bootstrap also has explicit version tags; its installed version appears in
Settings alongside the connected server's Stimma version.

The default Compose file uses Linux host networking. Stimma advertises the
host's LAN and VPN addresses automatically and refreshes them as interfaces
change. Clients try those routes with pinned TLS; users do not maintain an IP
list. Tailscale must run on the host to expose its interface to Stimma.

The authenticated server prefers TCP 9193; if occupied, it advertises an
available port. The private backend uses a free loopback port in base 1.0.2+.
Host networking shares the host's network namespace, so `ports:` mappings do
not apply. Network routes and firewall access are still required.

## Operation

```sh
docker compose up -d
docker compose logs -f stimma
docker exec stimma stimma-server status
docker exec stimma stimma-server login
docker exec stimma stimma-server check
docker exec stimma stimma-server update
docker exec stimma stimma-server restart
```

First startup downloads a signed runtime package and displays a short activation
code. Approve it at the displayed URL in a browser on any device. Login and
server identity persist in `/data/state`. Runtime packages live in `/data/app`,
model caches in `/data/cache`. Keep the volume when replacing the container.
One running server owns each volume. External source folders can be mounted
read-only. Store SQLite databases on suitable local storage.

Settings → Stimma Server shows the server hosting your library in a named card
with app/base versions, update status, check/update actions and restart. About
shows only the local app. The top-bar update pill includes available server
updates; **Update all** updates the server and this machine in one click.

The launcher checks on startup and starts the cached package if the update
service is unavailable. Optional `UPDATE_WINDOW=03:00-05:00` with `TZ` enables
nightly updates; omit it for startup/manual updates only. Manual updates and
restarts begin immediately. Scheduled updates wait for active work to finish.
A busy server defers a scheduled update once
the window closes. The headless runtime includes FFmpeg, Bash, Python, Git,
curl, jq, ripgrep and archive tools. No Docker socket or privileged container
is required.

Normal app updates use the same container image. When system libraries or the
bootstrap require an update, Settings explains the same-tag refresh:

```sh
docker compose pull && docker compose up -d
```

## Direct MCP connections

Agents can connect directly without a desktop relay. In the desktop app connected
to this server, open **Settings → MCP → Direct connections**, choose the server's
VPN or LAN IP and port, and click **Apply**. Enable MCP for the desired profile
and create a named connection. Copy its **Direct to server** URL and key.

For setup entirely from the shell (bootstrap **1.0.7+** and a runtime with direct
MCP support):

```sh
docker exec stimma stimma-server mcp status
docker exec stimma stimma-server mcp configure --host 100.64.0.10 --port 9194
docker exec stimma stimma-server mcp enable --profile PROFILE_ID
docker exec stimma stimma-server mcp connect --profile PROFILE_ID --name "Remote agent"
```

Replace the example IP with the server's own Tailscale address. `status` lists
profile IDs and detected addresses; omitting `--profile` selects the first
profile. `connect` prints a one-time connection key and `direct_endpoint`.
Configure the agent for Streamable HTTP with that URL and
`Authorization: Bearer <credential>`. Keep the key private. Profiles with a PIN
still require the usual MCP unlock. Existing keys work through either route.

`mcp configure --off` stops the direct listener installation-wide;
`mcp disable --profile PROFILE_ID` disables MCP for just that profile.
Configuration persists and applies without restarting the backend. The direct
listener defaults to loopback and port 9194; select a specific network address
for remote agents. It uses HTTP over your trusted network or encrypted VPN and
exposes only MCP and signed media transfers. The normal device listener remains
separate. Refresh the container image to obtain the new CLI when using an older
bootstrap; Settings can configure the listener on base 1.0.6 as well.

## Recovery

Back up the data volume while Stimma is stopped. Do not run `docker compose down
-v` unless deleting that volume is intended. The updater verifies signed
metadata and the package digest, stages a complete package and activates it
atomically. It retains the previous package and recent configuration/database
backups (the latest three after a successful update). These contain databases
and settings, not media. If migration/startup fails after activation, it stops rather than
running old code against potentially incompatible data. Consult container logs
and `/data/app/activation.json` for the candidate, previous package and recovery
backup. Restore from a complete backup before clearing a failed activation;
do not point an old executable at migrated databases.

## Building

Use `tools/stimma headless package --version VERSION --branch production` on
Linux to build the standalone Python runtime package, and
`tools/stimma headless image` to build the bootstrap. The runtime package embeds
its interpreter and native Python dependencies. The bootstrap's trust root is
`packaging/headless/updater.pub`; release CI uses the configured public release
signing key. Test with `tools/stimma headless test` and
`tools/stimma headless smoke` (Docker and a built package required).

Release CI publishes packages for both architectures. Bootstrap CI runs only
when bootstrap files change or on manual dispatch; each base change must bump
`packaging/headless/VERSION`. Existing version tags should never be repurposed
for different base contents. The signed runtime manifest declares its minimum
and recommended bootstrap versions so incompatible packages are blocked.

## Local document rendering

Base 1.0.6 adds one Chromium headless shell and its pinned Playwright runtime.
SVG/layout thumbnails, agent inspection and rasterization run on the server,
including when no desktop or browser client is connected. No browser is
installed or downloaded at runtime. A separate full Chromium is not included.

Use the supplied `packaging/headless/compose.yaml` together with
`packaging/headless/render-seccomp.json` in the same directory. The seccomp
profile allows Chromium to create its user namespace sandbox while retaining
Docker's other syscall restrictions. The host must support unprivileged user
namespaces. Existing Compose installations need this configuration addition
when upgrading to base 1.0.6; a container-image refresh alone does not update
Compose files. No privileged mode or Docker socket is needed.

Run `tools/stimma render-test --docker stimma-server:test` after building the
image to verify real captures with network access disabled. Desktop rendering
uses the installed Electron executable; `tools/stimma render-test` verifies it.
Use `tools/stimma render-test --executable FILE` to test a built desktop app.
