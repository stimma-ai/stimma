# Stimma mobile

The iOS app is a native Swift/WKWebView client for an existing Stimma Server.
It bundles only welcome, login, server selection, and recovery. The main UI is
downloaded from the selected server and cached on the phone; no Python backend
runs on the phone.
Welcome and server selection use the shared Vue components and styling; only
authentication opens the system browser.

## Development

Requires Xcode with an iOS simulator runtime, XcodeGen, Node/npm, and the normal
Stimma CLI prerequisites. Minimum iOS version: 17.

```sh
tools/stimma mobile ios doctor
tools/stimma mobile ios run --simulator 'iPhone 17 Pro'
tools/stimma mobile ios test
```

The run command builds the shell frontend, generates the Xcode project, builds the
app with local ad-hoc signing and simulator-only Keychain entitlements,
installs it, and opens the simulator. No Apple account is needed. Add
`--skip-frontend` for native-only iterations. Generated projects, web assets,
build logs, and signing state stay ignored.

Sign in through the system browser using the same account as the server, then
select the server. LAN or an existing Tailscale connection must provide the
route. Authentication uses the existing desktop browser callback protocol;
device activation codes are not used. Refresh tokens live in this phone's
Keychain. Native authentication requests use a separate ephemeral URLSession
with no cookie, credential, or response-cache storage. Signing out does not
sign the home server out.

## Server UI packages

Build/publish the UI beside the source backend:

```sh
tools/stimma mobile ios package
```

Use `--skip-frontend` to package an already completed frontend build. The
command generates `backend/mobile-ui/manifest.json` and an immutable gzip/USTAR
archive under `packages/<sha256>.tar.gz`. Electron and headless release builds
perform this step before copying the backend. `STIMMA_UI_PACKAGE_DIR` can
select another published directory for development.

The authenticated remote surface exposes `/api/mobile-ui/manifest` and
`/api/mobile-ui/packages/<hash>.tar.gz`. These are profile independent but
remain behind the remote session gate. The manifest supports ETag validation;
archives are immutable and old hashes remain available during live rebuilds.

On app launch or explicit server selection the shell checks the manifest and requires package format,
bridge, and API version 1. A verified cache hit needs no archive transfer. A
missing package downloads over the pinned server connection, is hash checked
and safely unpacked, then installed atomically. The current session uses one
immutable directory; it is never overwritten by an update. The next launch or selection
checks the server again. Unsupported servers show an update/recovery message;
there is no implicit fallback to an older, potentially incompatible interface.

The cache holds at most 256 MiB of archives, extracted files, and metadata,
evicting least-recently-used versions while protecting the running interface.
Prior versions remain while space permits. Packages are capped at 64 MiB
compressed and 128 MiB extracted, with 10,000 files. Archive links, unsafe paths,
collisions, and special files are rejected. The OS may also purge the cache;
the next connection will redownload any missing package.

## Physical iPhone

Add the intended organization account in Xcode Settings → Accounts. Connect
and trust the phone, enable Developer Mode, and run:

```sh
tools/stimma mobile ios device --team TEAM_ID --device DEVICE_ID
```

Alternatively set `STIMMA_APPLE_TEAM` locally. The command allows Xcode to
manage development provisioning and device registration, then installs and
launches the app. Never commit account details, team overrides, credentials,
or provisioning profiles. This command builds a development app; it does not
upload to TestFlight or submit to the App Store.

## Isolated simulator validation

A Debug simulator build can use an isolated loopback backend:

```sh
tools/stimma mobile ios run --simulator 'iPhone 16 Pro' --local-backend-port 9480
```

Build its package and start the isolated backend through the usual sandbox
CLI first (global `--sandbox NAME` precedes `run backend`). The
plain-HTTP shortcut is compiled out of physical-device and Release builds.
It cannot choose a non-loopback host. This test library is not a substitute for
validating account login and Tailscale.

The iOS account menu includes **Disconnect from server** and **Sign out**.
Disconnect closes the remote transport, clears the remembered server and returns
to server selection while retaining account sign-in. Sign out also removes the
phone's saved account credentials. Neither action signs the server itself out.

