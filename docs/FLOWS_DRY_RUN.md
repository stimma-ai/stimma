# Flow Dry-Run

Flow dry-run is a fast preflight execution path for catching structural
flow errors before real provider calls run.

It uses the real graph builder and `FlowRun` scheduler against a temporary
state DB and temporary equation store. Tool and LLM evaluators are replaced by
deterministic synthetic evaluators, and HITL equations are auto-resolved:

- `hitl.select` picks the first candidate(s)
- `hitl.approve` approves and passes through the asset

Dry-run is intentionally a sampled execution validator. It catches:

- graph-build errors
- deferred `foreach` / `fill_slots` expansion errors
- dynamic binding failures
- runtime `code()` shape errors
- bad HITL handoffs
- **tool parameter schema mismatches inside deferred callbacks** — required
  inputs missing, unknown kwargs, scalar-vs-array shape errors, and literal
  type mismatches against the tool's `input_schema` / `parameter_schema`.
  Build-time validation already covers eagerly-bound `tool()` calls; dry-run
  closes the gap for `tool()` calls constructed inside `foreach` /
  `fill_slots` callbacks (which the build can't see because the callback
  hasn't run yet).

It does not certify real provider behavior, LLM semantic quality, safety
outcomes, token limits, credit availability, or every possible branch/item.

When dry-run runs:

1. **Automatically on every flow parse / reparse / update** — dry-run is
   invoked from `flow_lifecycle.apply_program_edit()` after a successful
   graph build, so deferred-callback errors surface in the agent's edit
   feedback (and the `flow_updated` `load_error` payload) before the user
   ever clicks Start. Truncation alone (timeout / equation budget) is not
   treated as a failure — only hard issues block.
2. Explicit endpoints for ad-hoc preflight:
   - `POST /api/flows/{flow_id}/dry-run`
   - `POST /api/flows/{flow_id}/start?dry_run=true` — when enabled and
     dry-run reports issues, execution is blocked before real tool/LLM
     calls are submitted.
