# Headless Linux server

The headless distribution runs Stimma without a desktop shell. Connect using the
Stimma desktop app on the same account and a reachable LAN or tailnet route.

Use the [Docker setup and downloadable Compose file](https://docs.stimma.ai/docker/).
Both Linux amd64 and arm64 use `ghcr.io/stimma-ai/stimma-headless:latest`.
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

Settings → About and Settings → Stimma Server show a **Connected server** panel
with app/base versions, update status, check/update actions and restart. Those
controls address the server hosting the library; the desktop updater continues
to manage the local desktop app separately.

The launcher checks on startup and starts the cached package if the update
service is unavailable. Optional `UPDATE_WINDOW=03:00-05:00` with `TZ` enables
nightly updates; omit it for startup/manual updates only. Running jobs are
allowed to finish before restart. A busy server defers a scheduled update once
the window closes. The headless runtime includes FFmpeg, Bash, Python, Git,
curl, jq, ripgrep and archive tools. No Docker socket or privileged container
is required.

Normal app updates use the same container image. When system libraries or the
bootstrap require an update, Settings explains the same-tag refresh:

```sh
docker compose pull && docker compose up -d
```

## Recovery

Back up the data volume while Stimma is stopped. Do not run `docker compose down
-v` unless deleting that volume is intended. The updater verifies signed
metadata and the package digest, stages a complete package and activates it
atomically. It retains the previous package and recent configuration/database
snapshots. If migration/startup fails after activation, it stops rather than
running old code against potentially incompatible data. Consult container logs
and `/data/app/activation.json` for the candidate, previous package and recovery
snapshot. Restore from a complete backup before clearing a failed activation;
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
