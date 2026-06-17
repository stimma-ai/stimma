from __future__ import annotations

from flow_runtime.step_timeline import build_phase_steps


def row(
    key: str,
    equation_type: str,
    *,
    status: str = "pending",
    deps: list[str] | None = None,
    phase: list[str] | None = None,
    display: str | None = None,
    control_kind: str | None = None,
    hitl_kind: str | None = None,
    is_scaffolding: bool = False,
    media: list[int] | None = None,
) -> dict:
    return {
        "equation_key": key,
        "equation_type": equation_type,
        "status": status,
        "display_name": display,
        "phase_path": phase or ["Phase"],
        "dependencies": deps or [],
        "result_media_ids": media or [],
        "execution_duration_ms": None,
        "compute_duration_ms": None,
        "completed_at": None,
        "error": None,
        "is_scaffolding": is_scaffolding,
        "hitl_kind": hitl_kind,
        "hitl_count": None,
        "tool_id": None,
        "task_type": None,
        "control_kind": control_kind,
        "result_from": None,
        "description": None,
        "routing_kind": None,
        "is_output": False,
        "output_name": None,
        "slot_count": None,
        "instructions": None,
        "attempt": 1,
        "inputs_hash": None,
        "result": None,
        "created_at": None,
        "invalidated_at": None,
    }


def test_phase_steps_are_dependency_ordered_not_row_ordered():
    rows = [
        row("r/c", "tool_call", deps=["r/hidden"], display="C"),
        row("r/hidden", "code", deps=["r/b"], display="Hidden code", status="completed"),
        row("r/a", "llm_call", display="A"),
        row("r/b", "tool_call", deps=["r/a"], display="B"),
    ]

    steps = build_phase_steps(rows)[("Phase",)]

    assert [s["eq"]["equation_key"] for s in steps] == ["r/a", "r/b", "r/c"]


def test_hitl_approve_slots_are_transposed_and_downstream_stays_after_gate():
    rows = [
        row("r/downstream", "tool_call", deps=["r/hitl.approve$0"], display="Downstream"),
        row("r/hitl.approve$0", "control", control_kind="approve", is_scaffolding=True, display="Loop"),
        row("r/hitl.approve$0/lambda:0", "control", control_kind="slot", is_scaffolding=True),
        row("r/hitl.approve$0/lambda:0/tool$0", "tool_call", display="Flux", media=[1]),
        row(
            "r/hitl.approve$0/lambda:0/hitl.approve$0",
            "hitl",
            deps=["r/hitl.approve$0/lambda:0/tool$0"],
            status="awaiting_input",
            display="Approve",
            hitl_kind="approve",
        ),
        row("r/hitl.approve$0/lambda:1", "control", control_kind="slot", is_scaffolding=True),
        row("r/hitl.approve$0/lambda:1/tool$0", "tool_call", display="Flux", media=[2]),
        row(
            "r/hitl.approve$0/lambda:1/hitl.approve$0",
            "hitl",
            deps=["r/hitl.approve$0/lambda:1/tool$0"],
            status="awaiting_input",
            display="Approve",
            hitl_kind="approve",
        ),
    ]

    steps = build_phase_steps(rows)[("Phase",)]

    assert [s["kind"] for s in steps] == ["group", "group", "equation"]
    assert [s["displayName"] for s in steps[:2]] == ["Flux", "Your Turn"]
    assert [s["aggregate"]["total"] for s in steps[:2]] == [2, 2]
    assert steps[1]["cellMode"] == "hitl-approve"
    assert steps[2]["eq"]["equation_key"] == "r/downstream"


def test_hitl_approve_media_candidate_ignores_prompt_generation_text():
    rows = [
        row("r/hitl.approve$0", "control", control_kind="approve", is_scaffolding=True, display="Loop"),
        row("r/hitl.approve$0/lambda:0", "control", control_kind="slot", is_scaffolding=True),
        row("r/hitl.approve$0/lambda:0/llm$0", "llm_call", display="LLM", status="completed"),
        row("r/hitl.approve$0/lambda:0/tool$0", "tool_call", deps=["r/hitl.approve$0/lambda:0/llm$0"], display="Flux"),
        row(
            "r/hitl.approve$0/lambda:0/hitl.approve$0",
            "hitl",
            deps=["r/hitl.approve$0/lambda:0/tool$0"],
            status="pending",
            display="Approve",
            hitl_kind="approve",
        ),
        row("r/hitl.approve$0/lambda:1", "control", control_kind="slot", is_scaffolding=True),
        row("r/hitl.approve$0/lambda:1/llm$0", "llm_call", display="LLM", status="completed"),
        row("r/hitl.approve$0/lambda:1/tool$0", "tool_call", deps=["r/hitl.approve$0/lambda:1/llm$0"], display="Flux"),
        row(
            "r/hitl.approve$0/lambda:1/hitl.approve$0",
            "hitl",
            deps=["r/hitl.approve$0/lambda:1/tool$0"],
            status="pending",
            display="Approve",
            hitl_kind="approve",
        ),
    ]

    steps = build_phase_steps(rows)[("Phase",)]

    assert [s["displayName"] for s in steps] == ["LLM", "Flux", "Your Turn"]
    assert steps[2]["cellMode"] == "hitl-approve"
    assert steps[2]["contentKind"] == "media"


