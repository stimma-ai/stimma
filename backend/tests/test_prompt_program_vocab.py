"""Fluent vocabulary: the curated lists slots are read against, their loader (schema, ids,
tiers, tags, facets, shares, browsing, opt-in and adult-only values, context), the writer's
catalog, how a list becomes a seed bank for the variant writer, and article agreement in
emitted text."""

import collections
import json
import random
import re

import pytest

from prompt_programs import variants as V
from prompt_programs.fill import tidy_text
from prompt_programs.narrow import parse_subset
from prompt_programs.variant_pools import Choice, person_pickers
from prompt_programs.vocab import ROOT, TIER_WEIGHTS, _leaf, fill, load, tags_match, template_matches, vocabulary


class TestTheVocabulary:
    def test_it_loads_with_unique_leaves_and_frames(self):
        v = vocabulary()
        assert v.version.startswith("vocab-") and v.leaves and v.nodes
        for leaf in v.leaves.values():
            assert "___" in leaf.frame, leaf.id
            assert leaf.values, leaf.id
            assert all(val.tier in TIER_WEIGHTS for val in leaf.values), leaf.id
            assert leaf.id.rsplit(".", 1)[0] in v.nodes, leaf.id

    def test_person_leaves_are_there_and_some_are_closed(self):
        v = vocabulary()
        assert v.get("person.eye_color").closed and not v.get("person.expression").closed
        assert v.get("nope") is None and v.get(None) is None

    def test_context_defaults_filter_fantasy_values_out(self):
        leaf = vocabulary().get("person.eye_color")
        plain = {x.text for x in leaf.eligible()}
        fantasy = {x.text for x in leaf.eligible({"genre": "fantasy"})}
        assert plain and fantasy - plain  # fantasy-only colors appear only in fantasy

    def test_a_list_the_defaults_would_empty_keeps_its_own_world(self):
        v = vocabulary()
        for lid in ("person.outfit.period", "person.outfit.fantasy", "person.outfit.scifi"):
            assert v.get(lid).eligible()  # bound means the image is in that world
        fantasy = {x.text for x in v.get("person.eye_color").eligible()}
        assert {x.text for x in v.get("person.eye_color").eligible({"genre": "fantasy"})} - fantasy  # gates still hold

    def test_facial_hair_can_be_none(self):
        assert vocabulary().get("person.facial_hair").value("a clean-shaven face") is not None

    def test_examples_are_a_stable_spread(self):
        leaf = vocabulary().get("person.expression")
        a, b = leaf.examples("k"), leaf.examples("k")
        assert a == b and len(a) == 10 and len(set(a)) == 10 and leaf.examples("other") != a

    def test_the_catalog_lists_person_and_animal_ids_without_sample_values(self):
        cat = vocabulary().catalog()
        assert "- person.eye_color: adjective" in cat and "- interior_space.room:" in cat and "- clothing.footwear:" in cat
        assert "person.feature." not in cat   # the face's pieces are shown as the face
        assert "- animal.dog_breed: noun phrase" in cat and "- animal.cat_coat:" in cat
        assert "orange tabby" not in cat
        assert "medium brown" not in cat  # no fixed samples (a shade name like "hazel" is a facet, not a sample)

    def test_places_months_and_seasons_are_offered_by_name(self):
        cat = vocabulary().catalog()
        for lid in ("place.country", "place.city", "place.us_state", "scene.month", "scene.season"):
            assert f"- {lid}:" in cat
        country = vocabulary().get("place.country")
        assert country.closed and country.value("Japan") is not None and country.value("the Netherlands") is not None
        assert all("," not in v.text for v in country.values)   # names, never a description of the place
        assert len(country.values) > 190 and {"Europe", "East Asia"} <= set(country.local_facets["area"])
        assert [v.text for v in vocabulary().get("scene.month").values][:2] == ["January", "February"]
        assert len(vocabulary().get("place.us_state").values) == 50
        season = vocabulary().get("scene.season")
        assert sorted(v.text for v in season.values if v.tier == "typical") == ["autumn", "spring", "summer", "winter"]

    def test_every_place_sits_in_an_area(self):
        for lid in ("place.country", "place.city", "place.us_state"):
            leaf = vocabulary().get(lid)
            areas = set(leaf.local_facets["area"])
            for v in leaf.values:
                assert v.tags.get("area") and set(v.tags["area"]) <= areas, (lid, v.text)
        country = vocabulary().get("place.country")
        south = {v.text for v in country.values if "South America" in v.tags["area"]}
        assert {"Brazil", "Argentina", "Peru", "Guyana"} <= south

    def test_a_near_certain_typo_resolves_and_a_far_one_does_not(self):
        v = vocabulary()
        assert v.resolve("person.eye_eye_color").id == "person.eye_color"
        assert v.resolve("person.eye_colr").id == "person.eye_color"
        assert v.resolve("person.nostril") is None and v.resolve("interior.bedroom") is None

    def test_a_leaf_defined_twice_is_an_error(self, tmp_path):
        for root in ("a", "b"):
            d = tmp_path / root / "person"
            d.mkdir(parents=True)
            (d / "_node.json").write_text('{"id": "person"}')
            (d / "eyes.json").write_text('{"values": [{"text": "brown", "tier": "typical"}]}')
        with pytest.raises(ValueError):
            load((tmp_path / "a", tmp_path / "b"))


