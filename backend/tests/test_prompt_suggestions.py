from routes.prompt_enhancement import CategoryItem, _stabilize_suggestion_categories


def test_central_human_prompt_gets_stable_core_categories():
    categories = [
        CategoryItem(label="Lighting", category="lighting"),
        CategoryItem(label="Setting", category="setting"),
    ]

    result = _stabilize_suggestion_categories(
        "A portrait of a woman in a rain-soaked alley", categories
    )

    keys = [item.category for item in result]
    assert keys[:6] == [
        "expression",
        "pose",
        "outfit",
        "hair_style",
        "hair_color",
        "age",
    ]
    assert "lighting" in keys
    assert "setting" in keys


def test_identity_category_filtered_when_prompt_does_not_specify_identity():
    categories = [
        CategoryItem(label="Ethnicity", category="ethnicity", allow_wildcard=True),
        CategoryItem(label="Lighting", category="lighting"),
    ]

    result = _stabilize_suggestion_categories(
        "A portrait of a woman in a rain-soaked alley", categories
    )

    keys = [item.category for item in result]
    assert "heritage" not in keys
    assert "ethnicity" not in keys
    assert "lighting" in keys


def test_identity_category_kept_as_heritage_when_prompt_specifies_identity():
    categories = [
        CategoryItem(label="Ethnicity", category="ethnicity", allow_wildcard=True),
        CategoryItem(label="Lighting", category="lighting"),
    ]

    result = _stabilize_suggestion_categories(
        "A portrait of a Japanese woman in a rain-soaked alley", categories
    )

    heritage = next(item for item in result if item.category == "heritage")
    assert heritage.label == "Heritage"
    assert heritage.allow_wildcard is True
