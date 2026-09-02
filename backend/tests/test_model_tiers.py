"""Tier classification and `auto` role selection."""
import pytest

from model_tiers import (
    BALANCED,
    DEEP,
    FAST,
    ModelCandidate,
    ROLE_TIERS,
    is_specialty,
    select_auto_models,
    tier_for,
)


def c(slug, vendor=None, name=None, model_id=None):
    return ModelCandidate(slug=slug, name=name or slug, vendor=vendor, model_id=model_id)


class TestTierFor:
    @pytest.mark.parametrize("slug,expected", [
        ("stimma:claude-opus-5", DEEP),
        ("stimma:claude-sonnet-5", BALANCED),
        ("stimma:claude-haiku-4.5", FAST),
        ("stimma:gpt-5.6-sol", DEEP),
        ("stimma:gpt-5.6-terra", BALANCED),
        ("stimma:gpt-5.6-luna", FAST),
        ("stimma:kimi-k2.7", DEEP),
        ("stimma:minimax-m3", BALANCED),
        ("stimma:stepfun-3.7-flash", FAST),
    ])
    def test_curated_cloud_slugs(self, slug, expected):
        assert tier_for(c(slug)) == expected

    def test_branded_provider_ids_use_model_id(self):
        # A BYO Anthropic key produces id "anthropic:claude-haiku-4-5-20251001".
        assert tier_for(c("anthropic:claude-haiku-4-5-20251001",
                          model_id="claude-haiku-4-5-20251001")) == FAST
        assert tier_for(c("anthropic:claude-opus-5", model_id="claude-opus-5")) == DEEP

    @pytest.mark.parametrize("model_id,expected", [
        ("qwen3-8b", FAST),
        ("llama-3.3-70b-instruct", BALANCED),
        ("qwen3-235b-a22b", DEEP),
        ("mixtral-8x22b", DEEP),          # 8 x 22B = 176B total
        ("mistral-7b-instruct", FAST),
    ])
    def test_size_parse(self, model_id, expected):
        assert tier_for(c(f"openrouter:{model_id}", model_id=model_id)) == expected

    @pytest.mark.parametrize("model_id,expected", [
        ("some-model-flash", FAST),
        ("vendor-thing-mini", FAST),
        ("house-model-pro", DEEP),
        ("deepseek-reasoner", DEEP),
    ])
    def test_name_markers(self, model_id, expected):
        assert tier_for(c(f"together:{model_id}", model_id=model_id)) == expected

    def test_unknown_is_balanced(self):
        assert tier_for(c("local:my-finetune", model_id="my-finetune")) == BALANCED

    def test_size_beats_name_marker(self):
        # "flash" says fast, but 200B says otherwise. Size is the harder signal.
        assert tier_for(c("or:flash-200b", model_id="flash-200b")) == DEEP

    def test_openrouter_namespaced_ids(self):
        assert tier_for(c("or:anthropic/claude-opus-5",
                          model_id="anthropic/claude-opus-5")) == DEEP


class TestSpecialty:
    def test_fable_excluded(self):
        assert is_specialty(c("stimma:claude-fable-5"))
        assert is_specialty(c("stimma:claude-fable-5.1"))
        # Cloud rows look up by canonical_model_id, BYO rows by the provider's
        # own id — the dashed spelling has to be excluded too.
        assert is_specialty(c("stimma:claude-fable-5.1",
                              model_id="anthropic:claude-fable-5-1"))
        assert not is_specialty(c("stimma:claude-opus-5"))