class TestArticles:
    @pytest.mark.parametrize("text,want", [
        ("a Irish woman", "An Irish woman"), ("an Korean man", "A Korean man"), ("a hour", "An hour"),
        ("an unicorn", "A unicorn"), ("an European", "A European"), ("a umbrella", "An umbrella"),
        ("a Ukrainian woman", "A Ukrainian woman"), ("a LED lamp", "An LED lamp"), ("an USB cable", "A USB cable"),
        ("She has a oval face.", "She has an oval face."), ("A portrait of a athletic man", "A portrait of an athletic man"),
        ("Plan A in action", "Plan A in action"), ("a bottle of vitamin A oil", "A bottle of vitamin A oil"),
        ("an unimpressed woman", "An unimpressed woman"), ("a uniform", "A uniform"), ("an university", "A university"),
        ("grade A eggs", "Grade A eggs"), ('He said "a apple"', 'He said "an apple"'),
        ('a sign reading "A is for apple"', 'A sign reading "A is for apple"'),
        ("a diagram with labels (A and B)", "A diagram with labels (A and B)"),
        ("a 80-year-old man", "An 80-year-old man"), ("an 65-year-old man", "A 65-year-old man"),
        ("a 8-year-old girl", "An 8-year-old girl"), ("a 11-year-old", "An 11-year-old"),
        ("a 18-year-old", "An 18-year-old"), ("an 13-year-old", "A 13-year-old"),
        ("a 1980s car", "A 1980s car"), ("a 18,000-seat arena", "An 18,000-seat arena"), ("an 110 km road", "A 110 km road"),
        ("An honest, elderly woman.", "An honest, elderly woman."), ("an hour, then", "An hour, then"),
        ("a 8, then a 9", "An 8, then a 9"),
    ])
    def test_a_and_an_follow_the_next_word(self, text, want):
        assert tidy_text([text]) == want


class TestNarrowing:
    def test_parse_subset_keeps_the_lists_order_and_ignores_strangers(self):
        assert parse_subset('Sure: ["25–29", "18–19", "a teenager"]', ["18–19", "20–24", "25–29"]) == ["18–19", "25–29"]
        assert parse_subset("no list here", ["a"]) is None
        assert parse_subset("[]", ["a"]) == []
        assert parse_subset('```json\n["ALL"]\n```', ["a", "b"]) == ["a", "b"]

    def test_the_loader_reads_a_strict_list(self):
        assert vocabulary().get("person.age_band").strict and not vocabulary().get("person.eye_color").strict


# --------------------------------------------------------------------------- templates and palettes

PALETTE = {"label": "Colors", "description": "a color scheme", "pos": "color scheme", "frame": "in ___",
           "facets": [], "closed": True,
           "local_facets": {"color_family": ["red", "blue", "black"], "tone": ["dark", "bright"]},
           "values": [
               {"text": "red, white and gray", "tier": "typical", "roles": {"main": "red", "accent": "white", "neutral": "gray"},
                "tags": {"color_family": ["red"], "tone": ["bright"]}},
               {"text": "navy, white and gray", "tier": "typical", "roles": {"main": "navy", "accent": "white", "neutral": "gray"},
                "tags": {"color_family": ["blue"], "tone": ["dark"]}},
               {"text": "black, gray and white", "tier": "typical", "roles": {"main": "black", "accent": "gray", "neutral": "white"},
                "tags": {"color_family": ["black"], "tone": ["dark"]}}]}
OUTFITS = {"label": "Test outfit", "description": "whole looks", "pos": "noun phrase", "frame": "wearing ___",
           "facets": [], "closed": True, "slots": "person.palette",
           "local_facets": {"sport": ["running", "formal"]},
           "values": [
               {"text": "a {main} technical T-shirt and {accent} running shorts", "tier": "typical", "tags": {"sport": ["running"]}},
               {"text": "a {main} tuxedo with a {accent} shirt", "tier": "typical", "tags": {"sport": ["formal"]},
                "palette": {"tone": ["dark"]}},
               {"text": "a white karate gi", "tier": "typical", "tags": {"sport": ["running"]}}]}

@pytest.fixture
def dressed(monkeypatch):
    v = vocabulary()
    monkeypatch.setitem(v.leaves, "person.palette", _leaf("person.palette", PALETTE))
    monkeypatch.setitem(v.leaves, "person.outfit.test", _leaf("person.outfit.test", OUTFITS))
    return v


