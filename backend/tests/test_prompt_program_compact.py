"""What is stored about a vocabulary list is a reference to it, never a copy (compact.py)."""
import dataclasses
import json

import pytest

from prompt_programs.compact import PoolStore, is_pool_ref, is_ref, pack_entry, pack_values, unpack_entry, unpack_values
from prompt_programs.fluent import runtime_for
from prompt_programs.judge import settings
from prompt_programs.options import OptionStore
from prompt_programs.program import realize
from prompt_programs.fill import ProgramError
from prompt_programs.store import ProgramStore
from prompt_programs.vocab import vocabulary

@pytest.fixture(autouse=True)
def long_face_list(monkeypatch):
    """These tests are about a list of thousands of values. The face is now its single pieces
    (a few hundred), so they draw from a face list composed the old way: two or three pieces
    joined, 3,000 of them."""
    import dataclasses as dc
    from prompt_programs.vocab import _composed
    v = vocabulary()
    parts = {lid: 1.0 for lid in v.leaves if lid.startswith("person.feature.")}
    spec = {"parts": parts, "take": {"2": 0.55, "3": 0.45}, "count": 3000,
            "tags": {"presentation": ["feminine", "masculine"]}, "keep": ["presentation"]}
    face = v.leaves["person.face"]
    monkeypatch.setitem(v.leaves, "person.face", dc.replace(face, values=_composed("person.face", spec, v.leaves)))


WOMAN = {"n": 1, "kind": "person", "label": "Woman", "lead": "",
         "person": {"noun": "woman", "presentation": "feminine", "stated": {},
                    "vary": ["age", "descent", "hair", "hair_color", "face"], "outfit": ""}}
KEY = "ab" * 16


def entry():
    from prompt_programs.slots import compose, parse
    faces = [v.text for v in vocabulary().get("person.face").matching({"presentation": "feminine"})]
    e = compose(parse("A portrait of a <woman>."), {1: WOMAN})
    return {**e, "key": KEY, "prompt": "a woman", "filters": {"woman.face": faces}}


def size(obj):
    return len(json.dumps(obj))


class TestListsByReference:
    def test_values_of_a_list_in_its_order_pack_and_unpack_exactly(self):
        leaf = vocabulary().get("person.face")
        texts = [v.text for v in leaf.values]
        for values in (texts, texts[5:], texts[::7], [t for i, t in enumerate(texts) if i % 50]):
            ref = pack_values("person.face", values)
            assert is_ref(ref) and size(ref) < size(values) / 10 and unpack_values(ref) == values
        assert pack_values("person.face", texts[5:])["without"] == [0, 1, 2, 3, 4]

    def test_what_is_not_a_lists_values_in_order_is_left_as_it_is(self):
        texts = [v.text for v in vocabulary().get("person.eye_color").values]
        for values in (texts[::-1], [*texts, "eyes like a winter sea"], texts[:3], None, "hazel"):
            assert pack_values("person.eye_color", values) == values
        assert pack_values("no.such_list", texts) == texts and pack_values(None, texts) == texts

    def test_a_stored_program_is_small_and_reads_back_as_it_was(self, tmp_path):
        e = entry()
        store = ProgramStore(tmp_path)
        store.put(KEY, e)
        assert store.get(KEY) == e
        on_disk = (tmp_path / KEY[:2] / f"{KEY}.json").stat().st_size
        assert on_disk < 20_000 < size(e) / 10

    def test_under_another_vocabulary_a_choice_shows_todays_list_and_a_filter_stays(self):
        e = entry()
        packed = pack_entry(e)
        old = json.loads(json.dumps(packed).replace(vocabulary().version, "vocab-000000000000"))
        got = unpack_entry(old)
        face = next(c for c in got["choices"] if c["id"] == "woman.face")
        # her face is narrowed by a named part: matched again on today's list
        assert face["options"] and got["filters"]["woman.face"] == e["filters"]["woman.face"]

    def test_a_narrowed_pick_replays_its_recorded_pool_after_the_vocabulary_changes(self, tmp_path, monkeypatch):
        # A pool's key says whether its pick was narrowed: losing the filter would miss the recorded pool.
        e, store, cfg = entry(), OptionStore(tmp_path / "o"), dataclasses.replace(settings(), generate_options=False)
        freckled = [t for t in e["filters"]["woman.face"] if "freckles" in t]
        e["filters"]["woman.face"] = freckled
        next(c for c in e["choices"] if c["id"] == "woman.face")["where"] = "freckles"
        programs = ProgramStore(tmp_path / "p")
        programs.put(KEY, e)
        first = realize(e, seed=5, runtime=runtime_for(e, store=store, cfg=cfg))
        assert "freckles" in first.prompt
        monkeypatch.setattr(vocabulary(), "version", "vocab-111111111111")   # a new vocabulary release
        later = programs.get(KEY)
        assert "woman.face" in later["filters"]
        again = realize(later, seed=5, runtime=runtime_for(later, store=store, cfg=cfg, revision=first.to_dict()["draw_revision"]))
        assert again.prompt == first.prompt


    def test_a_filter_whose_part_matches_nothing_today_still_replays_its_recorded_pool(self, tmp_path, monkeypatch):
        import dataclasses as dc
        e, store, cfg = entry(), OptionStore(tmp_path / "o"), dataclasses.replace(settings(), generate_options=False)
        programs = ProgramStore(tmp_path / "p")
        programs.put(KEY, e)
        first = realize(e, seed=5, runtime=runtime_for(e, store=store, cfg=cfg))
        v = vocabulary()
        face = v.leaves["person.face"]   # a release in which no face is tagged for a woman any more
        monkeypatch.setitem(v.leaves, "person.face", dc.replace(face, values=tuple(
            dc.replace(x, tags={**x.tags, "presentation": ["masculine"]}) for x in face.values)))
        monkeypatch.setattr(v, "version", "vocab-222222222222")
        later = programs.get(KEY)
        assert later["filters"]["woman.face"]
        again = realize(later, seed=5, runtime=runtime_for(later, store=store, cfg=cfg, revision=first.to_dict()["draw_revision"]))
        assert again.prompt == first.prompt


