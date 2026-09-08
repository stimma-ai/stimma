# Windows installer regression validation

## What failed

Real Canary testing on 2026-09-06 reproduced these failures:

- Uninstalling a running archive-runtime build (971) left its Python backend
  and multiprocessing worker running outside the application directory.
- A subsequent install, including the published 971 to 972 transition, could
  fail with "Stimma Canary cannot be closed" after its window disappeared.
- Recovery after an incomplete uninstall could leave two runtime transport
  archives in `resources`. The shell required exactly one and exited instead
  of starting the backend.

The installer now finds processes belonging to its exact installation,
including legacy Python command lines referencing its backend. The watchdog
owns its descendants in a Windows kill-on-close job, so forcibly terminating
it also terminates Python and workers. Each new build names its runtime archive
in packaged metadata; successful installer preparation removes obsolete
transport archives. Extracted shared runtimes are not pruned by this change.

## Test the physical installation

Use published installers and the normal `Stimma Canary` installation, default
profile, and shared runtime. Obtain explicit permission before resetting a
developer's profile. Preserve data in named backups when testing fresh state.

**Do not trust logical AppData paths alone.** A test launched from a packaged
Windows application can inherit MSIX filesystem virtualization. The normal
`LOCALAPPDATA` string can then resolve to the host application's `LocalCache`
instead of the physical desktop installation. This can make an installer,
Explorer-launched app, and diagnostic command observe different versions.

Launch installers and read-only probes from the ordinary interactive desktop
user context (for this run, a temporary interactive Task Scheduler task).
Write diagnostic results into the checkout, outside virtualized AppData.
Observe installer prompts and the final application with computer use.
Verify the physical executable version, archive names, backend startup log,
and process command lines from that same ordinary desktop context. Remove
temporary tasks when finished.

The original uninstaller process can exit before its temporary NSIS child
finishes. Do not treat that process's exit code as uninstall completion:
wait for the UI to finish and verify the executable and backend processes
are gone before resetting data or starting another installer.

## Required cases

1. Published loose runtime to archive runtime: 969 -> 970 -> 971.
   Inspection confirmed that **both 969 and 970 contain loose runtimes**;
   971 is the first archive build in this sequence.
2. Published archive to archive: 971 -> 972, with the application running.
3. Recovery from the reproduced orphaned-backend/incomplete-uninstall state.
4. Two manually packaged fixed builds installed consecutively while running.
5. Uninstall a running fixed build; verify no backend/worker survives.
6. Fresh install with no app directory, profile, shared runtime, or updater
   cache; verify backend startup and onboarding, not merely installer exit.

Record installer duration separately from backend/UI readiness. Manual prompt
delays are included in wall-clock measurements unless explicitly subtracted.
Cached-runtime timings are not fresh-install timings. The first transition
from loose files still has to remove thousands of old files.

## Results on the Windows test machine

All rows used the physical Canary installation. Successful rows were checked
in the actual UI and backend startup logs, not just by installer exit code.

| Case | Result | Installer wall time |
| --- | --- | --- |
| 969 install, empty app directory but existing profile | Pass | 106.5 s |
| 969 -> 970 | Pass | 141.6 s, including manual prompt delay |
| 970 -> 971 | Pass | 56.6 s, including manual prompt delay |
| 971, completely fresh state | Pass; onboarding | 21.4 s |
| Running 971 uninstall then reinstall | Reproduced orphan Python / cannot-close failure | Failed; no meaningful success timing |
| Running 971 -> published 972 | Reproduced same cannot-close failure | Failed; no meaningful success timing |
| Fixed test.2 recovery from incomplete install with stale archive | Pass | 11.7 s with runtime cached |
| Fixed test.2 recovery after the published 972 failure | Pass | 42.9 s, including manual prompt delay and new runtime extraction |
| Running fixed test.2 -> fixed test.3 | Pass; backend starts | 32.4 s total; 18.8 s after accepting close prompt |
| Running fixed test.3 uninstall | Pass; no surviving Canary backend/worker | Not benchmarked |
| Fixed test.3, completely fresh state | Pass; onboarding | 18.9 s |