class TestTemplates:
    def test_fill_match_and_tags(self):
        t = "a {main} technical T-shirt and {accent} running shorts"
        assert fill(t, {"main": "navy", "accent": "white"}) == "a navy technical T-shirt and white running shorts"
        assert fill(t, None) == "a technical T-shirt and running shorts"
        assert template_matches(t, "a navy technical T-shirt and white running shorts")
        assert not template_matches(t, "a navy hoodie")
        assert tags_match({"tone": ["dark"]}, {"tone": ["dark", "bright"]}) and not tags_match({}, {"tone": "dark"})

    def test_the_catalog_names_lists_not_their_groups_and_hides_the_palette(self, dressed):
        cat = dressed.catalog()
        line = next(ln for ln in cat.splitlines() if ln.startswith("- person.outfit.test"))
        assert "Colors vary separately" in line and "running" not in line and "color_family" not in line
        assert "- person.palette" not in cat

    def test_a_template_seed_reaches_the_writer_filled_from_the_palette(self, dressed):
        b = V.bank("person.outfit.test")
        assert b is not None and "a {main} tuxedo with a {accent} shirt" in b.texts()
        mains = {v["roles"]["main"] for v in PALETTE["values"]}
        cores = [spec.core for k in range(12) for spec in V.draw_seeds(random.Random(k), V.Seeds(core=b), 3).specs]
        assert cores and all("{" not in c for c in cores)
        filled = [c for c in cores if "karate gi" not in c]
        assert filled and all(c.split()[1] in mains for c in filled)


class TestDescentRegions:
    """Descent is browsed by world region: each value in one region, the chooser a row per region."""

    REGIONS = {"East Asia": 6, "Southeast Asia": 8, "South Asia": 10, "Central Asia": 5, "Middle East and North Africa": 16,
               "Sub-Saharan Africa": 14, "Europe": 19, "North America": 4, "Latin America and the Caribbean": 16, "Oceania": 7}

    def test_every_descent_sits_in_one_region(self):
        eth = vocabulary().get("person.ethnicity")
        assert eth.browse == "region" and list(eth.local_facets["region"]) == list(self.REGIONS)
        count = collections.Counter(v.tags["region"][0] for v in eth.values)
        assert all(len(v.tags["region"]) == 1 for v in eth.values) and dict(count) == self.REGIONS
        assert eth.value("Moroccan").tags["region"] == ["Middle East and North Africa"]
        assert eth.value("Ethiopian").tags["region"] == ["Sub-Saharan Africa"]
        assert vocabulary().to_dict()["leaves"][[lf["id"] for lf in vocabulary().to_dict()["leaves"]].index("person.ethnicity")]["browse"] == "region"

    def test_with_no_place_every_region_is_seeded_equally_however_many_values_it_has(self):
        """Regions organize the chooser, and with no place they are the prior: each region an equal
        share of the descent seeds, split evenly among its heritages (places.global_prior)."""
        eth = vocabulary().get("person.ethnicity")
        drawn, standby = eth.pool_values()
        assert not standby and len(drawn) == 105 and {v.weight for v in drawn} == {1.0}
        seeds = V.person_seeds()
        assert len(seeds.descent.values) == 105
        n = 6000
        got = collections.Counter(eth.value(s.descent).tags["region"][0]
                                  for s in V.draw_seeds(random.Random(5), seeds, n).specs)
        for region in self.REGIONS:
            assert abs(got[region] / n - 0.1) < 0.015, (region, got[region] / n)

    def test_the_picker_browses_descent_by_region_in_the_lists_order(self):
        eth = vocabulary().get("person.ethnicity")
        view = person_pickers([], Choice())["descent"]
        assert view["browse"] == "region" and [p["id"] for p in view["parts"]] == list(self.REGIONS)
        assert next(p for p in view["parts"] if p["id"] == "East Asia")["values"][:1] == \
            [v.text for v in eth.values if v.tags["region"] == ["East Asia"]][:1]
        assert sorted(t for p in view["parts"] for t in p["values"]) == sorted(v.text for v in eth.values)

    @pytest.mark.parametrize("browse,values,error", [
        ("area", [{"text": "a", "tier": "typical", "tags": {"region": ["x"]}}], "isn't one of its local facets"),
        ("region", [{"text": "a", "tier": "typical", "tags": {"region": ["x", "y"]}}], "needs exactly one"),
        ("region", [{"text": "a", "tier": "typical"}], "needs exactly one"),
        ("region", [{"text": "a", "tier": "typical", "tags": {"region": ["z"]}}], "needs exactly one"),
    ])
    def test_a_list_browsed_by_a_facet_puts_every_value_in_one_part(self, tmp_path, browse, values, error):
        d = tmp_path / "person"
        d.mkdir()
        (d / "x.json").write_text(json.dumps({"id": "person.x", "label": "X", "description": "", "pos": "adjective",
                                              "frame": "___", "notes": "", "closed": True, "facets": [],
                                              "local_facets": {"region": ["x", "y"]}, "browse": browse, "values": values}))
        with pytest.raises(ValueError, match=error):
            load((tmp_path,))