The shell saves `localStorage` preferences in Application Support, separately for
each account and server. Profile selection, theme, saved routes, and other local
preferences are restored at document start, before the UI reads them, even when
the loopback port or UI package changes. Writes and deletions are saved as they
happen; reloads receive the latest snapshot. Disconnect and sign-out retain these
preferences for that account/server. Cookies, `sessionStorage`, IndexedDB, and
other WebView data remain temporary. Preferences lost by older shells cannot be
recovered; this fix requires rebuilding the native iOS app.

`tools/stimma mobile ios test` checks the bridge contract and runs disposable
TLS/HTTP/WebSocket fixtures. It covers wrong-pin rejection, upload streaming,
media byte ranges, bidirectional WebSockets, callback-independent native
credential injection, cookie/origin restrictions, and invalid request framing. Auth callback tests use real IPv4 and IPv6 sockets
and verify state validation, single delivery, and complete HTTP responses.
Package tests cover corruption, unsafe archives, compatibility, cache hits,
cancellation, atomic replacement, and eviction.
Local preference tests cover file persistence and account/server isolation, plus
document-start restoration and Web Storage mutations in Chromium. Install the
frontend dependencies and Playwright Chromium before running this lane. The
`iOS checks` workflow runs these checks on macOS and compiles the iOS shell.

`tools/stimma mobile ios test-ui --simulator 'iPhone 16 Pro'` additionally runs
XCTest against the app. Its library test expects an isolated backend on port
9480 with at least one asset. It opens browser sign-in without entering any
credentials, checks navigation from Home into the asset browser, and verifies
Keychain create/read/update across app launches using an isolated dummy item.
It also probes the live authentication endpoints with deliberately invalid
credentials, checking HTTP responses for exchange, Firebase sign-in/refresh,
account, and device discovery. This does not create an authenticated session.

Debug simulator builds use a fresh browser authentication session because iOS 18
simulator shared sessions can fail before loading the sign-in page. Physical
devices keep Safari sign-in reuse. The app retains its own sign-in in Keychain
in both cases.

## Boundaries and current limits

- The native transport pins the server certificate from the authenticated
  account registry and injects its session into API/media/WebSocket requests.
  Browser JavaScript never receives either credential. The loopback listener
  requires an HttpOnly capability cookie and validates Host and Origin.
- Native commands accept only the main app document. Generated layout frames
  disable scripts on iOS. Provider-management web panels (ComfyUI, Draw
  Things) load as same-origin subframes through the `/api/provider-manage/`
  proxy; they get no native bridge. A WebKit content rule prevents
  cookie-bearing requests to another loopback port.
- The phone bypasses desktop onboarding and has no local-server option. Server
  profile PIN checks remain intact. Connection checks run while active and
  after resuming, with one five-second probe at a time through the same local
  listener, pinned upstream, and session used by the WebView. Backgrounding
  closes transport sockets; foregrounding recreates the listener on the same
  port and explicitly reconnects the UI WebSocket after the probe succeeds.
  This resume fix requires an updated native iOS app and server UI package.
  Recovery refreshes
  discovery and reestablishes the server session without replacing the page
  or its current UI package. Select a server explicitly or relaunch the app
  to pick up a new UI package.
- One native loading cover spans automatic restoration and WebView startup.
  After 4.5 seconds it adds a waiting message and an off-ramp to server selection.
  The web UI sends `interfaceReady` after startup routing and rendering finish;
  only then is the page revealed. WebView backgrounds match the dark shell.
  Failures expose the connection screen and their error.
- Server builds must include a mobile UI package. Older installed servers need
  an update before this shell can connect; UI packages cannot add native APIs.
- Uploads require Content-Length and are limited to 1 GiB. Share-sheet exports
  currently pass bytes through the bridge and are limited to 64 MiB. Native
  dictation, background transfers, push notifications, and Android are not
  implemented.
- Bootstrap uses URLSession with pinned TLS and local-network ATS permission.
  Literal LAN/Tailscale IP routes are the current target; fully qualified host
  routes need additional trust/ATS verification before being advertised as
  supported.
- This is a development shell, not a store-ready distribution. Store metadata,
  payment/account-management surfaces, distribution signing, and device-level
  acceptance still need their release pass.