class TestSelectAutoModels:
    def test_nothing_available(self):
        assert select_auto_models([]) == {role: None for role in ROLE_TIERS}

    def test_single_model_serves_every_role(self):
        chosen = select_auto_models([c("local:qwen3-8b", vendor="alibaba",
                                       model_id="qwen3-8b")])
        assert set(chosen.values()) == {"local:qwen3-8b"}

    def test_anthropic_family_wins_and_stays_coherent(self):
        chosen = select_auto_models([
            c("stimma:claude-opus-5", vendor="anthropic"),
            c("stimma:claude-sonnet-5", vendor="anthropic"),
            c("stimma:claude-haiku-4.5", vendor="anthropic"),
            c("stimma:gpt-5.6-sol", vendor="openai"),
            c("stimma:minimax-m3", vendor="minimax"),
        ])
        assert chosen["chat"] == "stimma:claude-opus-5"
        assert chosen["tool_assistant"] == "stimma:claude-sonnet-5"
        assert chosen["flow"] == "stimma:claude-sonnet-5"
        assert chosen["quick_task"] == "stimma:claude-haiku-4.5"

    def test_fable_never_auto_selected(self):
        chosen = select_auto_models([
            c("stimma:claude-fable-5.1", vendor="anthropic",
              model_id="anthropic:claude-fable-5-1"),
            c("stimma:claude-sonnet-5", vendor="anthropic"),
            c("stimma:claude-haiku-4.5", vendor="anthropic"),
        ])
        assert "stimma:claude-fable-5.1" not in chosen.values()
        assert chosen["chat"] == "stimma:claude-sonnet-5"

    def test_openai_only_install(self):
        chosen = select_auto_models([
            c("openai:gpt-5.6-sol", vendor="openai", model_id="gpt-5.6-sol"),
            c("openai:gpt-5.6-terra", vendor="openai", model_id="gpt-5.6-terra"),
            c("openai:gpt-5.6-luna", vendor="openai", model_id="gpt-5.6-luna"),
        ])
        assert chosen["chat"] == "openai:gpt-5.6-sol"
        assert chosen["tool_assistant"] == "openai:gpt-5.6-terra"
        assert chosen["quick_task"] == "openai:gpt-5.6-luna"

    def test_multiple_local_models_span_tiers(self):
        chosen = select_auto_models([
            c("local:qwen3-8b", vendor="alibaba", model_id="qwen3-8b"),
            c("local:qwen3-235b-a22b", vendor="alibaba", model_id="qwen3-235b-a22b"),
        ])
        assert chosen["quick_task"] == "local:qwen3-8b"
        assert chosen["chat"] == "local:qwen3-235b-a22b"

    def test_no_family_spans_tiers_falls_back_across_vendors(self):
        # One deep xAI model, one fast StepFun model — neither family covers two
        # tiers, so roles match per tier across everything.
        chosen = select_auto_models([
            c("stimma:grok-4.5", vendor="xai"),
            c("stimma:stepfun-3.7-flash", vendor="stepfun"),
        ])
        assert chosen["chat"] == "stimma:grok-4.5"
        assert chosen["quick_task"] == "stimma:stepfun-3.7-flash"

    def test_deep_role_never_downgrades_when_deep_exists(self):
        chosen = select_auto_models([
            c("stimma:claude-opus-5", vendor="anthropic"),
            c("stimma:claude-haiku-4.5", vendor="anthropic"),
        ])
        assert chosen["chat"] == "stimma:claude-opus-5"
        assert chosen["quick_task"] == "stimma:claude-haiku-4.5"
        # No balanced model in the family; tool assistant biases up, not down.
        assert chosen["tool_assistant"] == "stimma:claude-opus-5"


class TestSeedEffort:
    """A role's starting effort comes from the model's OWN declared levels —
    `reasoning.default` and `reasoning.quick_task` — so nothing invents a
    vocabulary the catalog didn't already have, and the result is always a
    concrete rung of that model's ladder."""

    ANTHROPIC = ["off", "low", "medium", "high", "xhigh", "max"]
    COARSE = ["off", "high"]                        # MiniMax: no cheap middle
    GEMINI = ["minimal", "low", "medium", "high"]   # no "off" at all

    def test_background_roles_take_the_model_cheap_level(self):
        from model_tiers import seed_effort
        for role in ("quick_task", "tool_assistant"):
            assert seed_effort(role, self.ANTHROPIC, "high", "off") == "off"
            assert seed_effort(role, self.GEMINI, "medium", "minimal") == "minimal"

    def test_chat_takes_the_model_normal_level(self):
        from model_tiers import seed_effort
        assert seed_effort("chat", self.ANTHROPIC, "high", "off") == "high"
        assert seed_effort("chat", self.GEMINI, "medium", "minimal") == "medium"

    def test_flows_take_one_rung_above_cheap(self):
        from model_tiers import seed_effort
        assert seed_effort("flow", self.ANTHROPIC, "high", "off") == "low"
        assert seed_effort("flow", self.GEMINI, "medium", "minimal") == "low"

    def test_flows_stay_cheap_when_one_rung_up_is_the_maximum(self):
        # off/high has no middle: "a little thinking" would mean the model's most
        # expensive setting, on the one role whose cost multiplies over every
        # item it processes.
        from model_tiers import seed_effort
        assert seed_effort("flow", self.COARSE, "high", "off") == "off"

    def test_a_model_with_no_ladder_has_nothing_to_seed(self):
        from model_tiers import seed_effort
        assert seed_effort("chat", [], "high", "off") is None
        assert seed_effort("quick_task", None, None, None) is None

    def test_metadata_outside_the_ladder_is_ignored(self):
        """Catalog entries drift; a `default` no longer on the ladder must not
        become the seeded level."""
        from model_tiers import seed_effort
        assert seed_effort("chat", self.COARSE, "medium", "off") == "high"
        assert seed_effort("quick_task", self.COARSE, "high", "minimal") == "off"