class TestGender:
    """person.gender is a comprehensive list: never a slot's list, every value pickable, seeded
    by its shares."""

    def test_it_is_valid_and_uncataloged(self):
        v = vocabulary()
        g = v.get("person.gender")
        assert [x.text for x in g.values] == ["woman", "man", "trans woman", "trans man", "non-binary person"]
        assert not g.listed and "person.gender" not in v.catalog() and g.closed
        assert [x.weight for x in g.values] == pytest.approx([0.46, 0.46, 0.027, 0.027, 0.026])
        assert all(x.tier in TIER_WEIGHTS and not x.opt_in and not x.adult_only for x in g.values)
        assert {x.text: x.tags.get("presentation") for x in g.values} == {
            "woman": ["feminine"], "man": ["masculine"], "trans woman": ["feminine"], "trans man": ["masculine"],
            "non-binary person": None}
        assert v.get("person.presentation") is None   # gender replaced it

    def test_every_value_is_pickable(self):
        texts = [x.text for x in vocabulary().get("person.gender").values]
        assert V.bank("person.gender").texts() == texts
        view = person_pickers([], Choice(pins=V.Pins(gender=("non-binary person",))))["gender"]
        assert view["options"] == texts and view["fits"] == texts and view["picked"] == {"values": ["non-binary person"]}
        for t in texts:
            assert V.person_seeds(gender=["woman", "trans woman"]).pinned(V.Pins(gender=(t,))).gender.texts() == [t]


class TestSeedBanks:
    """A vocabulary list as the variant writer's seed bank (variants.bank): opt-in values only
    when the words asked for them, values held for a setting only when the prompt states it,
    adult-only values never for a person who may be under 18."""

    def test_opt_in_values_are_never_seeded_unasked(self):
        ages = V.bank("person.age_band").texts()
        assert ages[0] == "18-year-old" and not any(int(t.split("-")[0]) < 18 for t in ages if t[0].isdigit())
        assert "newborn" not in ages
        assert V.bank("person.age_band", ["10-year-old", "30-year-old"]).texts() == ["10-year-old", "30-year-old"]
        many = {"a couple selfie", "a two-person mirror selfie", "a group selfie"}
        assert not many & set(V.bank("camera.selfie").texts())
        assert "a group selfie" in V.bank("camera.selfie", ["a group selfie", "an arm's-length selfie"]).texts()

    def test_values_held_for_a_setting_wait_for_the_prompt_to_state_it(self):
        leaf = vocabulary().get("lighting.natural")
        assert "space" in leaf.unstated and leaf.needs("overcast daylight") == ("space",)
        unstated = V.bank("lighting.natural").texts()
        assert "overcast daylight" not in unstated and unstated
        assert "overcast daylight" in V.bank("lighting.natural", stated={"space": ("outdoor",)}).texts()
        assert "overcast daylight" not in V.bank("lighting.natural", stated={"space": ("indoor",)}).texts()
        # the slot's words picked it out: seeded whatever the prompt says of the scene
        assert V.bank("lighting.natural", ["overcast daylight", "harsh midday sun"]).texts() == \
            ["overcast daylight", "harsh midday sun"]

    def test_adult_only_values_are_gone_for_a_minor_and_the_users_words_stay(self):
        leaf = vocabulary().get("person.expression")
        adult = {x.text for x in leaf.values if x.adult_only}
        assert adult and adult <= set(V.bank("person.expression").texts())
        assert not adult & set(V.bank("person.expression", minor=True).texts())
        assert V.bank("person.expression", sorted(adult), minor=True) is None
        seeds = V.person_seeds(ages=["9-year-old", "10-year-old"], ideas=[("person.expression", None)])
        assert seeds.minor == ("9-year-old", "10-year-old")
        assert not adult & {t for b in seeds.ideas for t in b.texts()}

    def test_a_list_nothing_is_left_of_or_one_there_isnt_is_no_bank(self):
        assert V.bank("person.nope") is None and V.bank("person.eye_color", []) is None


