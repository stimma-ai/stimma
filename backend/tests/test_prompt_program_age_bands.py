from prompt_programs import variants as V, variant_pools as P
from prompt_programs.age_bands import BANDS, bands, bands_of
from prompt_programs.choices import expand


def test_bands_partition_all_ages_without_changing_appearance_stages():
    ages = V.year_ages(list(range(111)))
    offered = bands(ages)
    flattened = [a for values in offered.values() for a in values]
    assert flattened == ages and len(flattened) == len(set(flattened)) == 111
    assert len(offered) == len(BANDS)
    assert bands_of("35-year-old") == ("35-39",)
    assert V.stages_of("35-year-old") == ("young adult", "middle-aged")
    assert bands_of("newborn") == ("0-1",)
    assert bands_of("110-year-old") == ("80+",)
    assert bands_of("nonsense") == bands_of(None) == ()


def test_bands_intersect_prompt_ages_and_never_offer_minors_by_default():
    assert min(V.age_years(a) for values in bands().values() for a in values) == 18
    assert bands(V.year_ages(list(range(28, 33)))) == {
        "25-29": ["28-year-old", "29-year-old"],
        "30-34": ["30-year-old", "31-year-old", "32-year-old"],
    }
    assert bands(V.year_ages([16, 17, 18, 19])) == {
        "16-17": ["16-year-old", "17-year-old"], "18-24": ["18-year-old", "19-year-old"],
    }


def test_numeric_and_saved_legacy_choices_seed_and_filter_the_same_years():
    for choice in (V.Pins(age=("35-39",)), V.Pins(age=("young adult",)),
                   V.Pins(age=("30-34",), years=(48,))):
        drawn = set(choice.ages())
        matched = {a for a in V.allowed_ages() if P.matches({"age": a}, choice)}
        assert matched == drawn
    assert V.Pins(age=("young adult",)).ages() == V.year_ages(list(range(18, 40)))
    assert not P.matches({"age": "34-year-old"}, V.Pins(age=("35-39",)))
    assert P.matches({"age": "35-year-old"}, V.Pins(age=("35-39",)))


def test_choice_expansion_preserves_legacy_and_sanitizes_numeric_years():
    entry = {"slots": [{"id": "p", "kind": "person"}], "seeds": {"p": {
        "banks": [{"role": "age", "narrowed": V.year_ages(list(range(28, 33)))}],
    }}}
    _, _, chosen = expand(entry, {"p": {"seeds": {"age": {
        "values": ["young adult", "25-29", "30-34", "16-17", "80+"], "years": [16, 28, 90],
    }}}})
    pins = chosen["p"].pins
    assert pins.age == ("young adult", "25-29", "30-34") and pins.years == (28,)
    assert pins.ages(V.year_ages(list(range(28, 33)))) == V.year_ages(list(range(28, 33)))


def test_prepared_prompt_cache_tracks_age_interpretation_version(monkeypatch):
    from prompt_programs import narrow, slots
    before = slots._key("fake-model", "a <college student>", {})
    monkeypatch.setattr(narrow, "NARROW_VERSION", "test-new-age-interpretation")
    assert slots._key("fake-model", "a <college student>", {}) != before