def test_foreach_body_positions_are_transposed_by_dependency():
    rows = [
        row("r/foreach$0", "control", control_kind="foreach", is_scaffolding=True),
        row("r/foreach$0/body:0", "control", control_kind="foreach_iteration", is_scaffolding=True),
        row("r/foreach$0/body:0/llm$0", "llm_call", display="LLM"),
        row("r/foreach$0/body:0/code$0", "code", deps=["r/foreach$0/body:0/llm$0"], status="completed"),
        row("r/foreach$0/body:0/tool$0", "tool_call", deps=["r/foreach$0/body:0/code$0"], display="Tool"),
        row("r/foreach$0/body:1", "control", control_kind="foreach_iteration", is_scaffolding=True),
        row("r/foreach$0/body:1/llm$0", "llm_call", display="LLM"),
        row("r/foreach$0/body:1/code$0", "code", deps=["r/foreach$0/body:1/llm$0"], status="completed"),
        row("r/foreach$0/body:1/tool$0", "tool_call", deps=["r/foreach$0/body:1/code$0"], display="Tool"),
        row("r/foreach$0/body:2", "control", control_kind="foreach_iteration", is_scaffolding=True),
        row("r/foreach$0/body:2/llm$0", "llm_call", display="LLM"),
        row("r/foreach$0/body:2/code$0", "code", deps=["r/foreach$0/body:2/llm$0"], status="completed"),
        row("r/foreach$0/body:2/tool$0", "tool_call", deps=["r/foreach$0/body:2/code$0"], display="Tool"),
    ]

    steps = build_phase_steps(rows)[("Phase",)]

    assert [s["displayName"] for s in steps] == ["LLM", "Tool"]
    assert [s["aggregate"]["total"] for s in steps] == [3, 3]


def test_approve_each_nested_singleton_approve_transposes_across_foreach_items():
    rows = [
        row("r/foreach$0", "control", control_kind="foreach", is_scaffolding=True),
        row("r/foreach$0/item:0", "control", control_kind="foreach_iteration", is_scaffolding=True),
        row("r/foreach$0/item:0/hitl.approve$0", "control", control_kind="approve", is_scaffolding=True),
        row("r/foreach$0/item:0/hitl.approve$0/lambda:0", "control", control_kind="slot", is_scaffolding=True),
        row("r/foreach$0/item:0/hitl.approve$0/lambda:0/tool$0", "tool_call", display="Flux", media=[1]),
        row(
            "r/foreach$0/item:0/hitl.approve$0/lambda:0/hitl.approve$0",
            "hitl",
            deps=["r/foreach$0/item:0/hitl.approve$0/lambda:0/tool$0"],
            status="awaiting_input",
            display="Approve",
            hitl_kind="approve",
        ),
        row("r/foreach$0/item:1", "control", control_kind="foreach_iteration", is_scaffolding=True),
        row("r/foreach$0/item:1/hitl.approve$0", "control", control_kind="approve", is_scaffolding=True),
        row("r/foreach$0/item:1/hitl.approve$0/lambda:0", "control", control_kind="slot", is_scaffolding=True),
        row("r/foreach$0/item:1/hitl.approve$0/lambda:0/tool$0", "tool_call", display="Flux", media=[2]),
        row(
            "r/foreach$0/item:1/hitl.approve$0/lambda:0/hitl.approve$0",
            "hitl",
            deps=["r/foreach$0/item:1/hitl.approve$0/lambda:0/tool$0"],
            status="awaiting_input",
            display="Approve",
            hitl_kind="approve",
        ),
        row("r/downstream", "tool_call", deps=["r/foreach$0"], display="Downstream"),
    ]

    steps = build_phase_steps(rows)[("Phase",)]

    assert [s["kind"] for s in steps] == ["group", "group", "equation"]
    assert [s["displayName"] for s in steps[:2]] == ["Flux", "Your Turn"]
    assert [s["aggregate"]["total"] for s in steps[:2]] == [2, 2]
    assert steps[1]["cellMode"] == "hitl-approve"
    assert steps[2]["eq"]["equation_key"] == "r/downstream"