class TestSharesAndComposedLists:
    """A list may give its parts fixed shares of the draws, and a list may be composed of
    other lists' values (a face is two or three features)."""

    def test_a_parts_share_does_not_depend_on_how_many_values_it_has(self):
        # The shares are of what is drawn unasked: a part's marked (opt-in) values don't take from it.
        nose = vocabulary().get("person.feature.nose")
        shares = json.loads((ROOT / "person" / "feature" / "nose.json").read_text())["shares"]["aspect"]
        by_part = {}
        drawn = [v for v in nose.values if not v.opt_in]
        for v in drawn:
            by_part.setdefault(v.tags["aspect"][0], []).append(v)
        total = sum(v.weight for v in drawn)
        for part, share in shares.items():
            assert abs(sum(v.weight for v in by_part[part]) / total - share / sum(shares.values())) < 1e-9
        assert any(v.opt_in for v in nose.values)

    def test_a_face_is_one_piece_from_the_feature_lists(self):
        v = vocabulary()
        face = v.get("person.face")
        parts = {lid: lf for lid, lf in v.leaves.items() if lid.startswith("person.feature.")}
        assert len(parts) == 12 and {x.text for x in face.values} == {x.text for lf in parts.values() for x in lf.values
                                                                      if x.text != lf.plain}
        assert list(face.parts) == [f"person.feature.{p}" for p in face.local_facets["piece"]]
        assert face.listed and not any(lf.listed for lf in parts.values())
        assert all(x.strength in (1, 2) for lf in parts.values() for x in lf.values)
        for x in face.values:
            assert x.tags["piece"] == [next(lid for lid, lf in parts.items() if lf.value(x.text)).rsplit(".", 1)[-1]]
        assert [x.text for x in face.values] == [x.text for x in load().get("person.face").values]

    def test_an_open_face_draws_only_subtle_pieces_and_a_marked_one_when_ticked(self):
        face = vocabulary().get("person.face")
        drawn, standby = face.pool_values()
        assert drawn and all(x.strength == 1 for x in drawn)
        marked = [x for x in face.values if x.strength == 2]
        assert marked and {x.text for x in marked} <= {x.text for x in standby}
        asked, _ = face.pool_values([marked[0].text])
        assert [x.text for x in asked] == [marked[0].text] and asked[0].weight > 0

    def test_a_face_fits_the_persons_age(self):
        v = vocabulary()
        face, age = v.get("person.face"), v.get("person.age_band")
        pool = [(x.text, x.weight) for x in face.values]

        def at(band):
            return {o for o, w in face.weigh(pool, [("life_stage", age.context_tags(band, "life_stage"))]) if w > 0}
        child, old = at("5-year-old"), at("75-year-old")
        lines = {x.text for x in face.values if x.tags["piece"] == ["age_marks"]}
        assert lines and not lines & child and {x.text for x in face.values if "elderly" in x.tags.get("life_stage", [])} & lines <= old
        young = {x.text for x in face.values if set(x.tags.get("life_stage", ["elderly"])) <= {"baby", "child"}}
        assert young.isdisjoint(old)
        # Removing what doesn't fit leaves the other faces their weight: nothing is scaled up to fill the gap.
        kept = dict(face.weigh(pool, [("life_stage", ("child",))]))
        assert all(kept[o] in (0.0, w) for o, w in pool)

    def test_a_feature_of_one_sex_is_drawn_only_for_that_sex(self):
        face = vocabulary().get("person.face")
        gendered = [x for x in face.values if x.tags["presentation"] != ["feminine", "masculine"]]
        assert all(x.tags["presentation"] for x in face.values)
        assert gendered and all(x.opt_in and len(x.tags["presentation"]) == 1 for x in gendered)
        men = {x.text for x in face.matching({"presentation": "masculine"})}
        assert {x.text for x in gendered if x.tags["presentation"] == ["masculine"]} <= men
        assert not {x.text for x in gendered if x.tags["presentation"] == ["feminine"]} & men


class TestGrayingFollowsAge:
    """Gray hair is drawn as it is seen: never before thirty, seldom in the thirties, more with age."""
    SOME = {"salt-and-pepper", "gray-templed dark brown", "white-streaked black"}
    FULL = {"gray", "white"}

    def pool(self, band):
        from prompt_programs.vocab import vocabulary
        v = vocabulary()
        age = next(x for x in v.get("person.age_band").values if x.text == band)
        fams = tuple(age.tags["graying"]) + tuple("~" + f for f in (age.less_common.get("graying") or ()))
        leaf = v.get("person.hair_color")
        items = [(x.text, x.weight) for x in leaf.values if not x.opt_in]
        got = dict(leaf.weigh(items, [("graying", fams)]))
        total = sum(got.values())
        return {k: w / total for k, w in got.items()}

    def share(self, band, names):
        return sum(w for k, w in self.pool(band).items() if k in names)

    def test_nobody_under_thirty_is_gray(self):
        for band in ("15-year-old", "18-year-old", "20-year-old", "25-year-old"):
            assert self.share(band, self.SOME | self.FULL) == 0

    def test_it_grows_with_age(self):
        thirties, forties = self.share("30-year-old", self.SOME | self.FULL), self.share("40-year-old", self.SOME | self.FULL)
        fifties, sixties = self.share("50-year-old", self.SOME | self.FULL), self.share("60-year-old", self.SOME | self.FULL)
        eighties = self.share("80-year-old", self.FULL)
        assert 0 < thirties < 0.05 < forties < fifties < sixties and eighties > 0.5
        assert self.share("35-year-old", self.FULL) == 0

    def test_the_users_words_for_gray_hair_win_at_any_age(self):
        """A list narrowed to gray for a young person keeps it: a context never empties a pool."""
        from prompt_programs.vocab import vocabulary
        leaf = vocabulary().get("person.hair_color")
        narrowed = [(x.text, x.weight if x.text == "gray" else 0.0) for x in leaf.values if not x.opt_in]
        got = dict(leaf.weigh(narrowed, [("graying", ("none",))]))
        assert got["gray"] > 0

    def test_the_nose_list_names_no_caricature(self):
        from prompt_programs.vocab import vocabulary
        noses = " ".join(x.text for x in vocabulary().get("person.feature.nose").values)
        for word in ("hooked", "points downward", "prominent", "slit-like", "widens a lot"):
            assert word not in noses


