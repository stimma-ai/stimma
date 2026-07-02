"""Tests for the agent notepad tool (agent/v2/tools/notepad.py)."""

import pytest

from agent.v2.tools.notepad import notepad, _read_tasks


@pytest.mark.asyncio
async def test_set_tasks_uses_zero_based_ids_and_echoes_them(tmp_path):
    result = await notepad(
        action="set_tasks",
        tasks=["first", "second", "third"],
        workspace_dir=str(tmp_path),
    )

    data = _read_tasks(str(tmp_path))
    assert [t["id"] for t in data["tasks"]] == [0, 1, 2]
    assert data["next_id"] == 3
    assert "0: first" in result
    assert "1: second" in result
    assert "2: third" in result


@pytest.mark.asyncio
async def test_add_tasks_continues_ids_and_echoes_them(tmp_path):
    await notepad(action="set_tasks", tasks=["a", "b"], workspace_dir=str(tmp_path))
    result = await notepad(action="add_tasks", tasks=["c"], workspace_dir=str(tmp_path))

    data = _read_tasks(str(tmp_path))
    assert [t["id"] for t in data["tasks"]] == [0, 1, 2]
    assert "2: c" in result
    assert "0: a" not in result  # only the added tasks are echoed


@pytest.mark.asyncio
async def test_update_task_zero_works(tmp_path):
    await notepad(action="set_tasks", tasks=["a", "b"], workspace_dir=str(tmp_path))
    result = await notepad(
        action="update_task", task_id=0, status="done", workspace_dir=str(tmp_path)
    )

    data = _read_tasks(str(tmp_path))
    assert data["tasks"][0]["status"] == "done"
    assert "Task 0 marked done" in result
    assert "1/2 done" in result


@pytest.mark.asyncio
async def test_update_task_not_found_lists_current_tasks(tmp_path):
    await notepad(action="set_tasks", tasks=["a", "b"], workspace_dir=str(tmp_path))
    result = await notepad(
        action="update_task", task_id=7, status="done", workspace_dir=str(tmp_path)
    )

    assert result.startswith("Error: Task 7 not found")
    assert "0: a" in result
    assert "1: b" in result
