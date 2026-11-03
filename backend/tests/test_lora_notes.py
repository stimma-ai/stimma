"""LoRA notes stay with a file's fingerprint through moves, renames and sharing."""

import types

import httpx
import pytest

import lora_notes
from providers.registry import ProviderRegistry

pytestmark = pytest.mark.asyncio(loop_scope="module")

TOOL = "fake:lora-tool"


def fp(name: str) -> str:
    return "stfp1:" + (name.encode().hex() + "0" * 32)[:32]


class FakeProvider:
    def __init__(self):
        self.files: dict = {}
        self.pending = 0
        self.fail = False

    async def file_fingerprints(self, tool_id, parameter):
        assert (tool_id, parameter) == ("lora-tool", "loras")
        if self.fail:
            raise RuntimeError("provider down")
        return {"fingerprints": dict(self.files), "pending": self.pending}


@pytest.fixture
def provider(monkeypatch):
    fake = FakeProvider()
    descriptor = types.SimpleNamespace(id="lora-tool", parameter_schema={"properties": {}})

    def get_tool(tool_id):
        descriptor.parameter_schema = {
            "properties": {"loras": {"items": {"properties": {"path": {"enum": list(fake.files)}}}}}
        }
        return (fake, descriptor) if tool_id == TOOL else None

    monkeypatch.setattr(ProviderRegistry, "get_instance", lambda: types.SimpleNamespace(get_tool=get_tool))
    lora_notes._snapshots.clear()
    yield fake
    lora_notes._snapshots.clear()


async def notes(client):
    lora_notes._snapshots.clear()
    response = await client.get("/api/lora-notes", params={"tool_id": TOOL})
    assert response.status_code == 200
    return response.json()


async def save(client, fingerprint, words=(), text=""):
    response = await client.put(
        f"/api/lora-notes/files/{fingerprint}", json={"trigger_words": list(words), "notes": text}
    )
    assert response.status_code == 200


def share(client, fingerprint, value, replace=False):
    return client.post(
        f"/api/lora-notes/files/{fingerprint}/share", json={"tool_id": TOOL, "value": value, "replace": replace}
    )


class TestSeriesKey:
    @pytest.mark.parametrize(
        "path,key,step",
        [
            ("a/ana_v3_000002400.safetensors", "a/ana_v3", True),
            ("a/ana_v3.safetensors", "a/ana_v3", False),
            ("a/ana-step1200.safetensors", "a/ana", True),
            ("a/ana_epoch_12.safetensors", "a/ana", True),
            ("a/ana_v2_2.safetensors", "a/ana_v2_2", False),
            ("a/style_2.safetensors", "a/style", False),
            ("a\\win_000000500.safetensors", "a/win", True),
            ("p/suit/checkpoint-400/pytorch_lora_weights.safetensors", "p/suit/*/pytorch_lora_weights", True),
            ("solo.safetensors", "solo", False),
        ],
    )
    def test_keys(self, path, key, step):
        assert lora_notes.series_key(path) == (key, step)

    def test_versions_are_separate_series(self):
        groups = lora_notes.group_series(["a_v2_000000500.st", "a_v2_000001000.st", "a_v3_000000500.st"])
        assert list(groups) == ["a_v2"]


class TestCanonicalValues:
    VALUES = ["flux/ana_000000500.safetensors", "flux/ana_000001000.safetensors", "flux/kodak.safetensors"]

    def test_accepts_each_item_shape(self):
        assert lora_notes.canonical_lora_values(self.VALUES, [{"lora": self.VALUES[0], "weight": 1}]) == [self.VALUES[0]]
        assert lora_notes.canonical_lora_values(self.VALUES, [{"path": self.VALUES[1]}]) == [self.VALUES[1]]
        assert lora_notes.canonical_lora_values(self.VALUES, [{"name": "kodak"}]) == [self.VALUES[2]]

    def test_negative_counts_but_zero_and_disabled_do_not(self):
        items = [
            {"lora": self.VALUES[0], "weight": -0.5},
            {"lora": self.VALUES[1], "weight": 0},
            {"lora": self.VALUES[2], "enabled": False},
        ]
        assert lora_notes.canonical_lora_values(self.VALUES, items) == [self.VALUES[0]]

    def test_ambiguous_or_unknown_is_skipped(self):
        assert lora_notes.canonical_lora_values(self.VALUES, [{"name": "ana"}, {"name": "nothing"}]) == []