class TestAgeList:
    """One value per year, and only the ages under 18 are opt-in."""

    def test_every_year_is_unique_and_only_minors_are_opt_in(self):
        from prompt_programs.vocab import vocabulary
        leaf = vocabulary().get("person.age_band")
        ages = [0 if v.text == "newborn" else int(v.text.split("-")[0]) for v in leaf.values]
        assert ages == list(range(111))
        assert all(v.opt_in == (a < 18) and v.minor == (a < 18) for v, a in zip(leaf.values, ages))


class TestOutfitsKnowWhoTheyAreFor:
    """Every outfit says who it is conventionally worn by, so a man asked for by name isn't
    drawn a dress. An outfit anyone wears carries both parts."""

    OUTFITS = ("athletic", "casual", "cold_weather", "fantasy", "formal", "period", "scifi", "sleep_lounge", "smart", "summer")
    # Checked by hand against the lists: worn by women, never left for a man.
    FEMININE = {
        "person.outfit.casual": ["a {main} knee-length jersey dress with short sleeves",
                                 "a {main} sweatshirt and {neutral} jersey leggings"],
        "person.outfit.cold_weather": ["a {main} teddy-fleece coat over a {accent} long-sleeved jersey dress and {neutral} wool tights"],
        "person.outfit.smart": ["a {main} blouse and a {neutral} pencil skirt", "a {accent} jersey top and a {main} pantsuit"],
        "person.outfit.formal": ["a {main} satin gown with a full skirt", "a {main} crepe jumpsuit with wide tailored legs"],
        "person.outfit.summer": ["a {main} cotton sundress with a gathered waist"],
        "person.outfit.sleep_lounge": ["a white cotton nightgown with long sleeves"],
        "person.outfit.period": ["a {main} wool kirtle over a cream linen shift"],
        "person.outfit.fantasy": ["a {main} hooded cloak over a {neutral} wool dress"],
    }
    # Worn by anyone: left for both.
    ANYONE = {
        "person.outfit.casual": ["a {main} cotton T-shirt and straight blue jeans"],
        "person.outfit.smart": ["a {main} wool suit with a {accent} shirt"],
        "person.outfit.athletic": ["a white cotton karate gi with matching pants"],
        "person.outfit.scifi": ["a {main} flight jumpsuit with {accent} reinforced seams"],
    }

    def leaves(self):
        v = vocabulary()
        return [v.get(f"person.outfit.{n}") for n in self.OUTFITS]

    def test_every_outfit_carries_a_presentation(self):
        for leaf in self.leaves():
            assert leaf.local_facets["presentation"] == ("feminine", "masculine"), leaf.id
            for x in leaf.values:
                got = x.tags.get("presentation")
                assert got and set(got) <= {"feminine", "masculine"}, (leaf.id, x.text)

    def test_the_masculine_part_leaves_no_dresses(self):
        from prompt_programs.vocab import tags_match
        v = vocabulary()
        for lid, texts in self.FEMININE.items():
            leaf = v.get(lid)
            men = {x.text for x in leaf.values if tags_match(x.tags, {"presentation": "masculine"})}
            women = {x.text for x in leaf.values if tags_match(x.tags, {"presentation": "feminine"})}
            for t in texts:
                assert leaf.value(t) is not None, t
                assert t not in men and t in women, t
        for lid, texts in self.ANYONE.items():
            leaf = v.get(lid)
            for t in texts:
                assert set(leaf.value(t).tags["presentation"]) == {"feminine", "masculine"}, t


