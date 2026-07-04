"""Server-side generate-time prompt pipeline (prompt_pipeline.py) — must stay
behaviorally identical to the frontend's promptProcessor.ts + useSubmissionQueue."""

from types import SimpleNamespace

import prompt_pipeline as pp
import pytest


# --- promptProcessor.ts ports (pure functions) --------------------------------

class TestVerbatim:
    def test_extract_and_restore_roundtrip(self):
        processed, segments = pp.extract_verbatim("a [red car] on a [wet road]")
        assert processed == "a __VERBATIM_A__ on a __VERBATIM_B__"
        assert [s["original"] for s in segments] == ["red car", "wet road"]
        assert pp.restore_verbatim(processed, segments) == "a [red car] on a [wet road]"

    def test_verify_detects_dropped_placeholder(self):
        _, segments = pp.extract_verbatim("[keep me]")
        assert pp.verify_verbatim_preserved("text __VERBATIM_A__ text", segments)
        assert not pp.verify_verbatim_preserved("text without placeholder", segments)

    def test_unwrap(self):
        assert pp.unwrap_verbatim("a [red car] here") == "a red car here"


class TestComments:
    def test_strips_comment_lines_and_collapses_blanks(self):
        prompt = "a cat\n# style note\n\n\n\nsitting on a mat\n  # indented comment"
        assert pp.strip_comments(prompt) == "a cat\n\nsitting on a mat"


class TestWildcards:
    def test_inline_expansion_picks_an_option(self):
        out = pp.expand_wildcards("a {red|blue} car")
        assert out in ("a red car", "a blue car")

    def test_single_option_unwraps(self):
        assert pp.expand_wildcards("a {red} car") == "a red car"

    def test_unresolved_named_token_survives_inline_pass(self):
        assert pp.expand_wildcards("a {{unknown}} thing") == "a {{unknown}} thing"

    def test_named_wildcard_random_pick(self):
        out = pp.expand_named_wildcards("a {{color}} car", [{"name": "color", "values": ["teal"]}])
        assert out == "a teal car"

    def test_segments_win_over_wildcards_and_match_case_insensitively(self):
        out = pp.expand_named_wildcards(
            "{{Style}}",
            [{"name": "style", "values": ["from-wildcard"]}],
            [{"name": "STYLE", "content": "from-segment"}],
        )
        assert out == "from-segment"

    def test_unknown_name_left_as_is(self):
        assert pp.expand_named_wildcards("{{nope}}", [{"name": "other", "values": ["x"]}]) == "{{nope}}"


class TestProcessFinalPrompt:
    def test_resolve_wildcards_for_llm_preserves_comments_and_verbatim(self):
        out = pp.resolve_wildcards_for_llm(
            "{{scene}}\n# keep as guidance\n[exact {tone|tone}]",
            wildcards=[],
            segments=[{"name": "scene", "content": "a {red|red} fox"}],
        )
        assert out == "a red fox\n# keep as guidance\n[exact tone]"

    def test_full_resolution_order(self):
        # {{name}} expands first so segment content gets further processing.
        out = pp.process_final_prompt(
            "{{scene}}\n# a comment\n[verbatim text] and {only}",
            wildcards=[],
            segments=[{"name": "scene", "content": "# seg comment\na {lone} wolf"}],
        )
        assert out == "a lone wolf\nverbatim text and only"


class TestIdeogramDetection:
    def test_matches_toolview_isideogram4(self):
        assert pp.is_ideogram4("ideogram", "ideogram:4@0")
        assert pp.is_ideogram4("Ideogram", "Ideogram 4.0")
        assert not pp.is_ideogram4("ideogram", "ideogram:3@1")
        assert not pp.is_ideogram4("openai", "ideogram:4@0")
        assert not pp.is_ideogram4(None, "ideogram:4@0")


# --- Orchestration (mirrors submitJobAsync steps 1-4) ---------------------------

def _db(session_factory=None):
    return SimpleNamespace(async_session_maker=session_factory)