async def test_provider_without_support_is_unavailable(client: httpx.AsyncClient, provider, monkeypatch):
    provider.fail = True
    provider.files = {"a.safetensors": None}
    assert await notes(client) == {"available": False, "pending": 0, "items": {}}


async def test_note_survives_move_and_rename(client: httpx.AsyncClient, provider):
    f = fp("mover")
    provider.files = {"training/run_000000500.safetensors": f}
    await save(client, f, ["ohwx mara"], "A person.")

    provider.files = {"final/mara.safetensors": f}
    item = (await notes(client))["items"]["final/mara.safetensors"]
    assert item["note"]["trigger_words"] == ["ohwx mara"]
    assert item["note"]["notes"] == "A person."


async def test_row_without_fingerprint_has_no_note(client: httpx.AsyncClient, provider):
    provider.files = {"old.ckpt": None}
    assert (await notes(client))["items"]["old.ckpt"]["note"] is None


async def test_copies_share_a_note(client: httpx.AsyncClient, provider):
    f = fp("copies")
    provider.files = {"one/copy.safetensors": f, "two/renamed.safetensors": f}
    await save(client, f, ["copyword"])
    items = (await notes(client))["items"]
    assert items["two/renamed.safetensors"]["note"]["trigger_words"] == ["copyword"]


async def test_new_checkpoint_auto_joins_then_keeps_note_after_rename(client: httpx.AsyncClient, provider):
    a, b, c = fp("join-a"), fp("join-b"), fp("join-c")
    provider.files = {"run/j_000000500.safetensors": a, "run/j_000001000.safetensors": b}
    await save(client, a, ["jword"], "Shared.")
    assert (await share(client, a, "run/j_000000500.safetensors")).json()["status"] == "shared"
    assert (await notes(client))["items"]["run/j_000001000.safetensors"]["note"]["shared"] is True

    provider.files["run/j_000001500.safetensors"] = c
    item = (await notes(client))["items"]["run/j_000001500.safetensors"]
    assert item["note"]["trigger_words"] == ["jword"]
    assert item["note"]["linked_count"] == 3

    # The keeper moves out of the series, and its note goes with it.
    provider.files = {"final/j_keeper.safetensors": c}
    assert (await notes(client))["items"]["final/j_keeper.safetensors"]["note"]["trigger_words"] == ["jword"]


async def test_auto_join_commits_for_a_read_only_caller(client: httpx.AsyncClient, provider):
    a, b, c = fp("commit-a"), fp("commit-b"), fp("commit-c")
    provider.files = {"cr/c_000000500.safetensors": a, "cr/c_000001000.safetensors": b}
    await save(client, a, ["cword"])
    await share(client, a, "cr/c_000000500.safetensors")
    provider.files["cr/c_000001500.safetensors"] = c
    lora_notes._snapshots.clear()
    context = await lora_notes.lora_context_for(TOOL, {"loras": [{"lora": "cr/c_000001500.safetensors"}]})
    assert context[0]["trigger_words"] == ["cword"]
    provider.files = {"elsewhere.safetensors": c}
    assert (await notes(client))["items"]["elsewhere.safetensors"]["note"]["trigger_words"] == ["cword"]


