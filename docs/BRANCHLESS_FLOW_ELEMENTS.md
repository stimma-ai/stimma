# Branchless Flow Elements

This note describes the current design direction for conditional behavior in
Stimma flows after removing `branch()`. The goal is an equation graph that is
auditable before execution: the user and runtime should be able to see the
workflow shape without waiting for hidden subgraphs to appear dynamically.

## Why `branch()` Went Away

Flows are functional-reactive equation graphs. A flow program builds a graph
of equations, and the runtime later evaluates that graph as inputs resolve.
`branch()` violated the useful part of that model: it made graph shape depend on
runtime values. That created several practical problems.

- The workflow could not be fully inspected before running.
- The UI had to explain steps that did not exist yet, or that only existed on
  one run.
- Branch arms were easy for agents to misuse by returning plain values instead
  of building subgraphs.
- Equation keys, phase display, result reuse, and dependency tracking became
  harder to reason about.

The replacement approach is not “no conditionals.” It is “conditionals should
route values and collections through a graph whose structure remains stable.”
When graph shape is stable, previews, traces, phase summaries, retries, and
store reuse all become easier to audit.

## The Branchless Primitives

The branchless primitives are small data-flow elements. Most are implemented as
`code()` equations with extra metadata (`routing_kind`) so the UI can label them
as routing operations instead of generic logic.

```python
switch(value, cases, *, default=None, output_type="json", description=None)
when(condition, value, *, otherwise=None, output_type="json", description=None)
gate(condition, value, *, otherwise=None, output_type="json", description=None)
filter(items, predicate, *, output_type="list[json]", description=None)
filter_items(items, predicate, *, output_type="list[json]", description=None)
partition(items, classifier, *, labels, default_label=None, description=None)
take(items, n, *, output_type="list[json]", description=None)
foreach_range(n, callback, **extra_kwargs)
```

Use `switch` for scalar value selection: prompts, style labels, model names,
tool parameters, or other values that downstream nodes consume. It does not
choose which graph nodes exist.

Use `when` or `gate` for value-level pass-through. These are useful when a value
should become `None`, a fallback, or a sentinel if a condition is false. They do
not prevent upstream work from existing or running. If the goal is to avoid
expensive work for rejected items, filter before the expensive `foreach`.

Use `filter` / `filter_items` for collection routing. These keep matching items
from a list and produce a list node, so downstream `foreach` naturally runs zero
or more iterations.

Use `partition` to split a collection into labeled lanes. The result is a dict
of lists; extract lanes with `code()` before sending them into separate
pipelines.

Use `take` after filtering or ranking when only the first N items should move
forward.

Use `foreach_range` when the number of iterations is itself a node value. Use
plain `foreach(range(N), ...)` when N is a literal known at graph-build time.

## Patterns

### Route Parameters, Not Graph Shape

Instead of building different branch arms, compute a parameter and feed it to
the same downstream node.

```python
style_prompt = switch(
    genre,
    {
        "jazz": "smoky blue jazz-club poster",
        "rock": "red concert poster",
        "classical": "gold concert-hall poster",
    },
    default="neutral portrait poster",
    output_type="text",
    description="choose poster style",
)

image = tool("stimma-cloud:flux2-klein-9b", task_type="text-to-image", prompt=style_prompt)
```

This graph is visible up front: classify genre, choose style, generate image.
Only the value flowing through `style_prompt` changes at runtime.

### Filter Before Expensive Work

When only some items should enter a pipeline, filter the collection first.

```python
approved_specs = filter(
    specs,
    lambda item: item["approved"],
    output_type="list[json]",
    description="keep approved specs",
)

images = foreach(approved_specs, generate_image)
```

This is the branchless equivalent of “if approved, process it.” An empty list is
a valid result and simply produces no downstream iterations.

### Split Into Lanes

When items need different downstream treatment, use `partition`.

```python
lanes = partition(
    subjects,
    lambda item: item["genre"],
    labels=["jazz", "rock", "classical"],
    default_label="other",
    description="split subjects by genre",
)

jazz_subjects = code(
    lambda lanes: lanes["jazz"],
    inputs={"lanes": lanes},
    output_type="list[json]",
    description="extract jazz lane",
)

jazz_images = foreach(jazz_subjects, generate_jazz_image)
```

The UI can display this as a split even though the graph is just data-flow:
partition, lane extraction, and separate foreach pipelines.

### Collect N User-Approved Results

Do not model “repeat until I accept N” with a Python `while` loop, four
hand-written rounds, or `filter/take` over manual decisions. Human rejection is
already represented by `hitl.approve`: rejecting invalidates the upstream asset
and asks again. The branchless shape is N independent approval slots.

```python
def make_approved_dog(_):
    dog = tool(
        "stimma-cloud:flux2-klein-9b",
        prompt="a cute dog, high quality photography",
    )
    return hitl.approve(
        dog,
        instructions="Keep this dog? Reject to regenerate this slot.",
    )

with phase("Choose Dogs"):
    favorites = foreach(range(4), make_approved_dog)
```

This produces exactly four accepted media items. Each slot retries
independently when rejected, so the graph remains fixed while the runtime
handles regeneration.

Use `hitl.select(count=N)` for a different interaction: generate a visible batch
once and ask the user to choose N items from it.

## UI Implications

The UI should present these primitives as workflow concepts, not low-level code.
Current routing metadata supports labels like:

- `switch` -> “Choose Value”
- `filter` -> “Filter Items”
- `partition` -> “Split Items”
- `take` -> “Take First Items”
- `when` / `gate` -> “Gate Value”

These nodes should usually be shown as lightweight routing steps in graph views.
In step lists, they can stay less prominent than tools, LLM calls, and HITL
tasks unless they are user-meaningful or have failed. The important property is
that all possible work is represented in the graph before execution.

## Design Rule

Prefer the smallest primitive that keeps graph shape static:

- Need to choose a prompt or parameter: `switch`.
- Need to keep/drop collection items before work: `filter`.
- Need to split a collection into lanes: `partition`.
- Need to cap a list: `take`.
- Need conditional value pass-through: `gate` / `when`.
- Need N accepted human-approved outputs: `foreach(... hitl.approve(...))`.
- Need user to choose N from a batch: `hitl.select(count=N)`.

If a proposed feature requires new equations to appear only after a runtime
condition resolves, treat that as a design smell. Look first for a value-routing,
collection-routing, or HITL retry pattern that preserves a static graph.