class TestRunPromptPipeline:
    async def test_enhance_then_translate_then_resolve(self, generation_app, generation_db_session, monkeypatch):
        import routes.prompt_enhancement as pe

        calls = []

        async def fake_improve(request, session):
            calls.append(("improve", request))
            return pe.ImprovePromptResponse(improved_prompt="ENHANCED {a|a} prompt")

        async def fake_translate(request):
            calls.append(("translate", request))
            return pe.TranslatePromptResponse(translated_prompt=request.prompt.replace("ENHANCED", "TRANSLATED"))

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)
        monkeypatch.setattr(pe, "translate_prompt", fake_translate)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "orbit the camera slowly",
            {
                "autoImprove": {"enabled": True, "instructions": "keep it short"},
                "translate": {"enabled": True, "language": "zh-Hans"},
            },
            model="wan-2.7",
            is_video=True,
            media_id=123,
        )

        # Order: improve → translate → final resolve (inline wildcard expanded last)
        assert [name for name, _ in calls] == ["improve", "translate"]
        improve_req = calls[0][1]
        assert improve_req.prompt == "orbit the camera slowly"
        assert improve_req.instructions == "keep it short"
        assert improve_req.is_video is True
        assert improve_req.media_id == 123
        translate_req = calls[1][1]
        assert translate_req.prompt == "ENHANCED {a|a} prompt"
        assert translate_req.target_language == "Simplified Chinese"
        assert out == "TRANSLATED a prompt"

    async def test_resolves_wildcards_before_enhance(self, generation_app, generation_db_session, monkeypatch):
        import routes.prompt_enhancement as pe

        monkeypatch.setattr(
            pp,
            "_profile_wildcards_and_segments",
            lambda profile_id: (
                [{"name": "animal", "values": ["fox"]}],
                [{"name": "scene", "content": "with {red|red} fur"}],
            ),
        )

        seen = {}

        async def fake_improve(request, session):
            seen["prompt"] = request.prompt
            return pe.ImprovePromptResponse(improved_prompt=f"better {request.prompt} plus {{spark|spark}}")

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a {{animal}} {{scene}}\n# lighting note\n[exact words]",
            {"autoImprove": {"enabled": True, "instructions": ""}},
            profile_id="profile-test",
        )

        assert seen["prompt"] == "a fox with red fur\n# lighting note\n__VERBATIM_A__"
        assert out == "better a fox with red fur\nexact words plus spark"

    async def test_verbatim_survives_enhance_via_retry(self, generation_app, generation_db_session, monkeypatch):
        import routes.prompt_enhancement as pe

        attempts = []

        async def fake_improve(request, session):
            attempts.append(request.prompt)
            # Drop the placeholder twice, keep it on the third attempt.
            if len(attempts) < 3:
                return pe.ImprovePromptResponse(improved_prompt="rewrite without placeholder")
            return pe.ImprovePromptResponse(improved_prompt=f"better {request.prompt}")

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "[exact words] and more",
            {"autoImprove": {"enabled": True, "instructions": ""}},
        )
        assert len(attempts) == 3
        # The LLM saw placeholders, never the bracket text.
        assert "__VERBATIM_A__" in attempts[0]
        assert "[exact words]" not in attempts[0]
        # Restored, then unwrapped by final processing.
        assert "exact words" in out
        assert "__VERBATIM_A__" not in out

    async def test_enhance_falls_back_to_original_when_verbatim_never_survives(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        async def fake_improve(request, session):
            return pe.ImprovePromptResponse(improved_prompt="always drops it")

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "[exact words] scene",
            {"autoImprove": {"enabled": True, "instructions": ""}},
        )
        # Falls back to the original prompt (then final-processed).
        assert out == "exact words scene"

    async def test_unknown_translate_language_is_noop(self, generation_app, monkeypatch):
        import routes.prompt_enhancement as pe

        async def fail(request):
            raise AssertionError("translate must be skipped for unknown codes")

        monkeypatch.setattr(pe, "translate_prompt", fail)

        out = await pp.run_prompt_pipeline(
            _db(),
            "as stored",
            {"autoImprove": {"enabled": False, "instructions": ""}, "translate": {"enabled": True, "language": "xx"}},
        )
        assert out == "as stored"

    async def test_final_processing_runs_without_any_options(self, generation_app):
        out = await pp.run_prompt_pipeline(
            _db(),
            "# comment\na [red] {dog|dog}",
            None,
        )
        assert out == "a red dog"

    async def test_ideogram_json_mode_skips_text_rewrite_and_runs_last(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        async def fail_improve(request, session):
            raise AssertionError("text rewrite must not run in ideogram-json mode")

        seen = {}

        async def fake_json(request):
            seen["prompt"] = request.prompt
            seen["size"] = (request.width, request.height)
            return pe.IdeogramJsonResponse(json_prompt='{"scene": "resolved"}')

        monkeypatch.setattr(pe, "improve_prompt", fail_improve)
        monkeypatch.setattr(pe, "prompt_to_ideogram_json", fake_json)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a {sign|sign} that says [OPEN]",
            {"autoImprove": {"enabled": True, "instructions": ""}},
            model="ideogram:4@0",
            model_vendor="ideogram",
            width=1024,
            height=768,
        )
        # JSON conversion sees the fully-resolved prompt and the real canvas.
        assert seen["prompt"] == "a sign that says OPEN"
        assert seen["size"] == (1024, 768)
        assert out == '{"scene": "resolved"}'

    async def test_profile_wildcards_are_used(self, generation_app, monkeypatch):
        monkeypatch.setattr(
            pp,
            "_profile_wildcards_and_segments",
            lambda profile_id: (
                [{"name": "animal", "values": ["fox"]}],
                [{"name": "style", "content": "watercolor"}],
            ),
        )
        out = await pp.run_prompt_pipeline(
            _db(),
            "a {{animal}} in {{style}}",
            None,
            profile_id="profile-test",
        )
        assert out == "a fox in watercolor"
