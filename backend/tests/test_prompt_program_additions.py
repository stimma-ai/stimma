"""The user's own options kept per vocabulary list (prompt_programs/additions.py): the store,
its routes, and how later prompts offer and draw them."""

import copy

import httpx
import pytest
from fastapi import FastAPI

from prompt_programs import additions as adds
from prompt_programs import program as prep
from prompt_programs.additions import AdditionStore, additions_for, list_id
from prompt_programs.fix import fix_draw, judged_picks
from prompt_programs.fluent import pool_options, runtime_for
from prompt_programs.judge import FluentSettings
from tests.slot_fixtures import discover
from prompt_programs.vocab import AGE_LIST, TIER_WEIGHTS, vocabulary

OFF = FluentSettings(generate_options=False, fix_model="off")
BRAID = "a messy fishtail braid"

# Two different prompts whose hair choices bind the same list, under different ids.
BEACH = '''
hair = pick("hair", cls="person.hairstyle", about="her hairstyle", seed=["a low ponytail"], label="Hairstyle", phase=1, line=1)
emit("A woman at the beach with", hair, ".")
'''
CAFE = '''
hair = pick("barista.hair", cls="person.hairstyle", about="the barista's hairstyle", seed=["a bob"], label="Hair", phase=1, line=1)
expr = pick("barista.expr", cls="person.expression", about="her expression", seed=["a smile"], label="Expression", phase=1, line=1)
emit("A barista with", hair, "and", expr, ".")
'''
SAID = '''
hair = pick("hair", cls="person.hairstyle", about="her hairstyle", said="a high ponytail", label="Hairstyle", phase=1, line=1)
emit("A woman with", hair, ".")
'''
AGED = '''
age = pick("age", cls="person.age_band", about="her age", seed=["25-year-old"], label="Age", phase=1, line=1)
hair = pick("hair", cls="person.hairstyle", about="her hairstyle", seed=["a bob"], label="Hairstyle", phase=1, line=1)
outfit = pick("outfit", cls="person.outfit.summer", about="what she wears", seed=["a swimsuit"], label="Outfit", phase=1, line=1)
emit("A", age, "person with", hair, "wearing", outfit, ".")
'''
SEEDS = range(400)


def entry_of(src, key="k", **extra):
    from tests.slot_fixtures import entry_of as fixture
    return fixture(src, "", key=key, **extra)


def hair_values():
    return [v.text for v in vocabulary().get("person.hairstyle").values]


@pytest.fixture(autouse=True)
def profiles(tmp_path, monkeypatch):
    """Each profile's directory under tmp_path; no option cache or filler, so pools are the
    lists themselves (the production path otherwise: realize() and pool_options() read the
    profile's additions)."""
    import app_dirs
    import prompt_programs.fluent as fl

    def profile_dir(modifier="", profile_id="default"):
        d = tmp_path / "profiles" / str(profile_id)
        d.mkdir(parents=True, exist_ok=True)
        return d
    monkeypatch.setattr(app_dirs, "get_profile_dir", lambda pid="default": profile_dir(profile_id=pid))
    monkeypatch.setattr(adds, "_stores", {})
    monkeypatch.setattr(fl, "_profile_store", lambda pid: None)
    monkeypatch.setattr(fl, "filler_for", lambda pid: (_ for _ in ()).throw(RuntimeError("no filler in tests")))
    monkeypatch.setattr(fl, "settings", lambda: OFF)
    return tmp_path


def draws(entry, profile, seeds=SEEDS, pins=None, edits=None):
    for s in seeds:
        r = prep.realize(entry, seed=s, pins=pins, edits=edits, profile_id=profile)
        yield {d.id: d for d in r.draws}


# --------------------------------------------------------------------------- the store

