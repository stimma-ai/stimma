"""What realize() draws a prepared prompt's slots with (prompt_programs.fluent): whether a prompt
has anything to draw, the Variants runtime, the replay rules for a recorded revision, and the
Fluent settings. Pools are written straight into the profile's store; nothing here calls a model."""

import pytest

from prompt_programs import program as prep
from prompt_programs import variant_pools as P
from prompt_programs.fill import DrawResult, ProgramError
from prompt_programs.fluent import ENGINE, has_draws, runtime_for, start_pools
from prompt_programs.judge import settings

from test_prompt_program_fix import LIGHT, OUTFIT, POOLS, PROFILE, USER, entry_for, profile  # noqa: F401  (profile: the store fixture)


def draw(entry, seed, **kw):
    return prep.realize(entry, seed=seed, profile_id=PROFILE, **kw)


def values(result):
    return {d.id: d.value for d in result.draws}


class TestHasDraws:
    def test_a_read_slot_or_a_user_list_is_something_to_draw(self):
        assert has_draws(entry_for())
        assert has_draws(entry_for("a {nun|lifeguard} at noon", readings=()))
        assert has_draws(entry_for("a nun wearing <outfit>", readings=(OUTFIT,)))

    def test_slots_not_read_or_read_as_written_are_not(self):
        assert not has_draws(entry_for("a nun wearing <outfit>", readings=()))
        e = entry_for("a nun wearing <outfit>", readings=({**OUTFIT, "degraded": True},))
        assert e["slots"][0]["degraded"] and not has_draws(e)
        assert not has_draws({})


class TestDrawing:
    def test_the_template_shows_every_slot_and_list_by_its_label(self):
        assert entry_for()["template"] == "A [Job] wearing [Outfit] under [Light]"

    def test_each_slot_draws_from_its_pool_and_the_revision_records_it(self):
        entry = entry_for()
        seen = set()
        for seed in range(40):
            r = draw(entry, seed)
            v = values(r)
            seen.add(v["light"])
            assert v["outfit"] in POOLS["outfit"] and v["light"] in POOLS["light"] and v["light"] in r.prompt
        assert seen == set(POOLS["light"])
        by = {s["id"]: s for s in entry["slots"]}
        assert r.revision["engine"] == ENGINE and "judge" not in r.revision
        assert r.revision["variants"] == {**{sid: {"pool": by[sid]["pool"], "text": v[sid]} for sid in ("light", "outfit")},
                                          "job": {"text": v["job"]}}   # the user's list is recorded too
        assert r.revision["entry"] == "fix1" and r.revision["id"] and not r.more_coming

    def test_a_slot_whose_pool_is_not_written_yet_is_its_words_and_more_is_coming(self):
        entry = entry_for()
        entry["slots"][1]["pool"] = P.pool_key("fake-model", "light", "another line", [])
        r = draw(entry, 1)
        assert isinstance(r, DrawResult) and values(r)["light"] == "light" and r.prompt.endswith("under light")
        assert r.more_coming == ["light"] and r.to_dict()["more_coming"] == ["light"]
        assert next(d for d in r.draws if d.id == "light").source == "words"

    def test_without_a_profile_store_every_slot_is_its_words(self, monkeypatch):
        import prompt_programs.fluent as fl

        def no_store(pid):
            raise RuntimeError("no profile")
        monkeypatch.setattr(fl, "store_for", no_store)
        r = prep.realize(entry_for(), seed=2)
        assert r.prompt.endswith("wearing outfit under light")

    def test_a_batch_runtime_takes_another_variant_after_a_noted_draw(self):
        entry = entry_for()
        rt = runtime_for(entry, profile_id=PROFILE)
        lights = []
        for seed in range(len(POOLS["light"])):
            r = prep.realize(entry, seed=seed, runtime=rt)
            rt.note(entry, r)
            lights.append(values(r)["light"])
        assert sorted(lights) == sorted(POOLS["light"])


class TestReplay:
    def test_a_variants_revision_replays_its_texts_after_the_pool_grows(self):
        entry = entry_for()
        first = [draw(entry, s) for s in range(8)]
        store = P.store_for(PROFILE)
        store.append(entry["slots"][1]["pool"], {"batch": 1, "role": "top_up",
                                                 "variants": [{"text": t, "seeds": {}} for t in ("starlight", "neon glow")]})
        for s, r in enumerate(first):   # the user's lists draw by the seed, the slots by the revision
            again = draw(entry, s, revision=r.revision)
            assert again.prompt == r.prompt and again.revision["id"] == r.revision["id"]
        assert runtime_for(entry, revision=first[0].revision, profile_id=PROFILE).fixed == \
            {sid: v["text"] for sid, v in first[0].revision["variants"].items()}

    def test_a_revision_recorded_with_the_null_judge_still_replays(self):
        # Revisions from before the in-draw judge was removed record judge "null": drawing
        # judged nothing then either, so they replay exactly.
        entry = entry_for()
        r = draw(entry, 3)
        assert draw(entry, 3, revision={**r.revision, "judge": "null"}).prompt == r.prompt

    def test_an_earlier_engine_cant_be_redrawn(self):
        entry = entry_for()
        for old in ({"engine": "fill-1", "pools": {}}, {"engine": "slots-2"}, {"pools": {"x": 3}}):
            with pytest.raises(ProgramError, match="earlier Fluent"):
                runtime_for(entry, revision=old, profile_id=PROFILE)
            with pytest.raises(ProgramError, match="earlier Fluent"):
                draw(entry, 1, revision=old)

    def test_a_revision_drawn_with_another_judge_says_so(self):
        entry = entry_for()
        r = draw(entry, 1)
        with pytest.raises(ProgramError, match="judge d3-edge"):
            runtime_for(entry, revision={**r.revision, "judge": "d3-edge@abc/q1"}, profile_id=PROFILE)
        with pytest.raises(ProgramError, match="can't be replayed exactly"):
            draw(entry, 1, revision={**r.revision, "judge": "fake-1"})

    def test_a_revision_that_isnt_one_is_ignored(self):
        entry = entry_for()
        assert runtime_for(entry, revision="nonsense", profile_id=PROFILE).fixed == {}
        assert draw(entry, 1, revision="nonsense").prompt == draw(entry, 1).prompt


def test_starting_pools_for_a_prompt_with_nothing_to_draw_never_raises():
    assert start_pools({"slots": []}, profile_id=PROFILE) == []
    assert start_pools({"slots": [{"id": "x", "state": "ready", "pool": "not a key"}], "key": "k"},
                       profile_id=PROFILE) == []
    assert start_pools({"slots": None, "key": "k"}, profile_id=PROFILE) == []


def test_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("STIMMA_FLUENT_GENERATE", "0")   # gone: ignored
    monkeypatch.setenv("STIMMA_FLUENT_JUDGE", "http")   # gone: ignored
    monkeypatch.setenv("STIMMA_FLUENT_FIX_ROUNDS", "3")
    s = settings()
    assert not hasattr(s, "generate_options") and not hasattr(s, "judge") and s.fix_rounds == 3