class TestShortForms:
    """Every value of the person, camera and light lists has a name short enough for a small
    space: its own text, or the short form the file gives. A face is composed of pieces, each
    with its own short form, so the composed list is left out."""

    ROOTS = ("person.", "camera.", "lighting.")
    LIMIT = 24

    def leaves(self):
        return [lf for lf in vocabulary().leaves.values()
                if lf.id.startswith(self.ROOTS) and lf.id != "person.face"]

    def test_every_long_value_has_a_short_form_that_fits(self):
        from prompt_programs.vocab import is_template
        leaves = self.leaves()
        assert len(leaves) > 40
        for leaf in leaves:
            for v in leaf.values:
                if v.short:
                    assert 0 < len(v.short) <= self.LIMIT, (leaf.id, v.short)
                    assert not is_template(v.short) and "{" not in v.short, (leaf.id, v.short)
                    assert v.short.split(" ")[0].lower() not in ("a", "an", "the"), (leaf.id, v.short)
                else:
                    assert len(v.text) <= self.LIMIT, (leaf.id, v.text)

    def test_the_loader_reads_the_short_form_and_falls_back_to_the_value(self):
        v = vocabulary()
        outfit = v.get("person.outfit.casual")
        assert outfit.short("a {main} flannel shirt and {neutral} denim jeans") == "flannel shirt and jeans"
        # A drawn outfit is the template filled with colors; its pill names no colors.
        assert outfit.short("a red flannel shirt and navy denim jeans") == "flannel shirt and jeans"
        light = v.get("lighting.natural")
        assert light.short("low golden-hour sun raking across the scene") == "golden hour"
        assert v.get("person.eye_color").short("hazel") == "hazel"
        assert outfit.short("something the list never had") == "something the list never had"
        assert any(x.get("short") for lf in v.to_dict()["leaves"] if lf["id"] == "lighting.natural" for x in lf["values"])


class TestDogBreeds:
    """A teaching list: about two hundred real breeds nobody could name from memory, browsed by
    breed group, with size to narrow by and the common breeds drawn most."""

    def test_about_two_hundred_breeds_each_once(self):
        leaf = vocabulary().get("animal.dog_breed")
        texts = [v.text for v in leaf.values]
        assert 200 <= len(texts) <= 240
        assert len({t.lower() for t in texts}) == len(texts)

    def test_every_breed_sits_in_one_group_with_a_size(self):
        leaf = vocabulary().get("animal.dog_breed")
        groups, sizes = leaf.local_facets["breed_group"], leaf.local_facets["size"]
        assert {"herding", "hound", "sighthound", "terrier", "toy", "working", "sporting"} <= set(groups)
        for v in leaf.values:
            assert len(v.tags["breed_group"]) == 1 and v.tags["breed_group"][0] in groups, v.text
            assert len(v.tags["size"]) == 1 and v.tags["size"][0] in sizes, v.text
        assert {v.tags["breed_group"][0] for v in leaf.values} == set(groups)

    def test_common_breeds_are_typical_and_rare_ones_are_not(self):
        leaf = vocabulary().get("animal.dog_breed")
        tier = {v.text: v.tier for v in leaf.values}
        for t in ("Labrador retriever", "golden retriever", "German shepherd", "beagle", "French bulldog"):
            assert tier[t] == "typical", t
        for t in ("Azawakh", "Lancashire heeler", "Kishu Ken", "Bergamasco", "otterhound"):
            assert tier[t] == "unusual", t
        assert sum(1 for x in tier.values() if x == "typical") < len(tier) // 5


class TestCameraLists:
    """Each camera list holds one kind of thing, so a slot bound to it is offered only that."""

    def test_lens_values_are_lenses_and_effects_have_their_own_list(self):
        v = vocabulary()
        lens, effect = v.get("camera.lens"), v.get("camera.effect")
        assert set(lens.local_facets) == {"kind"} and set(effect.local_facets) == {"kind"}
        for x in lens.values:
            assert x.tags.get("kind") and set(x.tags["kind"]) <= set(lens.local_facets["kind"]), x.text
            assert x.look, x.text   # described by what it does to the picture
        for x in effect.values:
            assert x.tags.get("kind") and set(x.tags["kind"]) <= set(effect.local_facets["kind"]), x.text
        assert not {x.text for x in lens.values} & {x.text for x in effect.values}
        for moved in ("shallow depth of field and creamy bokeh", "a tilt-shift miniature effect", "a star filter",
                      "a long exposure", "a kaleidoscope prism filter", "deep focus"):
            assert lens.value(moved) is None and effect.value(moved) is not None, moved
        assert {"a 35mm lens", "a 50mm lens", "an 85mm portrait lens"} <= {x.text for x in lens.values}
        assert effect.frame == lens.frame and effect.listed

    def test_shot_size_is_only_shot_sizes(self):
        v = vocabulary()
        ss = v.get("camera.shot_size")
        assert ss.local_facets == {"kind": ("close", "medium", "full", "wide"), "subject": ("person", "general")}
        for x in ss.values:
            assert x.tags["kind"] and x.tags["subject"], x.text
        selfies, angle, genre = v.get("camera.selfie"), v.get("camera.angle"), v.get("camera.genre")
        for text in ("an arm's-length selfie", "a waist-up mirror selfie", "a full-length mirror selfie", "a group selfie"):
            assert ss.value(text) is None and selfies.value(text) is not None, text
        for text in ("an over-the-shoulder shot", "a point-of-view shot"):
            assert ss.value(text) is None and angle.value(text) is not None, text
        for text in ("a two-shot", "a group portrait"):
            assert ss.value(text) is None and genre.value(text) is not None, text
        assert not {x.text for x in ss.values} & {x.text for x in selfies.values}
        assert not {x.text for x in ss.values} & {x.text for x in angle.values}

    def test_framings_say_how_many_people_they_need(self):
        v = vocabulary()
        selfies = v.get("camera.selfie")
        assert selfies.local_facets["people"] == ("one", "two", "group")
        for x in selfies.values:
            assert x.tags.get("people"), x.text
        one = {x.text for x in selfies.matching({"people": "one"})}
        assert "an arm's-length selfie" in one and "a group selfie" not in one and "a couple selfie" not in one
        assert v.get("camera.angle").value("an over-the-shoulder shot").tags["people"] == ["two"]
        assert v.get("camera.genre").value("a group portrait").tags["people"] == ["group"]
        # Framings for more than one person are drawn only when asked for: a selfie is one person's.
        for lid in ("camera.selfie", "camera.angle", "camera.genre"):
            for x in v.get(lid).values:
                many = bool(x.tags.get("people")) and "one" not in x.tags["people"]
                assert x.opt_in == many, (lid, x.text)
        drawn, held = selfies.pool_values()
        assert {x.text for x in held} == {"a couple selfie", "a two-person mirror selfie", "a group selfie"}
        assert "a selfie-stick selfie" in {x.text for x in drawn}