class TestTheStore:
    def test_add_list_remove(self, tmp_path):
        s = AdditionStore(tmp_path / "a.json")
        assert s.lists() == {} and s.of("person.hairstyle") == []
        assert s.add("person.hairstyle", "  a messy   fishtail braid ")
        assert not s.add("person.hairstyle", "A Messy Fishtail Braid")   # the same option, once
        assert s.add("person.hairstyle", "a crown braid") and s.add("person.expression", "a smirk")
        assert s.of("person.hairstyle") == [BRAID, "a crown braid"]
        again = AdditionStore(tmp_path / "a.json")   # durable: a new process reads it back
        assert again.lists() == {"person.hairstyle": [BRAID, "a crown braid"], "person.expression": ["a smirk"]}
        assert again.remove("person.hairstyle", "A messy fishtail braid") and not again.remove("person.hairstyle", BRAID)
        assert again.lists() == {"person.hairstyle": ["a crown braid"], "person.expression": ["a smirk"]}

    def test_a_broken_file_reads_as_nothing_kept(self, tmp_path):
        p = tmp_path / "a.json"
        p.write_text("{not json")
        s = AdditionStore(p)
        assert s.lists() == {}
        assert s.add("person.hairstyle", BRAID) and s.of("person.hairstyle") == [BRAID]

    def test_the_version_follows_the_contents(self, tmp_path):
        s = AdditionStore(tmp_path / "a.json")
        empty = s.version()
        s.add("person.hairstyle", BRAID)
        assert s.version() != empty
        s.remove("person.hairstyle", BRAID)
        assert s.version() == empty

    def test_only_lists_keep_additions_and_typos_land_on_the_list(self):
        assert list_id("person.hairstyle") == "person.hairstyle"
        assert list_id("person.eye_colr") == "person.eye_color"   # the binding's own typo repair
        assert list_id("person.palette") is None                      # a look's Colors: schemes carry roles
        assert list_id("") is None and list_id("not.a.list") is None

    def test_profiles_are_apart(self):
        additions_for("a").add("person.hairstyle", BRAID)
        assert additions_for("b").lists() == {}
        assert additions_for("a").of("person.hairstyle") == [BRAID]


# --------------------------------------------------------------------------- the routes