async def test_share_conflict_then_replace(client: httpx.AsyncClient, provider):
    a, b = fp("conflict-a"), fp("conflict-b")
    provider.files = {"w/s_000000750.safetensors": a, "w/s_000001500.safetensors": b}
    await save(client, a, ["w"], "Too strong.")
    await save(client, b, ["w"], "Night only.")
    assert (await notes(client))["items"]["w/s_000000750.safetensors"]["series"]["default_shared"] is False

    response = await share(client, a, "w/s_000000750.safetensors")
    assert response.status_code == 409
    assert response.json()["detail"]["conflicts"] == 1
    assert (await notes(client))["items"]["w/s_000001500.safetensors"]["note"]["notes"] == "Night only."

    assert (await share(client, a, "w/s_000000750.safetensors", replace=True)).status_code == 200
    item = (await notes(client))["items"]["w/s_000001500.safetensors"]
    assert item["note"]["notes"] == "Too strong."
    assert item["note"]["shared"] is True


async def test_unshare_then_reshare(client: httpx.AsyncClient, provider):
    a, b = fp("unshare-a"), fp("unshare-b")
    provider.files = {"u/q_000000500.safetensors": a, "u/q_000001000.safetensors": b}
    await save(client, a, ["q"], "Text.")
    await share(client, a, "u/q_000000500.safetensors")

    assert (await client.post(f"/api/lora-notes/files/{a}/unshare")).status_code == 200
    items = (await notes(client))["items"]
    assert items["u/q_000000500.safetensors"]["note"]["notes"] == "Text."
    assert items["u/q_000000500.safetensors"]["note"]["shared"] is False
    assert items["u/q_000001000.safetensors"]["note"] is None

    assert (await share(client, a, "u/q_000000500.safetensors")).status_code == 200
    assert (await notes(client))["items"]["u/q_000001000.safetensors"]["note"]["notes"] == "Text."


async def test_empty_save_removes_note(client: httpx.AsyncClient, provider):
    f = fp("empty")
    provider.files = {"e.safetensors": f}
    await save(client, f, ["x"])
    await save(client, f)
    assert (await notes(client))["items"]["e.safetensors"]["note"] is None
    await save(client, f, ["again"])
    assert (await notes(client))["items"]["e.safetensors"]["note"]["trigger_words"] == ["again"]


async def test_two_shared_notes_in_one_series_do_not_join(client: httpx.AsyncClient, provider):
    a, b, c = fp("two-a"), fp("two-b"), fp("two-c")
    provider.files = {"t1/z_000000500.safetensors": a, "t1/z_000001000.safetensors": fp("two-x")}
    await save(client, a, ["one"])
    await share(client, a, "t1/z_000000500.safetensors")
    provider.files = {"t2/z_000000500.safetensors": b, "t2/z_000001000.safetensors": fp("two-y")}
    await save(client, b, ["two"])
    await share(client, b, "t2/z_000000500.safetensors")
    provider.files = {"t3/z_000000500.safetensors": a, "t3/z_000001000.safetensors": b, "t3/z_000001500.safetensors": c}
    assert (await notes(client))["items"]["t3/z_000001500.safetensors"]["note"] is None


async def test_invalid_fingerprint_is_rejected(client: httpx.AsyncClient, provider):
    assert (await client.put("/api/lora-notes/files/nope", json={})).status_code == 422


async def test_context_skips_loras_without_notes_and_never_raises(client: httpx.AsyncClient, provider):
    f = fp("context")
    provider.files = {"c/noted.safetensors": f, "c/plain.safetensors": fp("plain")}
    await save(client, f, ["ctx"], "Note.")
    lora_notes._snapshots.clear()
    context = await lora_notes.lora_context_for(
        TOOL, {"loras": [{"lora": "c/noted.safetensors", "weight": -1}, {"lora": "c/plain.safetensors"}]}
    )
    assert context == [{"name": "noted", "trigger_words": ["ctx"], "notes": "Note."}]

    provider.fail = True
    lora_notes._snapshots.clear()
    assert await lora_notes.lora_context_for(TOOL, {"loras": [{"lora": "c/noted.safetensors"}]}) == []