# --------------------------------------------------------------------------- where pictures are set (places.json)

class TestPlaces:
    """The places table: every heritage it names is a descent value, and no name means two places."""

    def test_every_heritage_named_is_a_descent_value_and_shares_fit(self):
        heritages = {v.text for v in vocabulary().get("person.ethnicity").values}
        places = vocabulary().places
        assert len(places) >= 193
        for code, p in places.items():
            assert re.match(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$", code) and p.name and p.shares, code
            assert all(h in heritages and 0 < w <= 1 for h, w in p.shares), code
            assert sum(w for _, w in p.shares) <= 1.0001, code

    def test_names_and_aliases_never_collide(self):
        seen = {}
        for code, p in vocabulary().places.items():
            for name in (p.name, *p.aliases):
                key = name.strip().casefold()
                assert key not in seen, (name, code, seen.get(key))
                seen[key] = code

    def test_the_un_member_states_are_all_there(self):
        un = ("AF AL DZ AD AO AG AR AM AU AT AZ BS BH BD BB BY BE BZ BJ BT BO BA BW BR BN BG BF BI CV KH CM CA CF TD CL CN "
              "CO KM CG CR CI HR CU CY CZ KP CD DK DJ DM DO EC EG SV GQ ER EE SZ ET FJ FI FR GA GM GE DE GH GR GD GT GN GW GY "
              "HT HN HU IS IN ID IR IQ IE IL IT JM JP JO KZ KE KI KW KG LA LV LB LS LR LY LI LT LU MG MW MY MV ML MT MH MR MU "
              "MX FM MD MC MN ME MA MZ MM NA NR NP NL NZ NI NE NG MK NO OM PK PW PA PG PY PE PH PL PT QA KR RO RU RW KN LC VC "
              "WS SM ST SA SN RS SC SL SG SK SI SB SO ZA SS ES LK SD SR SE CH SY TJ TZ TH TL TG TO TT TN TR TM TV UG UA AE GB "
              "US UY UZ VU VE VN YE ZM ZW").split()
        assert len(un) == 193 and not [c for c in un if c not in vocabulary().places]

    def test_a_name_matches_exactly_case_aside(self):
        v = vocabulary()
        assert v.place_named("Japan").code == "JP" and v.place_named("  JAPAN ").code == "JP"
        assert v.place_named("Burma").code == "MM" and v.place_named("Ivory Coast").code == "CI"
        assert v.place_named("Japn") is None and v.place_named("Tokyo") is None and v.place_named("") is None

    @pytest.mark.parametrize("places,error", [
        ({"XX": {"name": "Nowhere", "shares": {"Martian": 0.5}}}, "not a person.ethnicity value"),
        ({"XX": {"name": "Nowhere", "shares": {"Korean": 0.7, "Thai": 0.7}}}, "sum past 1"),
        ({"XX": {"name": "Nowhere", "shares": {"Korean": 0.5}}, "XY": {"name": "Elsewhere", "aliases": ["nowhere"],
                                                                       "shares": {"Thai": 0.5}}}, "stands for both"),
        ({"xx": {"name": "Nowhere", "shares": {"Korean": 0.5}}}, "not ISO 3166"),
    ])
    def test_the_loader_refuses_a_bad_table(self, tmp_path, places, error):
        from prompt_programs.vocab import ROOT, load
        import shutil
        root = tmp_path / "vocab"
        shutil.copytree(ROOT, root)
        (root / "places.json").write_text(json.dumps({"places": places}))
        with pytest.raises(ValueError, match=error):
            load((root,))
