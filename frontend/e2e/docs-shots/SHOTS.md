# Shot log

One row per captured screenshot: what it shows, how it was staged, and where
it was published. Specs in `shots/` are the executable record; this file is
the human-readable index. All shots: light theme, 1480x940 @2x, docs-demo
sandbox (see README.md). First captured 2026-06-12.

Published = copied into `stimma-cloud/packages/docs/src/assets/` and wired
into a page. Inventory refs point at the docs repo's SCREENSHOT_INVENTORY.md.

| Shot (out/…) | Spec | Staging | Published as |
|---|---|---|---|
| getting-started/onboarding.png | 05-onboarding | Clean storage state so the onboarding gate engages; theme forced light via init script. | getting-started/onboarding.png → getting-started page |
| getting-started/first-generation.png | 02-tools | Reset tool state, type prompt, Run, wait ~18s for the stage hero. Ollama configured so suggestion chips render instead of an error. | getting-started/first-generation.png → getting-started page |
| tools/tool-panel-flux.png | 02-tools | Reset tool state, type prompt, expand the Advanced group (steps/guidance/sampler in frame). | tools/tool-panel.png → tool-panel page |
| tools/tool-picker-open.png | 02-tools | Click the tool-name header to open the hop-to menu. Sparse with only demo tools — NOT published; revisit with more tools registered. | — |
| tools/all-tools.png | 02-tools | /tools view with the demo provider's five tools. | tools/all-tools.png → tools overview |
| tools/post-processing-chain.png | 03-postprocessing | Reset state; build 4x-UltraSharp + Levels + Vignette via the real Add step menu; expand a step. | tools/post-processing-chain.png → post-processing page |
| tools/post-processing-add-menu.png | 03-postprocessing | Open Add step menu after scrolling the panel for popover room. | tools/post-processing-add-menu.png → post-processing page |
| tools/post-processing-progress.png | 03-postprocessing | Run with a 2-step chain; wait for the job tile (provider paced via STIMMA_DEMO_DELAY=0.5), shoot mid-run. | tools/post-processing-progress.png → post-processing page |
| tools/post-processing-done.png | 03-postprocessing | Same run, after completion (companion). | — (alt take) |
| settings/tool-providers.png | 04-settings | open-settings event → 'tools'. Provider is WebSocket so no filesystem paths appear. | tools/tool-providers.png → STP page |
| settings/stimpacks.png | 04-settings | open-settings → 'stimpacks'. Shows the 3 auto-installed marketplace stimpacks. | prompt-engineering/stimpacks-settings.png → PE stimpack page |
| settings/llm-services.png | 04-settings | open-settings → 'ai-services'; clicks Test connection and waits for the green capability badges (text/thinking/tools/vision against local Ollama). | local-ai/llm-settings.png (replaced stale asset in llms page) |
| settings/agent.png | 04-settings | open-settings → 'agent'. | — (spare) |
| library/all-assets.png | 01-library | /browse with the seeded library. Feedback coachmark burned during setup so no stray menu. | — (home hero candidate; existing approved asset kept) |
| library/boards-landing.png | 01-library | /boards with the three seeded boards. | — (spare) |
| library/board-detail.png | 01-library | Open the "Brand Refresh" board. | — (spare) |
| lineage/lineage-view-demo.png | 01-library | /lineage/23 (kontext-edit restyle with a source chain). | — (spare; lineage pages have approved assets) |

## Gotchas encoded in the harness (don't relearn these)

- Theme comes from the **backend** config (`theme: light`), not localStorage.
- localStorage keys are prefixed with the **bundle id** (`stimma_ai.stimma.stimma.debug_global_*`).
- A one-time **feedback coachmark** auto-opens the logo menu post-onboarding; setup.ts lets it fire and persist before any shots.
- Generations default to **24h auto-delete**; seed passes `auto_delete_duration: null`.
- Tool working state **persists server-side**; specs reset it via `PUT /api/tools/state/<tool>` for idempotence.
- The websocket provider URL needs the **/stp-v1 path**.
- Never `lsof -ti :PORT | xargs kill` — it matches *connections* too. Use `-sTCP:LISTEN`.

## Not yet automated

- Agent chat shots (`bake` class) — gemma4-over-Ollama now works for suggestions; chat-driven shots are plausible next, or wait for the cloud bake.
- Flow shots — flows are agent-built; same dependency.
- ComfyUI's own UI (manual, one shot).
- Cloud-specific UI (cost badges, tier cards) — needs a signed-in account.