def _app(monkeypatch, profile):
    from routes import prompt_programs as route
    monkeypatch.setattr(route, "get_current_profile", lambda: profile["id"])
    app = FastAPI()
    app.include_router(route.router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class TestTheRoutes:
    async def test_add_list_remove(self, monkeypatch):
        who = {"id": "a"}
        async with _app(monkeypatch, who) as c:
            r = await c.post("/api/prompt-programs/additions", json={"cls": "person.hairstyle", "text": BRAID})
            assert r.status_code == 200 and r.json() == {"list": "person.hairstyle", "added": True, "options": [BRAID]}
            r = await c.post("/api/prompt-programs/additions", json={"cls": "person.hairstyle", "text": BRAID})
            assert r.json()["added"] is False
            assert (await c.get("/api/prompt-programs/additions")).json() == {"lists": {"person.hairstyle": [BRAID]}}
            who["id"] = "b"   # another profile sees none of it
            assert (await c.get("/api/prompt-programs/additions")).json() == {"lists": {}}
            who["id"] = "a"
            r = await c.post("/api/prompt-programs/additions/remove", json={"cls": "person.hairstyle", "text": BRAID})
            assert r.json() == {"list": "person.hairstyle", "removed": True, "options": []}

    async def test_what_isnt_kept(self, monkeypatch):
        async with _app(monkeypatch, {"id": "a"}) as c:
            r = await c.post("/api/prompt-programs/additions", json={"cls": "person.palette", "text": "teal and coral"})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "not_a_list"
            r = await c.post("/api/prompt-programs/additions", json={"cls": "", "text": BRAID})
            assert r.status_code == 422
            r = await c.post("/api/prompt-programs/additions", json={"cls": "person.hairstyle", "text": "   "})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "bad_option"
            r = await c.post("/api/prompt-programs/additions", json={"cls": "person.hairstyle", "text": "x" * 400})
            assert r.status_code == 422
        assert additions_for("a").lists() == {}

    async def test_added_in_one_prompt_offered_in_another(self, monkeypatch):
        """End to end through the routes: add the braid to one prompt's hairstyle, then a
        different prompt's pools offer it as the user's own, and its draws draw it."""
        store = prep.store_for("a")
        beach, cafe = entry_of(BEACH, key="b" * 32), entry_of(CAFE, key="c" * 32)
        store.put(beach["key"], beach)
        store.put(cafe["key"], cafe)
        body = {"tool_id": "t", "prompt": "a barista", "key": cafe["key"]}
        async with _app(monkeypatch, {"id": "a"}) as c:
            before = (await c.post("/api/prompt-programs/pools", json=body)).json()
            assert BRAID not in before["choices"]["barista.hair"]["options"]
            await c.post("/api/prompt-programs/additions", json={"cls": "person.hairstyle", "text": BRAID})
            after = (await c.post("/api/prompt-programs/pools", json=body)).json()
        meta = after["choices"]["barista.hair"]
        assert BRAID in meta["options"]
        assert meta["mine"] == [BRAID] and meta["tiers"][BRAID] == "typical"
        assert "mine" not in after["choices"]["barista.expr"]   # another list's choice is untouched
        drawn = {d["barista.hair"].value for d in draws(cafe, "a")}
        assert BRAID in drawn
        assert cafe == entry_of(CAFE, key="c" * 32)   # the prepared program itself never changes


# --------------------------------------------------------------------------- pools and draws

class TestDraws:
    def test_drawn_about_as_often_as_one_typical_value(self):
        additions_for("a").add("person.hairstyle", BRAID)
        rt = runtime_for(entry_of(BEACH), profile_id="a", cfg=OFF)
        d = next(iter(prep.realize(entry_of(BEACH), seed=1, profile_id="a", runtime=rt).draws))
        assert BRAID in d.options and d.own is (d.value == BRAID)
        pool = next(iter(rt.options._pools.values()))
        w = dict(zip(pool.items, pool.weights))
        typical = [x.text for x in vocabulary().get("person.hairstyle").values if x.tier == "typical"]
        assert w[BRAID] == pytest.approx(w[typical[0]]) and w[BRAID] == TIER_WEIGHTS["typical"]
        n = sum(1 for got in draws(entry_of(BEACH), "a") if got["hair"].value == BRAID)
        share = w[BRAID] / sum(w.values())
        assert 0 < n and abs(n / len(SEEDS) - share) < 0.04   # about one typical value's share, no more

    def test_another_profile_never_sees_it(self):
        additions_for("a").add("person.hairstyle", BRAID)
        for got in draws(entry_of(CAFE), "b", range(60)):
            assert BRAID not in got["barista.hair"].options

    def test_narrowed_by_the_users_words_offered_not_drawn_until_ticked(self):
        additions_for("a").add("person.hairstyle", BRAID)
        braids = [v for v in hair_values() if "braid" in v][:3]
        e = entry_of(BEACH, filters={"hair": braids})
        seen = [got["hair"] for got in draws(e, "a", range(150))]
        assert all(BRAID in d.options for d in seen)               # offered
        assert {d.value for d in seen} <= set(braids)               # never drawn unticked
        out = pool_options(e, profile_id="a", cfg=OFF)
        assert out["vocab"]["hair"]["tiers"][BRAID] == "opt_in"    # the picker's "drawn only once picked"
        ticked = {got["hair"].value for got in draws(e, "a", range(150), pins={"hair": [braids[0], BRAID]})}
        assert ticked == {braids[0], BRAID}                         # ticked: drawn like a typical value

    def test_standing_for_the_users_stated_value_it_is_offered_only(self):
        additions_for("a").add("person.hairstyle", BRAID)
        e = entry_of(SAID)
        seen = [got["hair"] for got in draws(e, "a", range(60))]
        assert all(d.value == "a high ponytail" and BRAID in d.options for d in seen)
        assert {got["hair"].value for got in draws(e, "a", range(80), pins={"hair": ["a high ponytail", BRAID]})} \
            == {"a high ponytail", BRAID}

    def test_an_option_removed_here_stays_removed(self):
        additions_for("a").add("person.hairstyle", BRAID)
        for got in draws(entry_of(BEACH), "a", range(40), edits={"hair": {"remove": [BRAID]}}):
            assert BRAID not in got["hair"].options

    def test_added_here_and_kept_is_one_option(self):
        additions_for("a").add("person.hairstyle", BRAID)
        d = next(draws(entry_of(BEACH), "a", range(1), edits={"hair": {"add": [BRAID]}}))["hair"]
        assert d.options.count(BRAID) == 1

    def test_never_left_out_for_a_person_under_18(self):
        leotard = "a sequined showgirl leotard"
        additions_for("a").add("person.outfit.summer", leotard)
        d = next(draws(entry_of(AGED), "a", range(1), pins={"age": ["8-year-old"]}))
        assert leotard in d["outfit"].options

    def test_the_age_lists_additions_are_drawn_only_once_ticked(self):
        additions_for("a").add(AGE_LIST, "a 45-year-old")
        seen = [got["age"] for got in draws(entry_of(AGED), "a", range(200))]
        assert all("a 45-year-old" in d.options for d in seen) and all(d.value != "a 45-year-old" for d in seen)
        got = next(draws(entry_of(AGED), "a", range(1), pins={"age": ["a 45-year-old"]}))
        assert got["age"].value == "a 45-year-old"

    def test_a_revision_replays_after_the_addition_is_gone(self):
        additions_for("a").add("person.hairstyle", BRAID)
        e = entry_of(BEACH)
        seed = next(s for s in SEEDS if prep.realize(e, seed=s, profile_id="a").draws[0].value == BRAID)
        rev = prep.realize(e, seed=seed, profile_id="a").revision
        additions_for("a").remove("person.hairstyle", BRAID)
        again = prep.realize(e, seed=seed, profile_id="a", revision=copy.deepcopy(rev))
        assert again.draws[0].value == BRAID

    def test_the_fit_check_never_rerolls_the_users_own(self):
        additions_for("a").add("person.hairstyle", BRAID)
        e = entry_of(CAFE)
        seed = next(s for s in SEEDS if prep.realize(e, seed=s, profile_id="a").draws[0].value == BRAID)
        r = prep.realize(e, seed=seed, profile_id="a")
        assert "barista.hair" not in {d.id for d in judged_picks(r)}
        assert "barista.expr" in {d.id for d in judged_picks(r)}

        class Hates:   # flags everything: only what isn't the user's own may be rerolled
            version, cut = "stub", 0.5

            def p_wrong(self, items):
                return [0.99 for _ in items]
        out, rec = fix_draw(r, judge=Hates(), redraw=lambda s, fx, ed: prep.realize(e, seed=s, fixed=fx, edits=ed,
                                                                                      profile_id="a"),
                            seed=seed, user_prompt="a barista", cut=0.5)
        assert {d.id: d.value for d in out.draws}["barista.hair"] == BRAID
        assert all(h.get("rerolled", {}).get("id") != "barista.hair" for h in rec["rounds"])

    def test_an_option_just_added_in_the_card_is_not_judged_either(self):
        e = entry_of(CAFE)
        mine = "a sleek silver pixie"
        seed = next(s for s in SEEDS if prep.realize(e, seed=s, edits={"barista.hair": {"add": [mine]}},
                                                     profile_id="a").draws[0].value == mine)
        r = prep.realize(e, seed=seed, edits={"barista.hair": {"add": [mine]}}, profile_id="a")
        assert "barista.hair" not in {d.id for d in judged_picks(r)}

    def test_a_hot_draw_made_before_an_addition_is_not_served_after(self):
        from routes.generation import hot_draw_signature
        e = entry_of(BEACH)
        before = hot_draw_signature(e, pins={}, edits={}, zones={}, profile_id="a", project_id=None)
        additions_for("a").add("person.hairstyle", BRAID)
        assert hot_draw_signature(e, pins={}, edits={}, zones={}, profile_id="a", project_id=None) != before
        assert hot_draw_signature(e, pins={}, edits={}, zones={}, profile_id="b", project_id=None) != before  # profile is in it