For the final fresh run, runtime preparation took 10.2 s within the installer;
backend `Application startup complete` arrived 33.0 s after installer start
(14.1 s after installer exit). Do not describe the 18.9 s as total time to a
ready backend.

The final machine installation is `1.0.14-canary.972-test.3`, with a fresh
default profile. Previous physical profiles/runtime/cache were moved to
named sibling backups. These measurements are individual local runs, not a
cross-hardware performance guarantee. Local test builds do not publish updates.

Automated checks: shell build passed; 29 unit tests passed (10 unrelated TLS
tests skipped because OpenSSL was unavailable); forced-watchdog-termination
regression passed. The Rust release test target compiled successfully but
contains no Rust unit tests.

## Local build and automated regressions

The normal CLI build stamps `stimmaPythonRuntimeArchive` into package metadata.
For rapid shell/watchdog iterations after staging a real Canary build:

```powershell
cd src-tauri/watchdog
cargo build --release
cd ../../electron
npm run build
node scripts/build-real-canary-test.mjs 1.0.14-canary.972.test.2 out-real-canary-test
node scripts/build-real-canary-test.mjs 1.0.14-canary.972.test.3 out-real-canary-test-3
npm run test:unit
npm run test:watchdog-windows
```

The helper reuses staged backend/frontend resources and preserves the real
Canary identity/location. It does not publish anything. A local build without
an update-feed URL does not test feed delivery or the in-app update button;
manually running its installer tests replacement and process cleanup.

For in-app validation, set `STIMMA_UPDATE_BASE_URL=https://updates.stimma.ai`
when invoking the helper, and build the frontend with its normal Canary update
endpoint enabled. Keep the test build's numeric Canary component below the
published target. Use `canary.981.test.1`, **not** `canary.981-test.1`: the latter
makes `981-test` a nonnumeric semver identifier that sorts after numeric `982`,
and downgrade protection correctly refuses the update.

## In-app update regression (2026-09-07)

Manual installer replacement did not cover the user's actual workflow. On
published 979, the actual `Update this PC` button failed with `No update
available` despite repeated successful checks finding 982. On Windows the UI
retains an update handle without downloading yet. A repeated check returns a
duplicate handle; closing it incorrectly erased Electron's shared availability.
The UI then retained a button pointing at no available update. Replacing a
staged version could trigger the same problem when closing the superseded handle.

Electron handle closure is now a no-op: only an update check changes shared
availability. Downloaded state remains independent. Failed user-initiated
installation or relaunch now shows a persistent error toast, also broadcast to
other profile windows so the originating window sees a failure.

Required proof is the actual UI workflow on the normal installation and
published feed: let an update become available, perform repeated checks
(including an unchanged scheduled check), click the top-bar `Update this PC`,
observe download/installer/relaunch, and verify the new executable version and
backend readiness. Installer-only tests and an immediate first-check click are
not substitutes for this sequence.

First live result: fixed `981.test.1` found published 982 at 00:49:37,
00:50:41, and 00:51:05 UTC on September 8 (the latter two via About-page
navigation). Clicking the top-bar button at 00:51:49 downloaded 982 by
00:51:56 and launched the cached installer with `--updated --force-run`.
The physical executable became 982 and backend startup completed at 00:52:28;
the normal application UI was verified after relaunch. No installer was
manually launched for that transition. The unpublished starting build had no
remote blockmap, so the updater correctly fell back to a full download.

The watchdog regression deliberately kills only the watchdog (without
`taskkill /T`) and asserts both backend and grandchild die. Runtime selection
tests cover stale archives and refusal to substitute a stale archive when the
build's declared archive is missing.