class TestRecordedPools:
    def cfg(self):
        return dataclasses.replace(settings(), generate_options=False)

    def test_a_revision_names_its_pools_and_replays_exactly(self, tmp_path):
        e, store = entry(), OptionStore(tmp_path)
        first = realize(e, seed=3, runtime=runtime_for(e, store=store, cfg=self.cfg()))
        rev = first.to_dict()["draw_revision"]
        assert rev["pools"] and all(is_pool_ref(v) or isinstance(v, int) for v in rev["pools"].values())
        assert size(rev) < 5_000
        again = realize(e, seed=3, runtime=runtime_for(e, store=store, cfg=self.cfg(), revision=rev))
        assert again.prompt == first.prompt

    def test_a_pool_is_kept_once_however_many_images_draw_from_it(self, tmp_path):
        e, store = entry(), OptionStore(tmp_path)
        for seed in range(6):
            realize(e, seed=seed, runtime=runtime_for(e, store=store, cfg=self.cfg()))
        files = list((tmp_path / "pools").rglob("*.json.gz"))
        refs = {v["$pool"] for seed in range(6)
                for v in realize(e, seed=seed, runtime=runtime_for(e, store=store, cfg=self.cfg())).to_dict()["draw_revision"]["pools"].values()
                if is_pool_ref(v)}
        assert {f.name.split(".")[0] for f in files} == refs

    def test_a_pool_that_is_gone_says_so(self, tmp_path):
        e, store = entry(), OptionStore(tmp_path)
        rev = realize(e, seed=3, runtime=runtime_for(e, store=store, cfg=self.cfg())).to_dict()["draw_revision"]
        with pytest.raises(ProgramError, match="can't be replayed exactly"):
            runtime_for(e, store=OptionStore(tmp_path / "elsewhere"), cfg=self.cfg(), revision=rev)

    def test_an_older_revision_with_its_pools_written_out_still_replays(self, tmp_path):
        e, store = entry(), OptionStore(tmp_path)
        first = realize(e, seed=3, runtime=runtime_for(e, store=store, cfg=self.cfg()))
        rev = first.to_dict()["draw_revision"]
        older = {**rev, "pools": {k: store.pools.get(v) if is_pool_ref(v) else v for k, v in rev["pools"].items()}}
        again = realize(e, seed=3, runtime=runtime_for(e, store=OptionStore(tmp_path / "elsewhere"), cfg=self.cfg(), revision=older))
        assert again.prompt == first.prompt

    def test_the_store_refuses_a_hash_that_is_a_path(self, tmp_path):
        assert PoolStore(tmp_path).get({"$pool": "../../etc/passwd"}) is None


class TestThePoolsAnswerStaysSmall:
    def test_a_long_list_is_not_sent_again_with_the_pools(self, tmp_path):
        from prompt_programs.fluent import pool_options
        e = entry()
        cfg = dataclasses.replace(settings(), generate_options=False)
        got = pool_options(e, store=OptionStore(tmp_path), cfg=cfg)
        # only what her choice doesn't list already: the few faces drawn only for a woman
        extra = got["options"]["woman.face"]
        assert len(extra) < 100 and not set(extra) & set(next(c for c in e["choices"] if c["id"] == "woman.face")["options"])
        assert got["vocab"]["woman.face"]["cls"] == "person.face"
        # every face her words leave is a usual one; the few outside them wait for a tick
        kept = set(e["filters"]["woman.face"])
        tiers = got["vocab"]["woman.face"]["tiers"]
        assert set(tiers.values()) <= {"opt_in"} and not set(tiers) & kept and len(tiers) < 100
        assert "reach" not in got["vocab"]["woman.face"]           # a long list keeps its plain row
        assert size(got) < 40_000 < size(e)
        # a short list is answered whole, as before, with its opt-in values marked for the picker
        assert len(got["options"]["woman.age"]) > 10
        assert "opt_in" in set(got["vocab"]["woman.age"]["tiers"].values())
