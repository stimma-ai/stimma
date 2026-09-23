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

    def test_h3_existing_structure_is_not_mistaken_for_verbatim(self):
        prompt = (
            "integrated_multimodal_description: [Shot 1] A woman says: "
            "<d>[Hindi] [exact words]</d>"
        )
        processed, segments = pp.extract_verbatim(prompt, preserve_h3_structure=True)
        assert "[Shot 1]" in processed
        assert "<d>[Hindi]" in processed
        assert "__VERBATIM_A__" in processed
        assert [segment["original"] for segment in segments] == ["exact words"]

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


class TestH3ReferenceContextValidation:
    def test_requires_every_model_visible_reference_tag(self):
        manifest = [
            {"label": "Picture 1", "kind": "image"},
            {"label": "Audio 1", "kind": "video_audio"},
            {"label": "Video 1", "kind": "video"},
            {"label": "Audio 2", "kind": "audio"},
        ]
        complete = (
            "integrated_multimodal_description: <Picture 1> supplies the subject; "
            "<Audio 1> supplies the voice; <Video 1> supplies the movement; "
            "<Audio 2> supplies the score.\n"
            "overall_soundscape: Use the referenced voice.\n"
            "non_diegetic_music: Use the referenced score."
        )

        assert pp._valid_h3_context_ir(complete, "ref2va", 8, manifest)
        assert not pp._valid_h3_context_ir(
            complete.replace("<Video 1>", "the video"),
            "ref2va",
            8,
            manifest,
        )

    def test_rejects_dialogue_not_grounded_in_user_input(self):
        silent = (
            "integrated_multimodal_description: [Shot 1] The sign reads \"OPEN LATE\".\n\n"
            "overall_soundscape: Room tone.\n\nnon_diegetic_music: N/A"
        )
        invented = silent.replace(
            "The sign reads \"OPEN LATE\".",
            "The sign reads \"OPEN LATE\" as a woman (S1) says: <d>[English] Welcome.</d>",
        )
        assert pp._valid_h3_context_ir(
            silent, "t2va", 5, source_prompt='the sign reads "OPEN LATE"'
        )
        assert not pp._valid_h3_context_ir(
            invented, "t2va", 5, source_prompt='the sign reads "OPEN LATE"'
        )

    def test_accepts_only_user_supplied_dialogue_words(self):
        supplied = (
            "integrated_multimodal_description: [Shot 1] A woman (S1) says: "
            "<d>[English] Welcome.</d>\n\noverall_soundscape: Room tone.\n\n"
            "non_diegetic_music: N/A"
        )
        assert pp._valid_h3_context_ir(
            supplied, "t2va", 5, source_prompt='a woman says "Welcome."'
        )
        assert not pp._valid_h3_context_ir(
            supplied.replace("Welcome.", "Welcome home."),
            "t2va",
            5,
            source_prompt='a woman says "Welcome."',
        )

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
    async def test_h3_context_reaches_enhancer_and_skips_generic_translation(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        seen = {}

        async def fake_improve(request, session):
            seen["request"] = request
            return pe.ImprovePromptResponse(
                improved_prompt="How the reference pictures align with the target video — "
                "Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
                "Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.\n\n"
                "integrated_multimodal_description: [Shot 1] A cyclist rides.\n\n"
                "overall_soundscape: Wind and tires.\n\nnon_diegetic_music: N/A"
            )

        async def fail_translate(request):
            raise AssertionError("H3 Context-IR must remain English and must not be generically translated")

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)
        monkeypatch.setattr(pe, "translate_prompt", fail_translate)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a cyclist rides",
            {
                "autoImprove": {"enabled": True},
                "translate": {"enabled": True, "language": "zh-Hans"},
            },
            model="minimax-h3-i2v",
            is_video=True,
            h3_task="fl2va",
            h3_duration=8,
            h3_media_ids=[11, 22],
            h3_generate_audio=False,
            prompt_preload={
                "originalPrompt": "a cyclist rides",
                "processedPrompt": "a cyclist rides",
                "improvedPrompt": "stale generic warm result",
                "instructions": None,
                "model": "minimax-h3-i2v",
                "isVideo": True,
                "isAudio": False,
                "inputImageCount": 0,
                "promptSourcesSignature": pp.prompt_sources_signature([], []),
            },
        )

        request = seen["request"]
        assert request.h3_task == "fl2va"
        assert request.h3_duration == 8
        assert request.h3_media_ids == [11, 22]
        assert request.h3_generate_audio is False
        assert out.startswith("How the reference pictures align with the target video —")
        assert "[Shot 1]" in out

    async def test_h3_retries_when_context_ir_shape_is_missing(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        attempts = []

        async def fake_improve(request, session):
            attempts.append(request)
            if len(attempts) == 1:
                return pe.ImprovePromptResponse(improved_prompt="a generic cinematic paragraph")
            return pe.ImprovePromptResponse(
                improved_prompt="integrated_multimodal_description: [Shot 1] A baker works.\n\n"
                "overall_soundscape: Quiet room tone.\n\nnon_diegetic_music: N/A"
            )

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)
        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a baker works",
            {"autoImprove": {"enabled": True}},
            model="minimax-h3-t2v",
            is_video=True,
            h3_task="t2va",
            h3_duration=5,
        )

        assert len(attempts) == 2
        assert out.startswith("integrated_multimodal_description:")
        assert "[Shot 1]" in out

    async def test_h3_falls_back_to_original_when_every_attempt_invents_dialogue(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        attempts = []

        async def fake_improve(request, session):
            attempts.append(request)
            return pe.ImprovePromptResponse(
                improved_prompt="integrated_multimodal_description: [Shot 1] "
                "A baker (S1) says: <d>[English] Fresh bread!</d>\n\n"
                "overall_soundscape: Quiet room tone.\n\nnon_diegetic_music: N/A"
            )

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)
        original = "a baker opens the shop"
        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            original,
            {"autoImprove": {"enabled": True}},
            model="minimax-h3-t2v",
            is_video=True,
            h3_task="t2va",
            h3_duration=5,
        )

        assert len(attempts) == 3
        assert out == original

    async def test_h3_preserves_structure_but_unwraps_user_verbatim(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        async def fake_improve(request, session):
            assert "__VERBATIM_A__" in request.prompt
            return pe.ImprovePromptResponse(
                improved_prompt="integrated_multimodal_description: [Shot 1] "
                "The sign reads __VERBATIM_A__.\n\noverall_soundscape: Room tone.\n\n"
                "non_diegetic_music: N/A"
            )

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)
        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "the sign reads [OPEN LATE]",
            {"autoImprove": {"enabled": True}},
            model="minimax-h3-t2v",
            is_video=True,
            h3_task="t2va",
            h3_duration=5,
        )

        assert "[Shot 1]" in out
        assert "<d>" not in out
        assert "reads OPEN LATE" in out
        assert "[OPEN LATE]" not in out

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

    async def test_ideogram_json_mode_honors_explicit_frontend_mode(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        async def fail_improve(request, session):
            raise AssertionError("explicit ideogram-json mode must skip text rewrite")

        async def fake_json(request):
            return pe.IdeogramJsonResponse(json_prompt='{"scene": "from mode"}')

        monkeypatch.setattr(pe, "improve_prompt", fail_improve)
        monkeypatch.setattr(pe, "prompt_to_ideogram_json", fake_json)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a poster",
            {"autoImprove": {"enabled": True, "mode": "ideogram-json"}},
            model=None,
            model_vendor=None,
        )

        assert out == '{"scene": "from mode"}'

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

    async def test_matching_prompt_preload_skips_live_improve(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        wildcards = [{"name": "animal", "values": ["fox"]}]
        segments = [{"name": "style", "content": "watercolor"}]
        monkeypatch.setattr(pp, "_profile_wildcards_and_segments", lambda profile_id: (wildcards, segments))

        async def fail_improve(request, session):
            raise AssertionError("matching preload should skip live improve")

        monkeypatch.setattr(pe, "improve_prompt", fail_improve)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a {{animal}} in {{style}}",
            {"autoImprove": {"enabled": True, "instructions": "make it vivid"}},
            model="flux-dev",
            profile_id="profile-test",
            prompt_preload={
                "originalPrompt": "a {{animal}} in {{style}}",
                "processedPrompt": "a fox in watercolor",
                "improvedPrompt": "a vivid fox in watercolor",
                "instructions": "make it vivid",
                "model": "flux-dev",
                "isVideo": False,
                "isAudio": False,
                "inputImageCount": 0,
                "promptSourcesSignature": pp.prompt_sources_signature(wildcards, segments),
            },
        )

        assert out == "a vivid fox in watercolor"

    async def test_prompt_preload_normalizes_instruction_whitespace(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        async def fail_improve(request, session):
            raise AssertionError("matching preload should tolerate instruction whitespace")

        monkeypatch.setattr(pe, "improve_prompt", fail_improve)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a handbag",
            {"autoImprove": {"enabled": True, "instructions": "  make it vivid  "}},
            model="flux-dev",
            prompt_preload={
                "originalPrompt": "a handbag",
                "processedPrompt": "a handbag",
                "improvedPrompt": "a vivid handbag",
                "instructions": "make it vivid",
                "model": "flux-dev",
                "isVideo": False,
                "isAudio": False,
                "inputImageCount": 0,
                "promptSourcesSignature": pp.prompt_sources_signature([], []),
            },
        )

        assert out == "a vivid handbag"

    async def test_stale_prompt_preload_falls_back_to_live_improve(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import routes.prompt_enhancement as pe

        calls = []

        async def fake_improve(request, session):
            calls.append(request)
            return pe.ImprovePromptResponse(improved_prompt="live improved prompt")

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "original prompt",
            {"autoImprove": {"enabled": True, "instructions": "current instructions"}},
            model="flux-dev",
            prompt_preload={
                "originalPrompt": "original prompt",
                "processedPrompt": "original prompt",
                "improvedPrompt": "stale improved prompt",
                "instructions": "old instructions",
                "model": "flux-dev",
                "isVideo": False,
                "isAudio": False,
                "inputImageCount": 0,
                "promptSourcesSignature": pp.prompt_sources_signature([], []),
            },
        )

        assert out == "live improved prompt"
        assert len(calls) == 1
        assert calls[0].instructions == "current instructions"

    async def test_preload_warmed_without_audio_is_not_reused_once_a_track_is_attached(
        self, generation_app, generation_db_session, monkeypatch
    ):
        """A supplied soundtrack changes the enhancement, so a pool warmed before
        the user attached one must not be served to that submit."""
        import routes.prompt_enhancement as pe

        calls = []

        async def fake_improve(request, session):
            calls.append(request)
            return pe.ImprovePromptResponse(improved_prompt="live improved prompt")

        monkeypatch.setattr(pe, "improve_prompt", fake_improve)

        preload = {
            "originalPrompt": "she turns to the camera",
            "processedPrompt": "she turns to the camera",
            "improvedPrompt": "warmed improved prompt",
            "instructions": None,
            "model": "ltx-2.3",
            "isVideo": True,
            "isAudio": False,
            "inputImageCount": 0,
            "audioConditioned": False,
            "promptSourcesSignature": pp.prompt_sources_signature([], []),
        }

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "she turns to the camera",
            {"autoImprove": {"enabled": True}},
            model="ltx-2.3",
            is_video=True,
            audio_conditioned=True,
            prompt_preload=preload,
        )
        assert out == "live improved prompt"
        assert len(calls) == 1
        assert calls[0].audio_conditioned is True

        # Same preload, same flag → reused without an LLM call.
        preload["audioConditioned"] = True
        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "she turns to the camera",
            {"autoImprove": {"enabled": True}},
            model="ltx-2.3",
            is_video=True,
            audio_conditioned=True,
            prompt_preload=preload,
        )
        assert out == "warmed improved prompt"
        assert len(calls) == 1


class TestUnconfiguredLlmSkipsSteps:
    """A user with zero LLM sources has opted out: stale enhance/translate
    flags must pass the prompt through instead of failing the job. Every
    other LLM failure keeps propagating."""

    async def test_not_configured_skips_enhance_and_translate(
        self, generation_app, generation_db_session, monkeypatch
    ):
        from fastapi import HTTPException
        import routes.prompt_enhancement as pe

        async def not_configured_improve(request, session):
            raise HTTPException(
                status_code=400,
                detail={"code": "llm_not_configured", "message": "No chat model is configured."},
            )

        async def not_configured_translate(request):
            raise HTTPException(
                status_code=400,
                detail={"code": "llm_not_configured", "message": "No chat model is configured."},
            )

        monkeypatch.setattr(pe, "improve_prompt", not_configured_improve)
        monkeypatch.setattr(pe, "translate_prompt", not_configured_translate)

        out = await pp.run_prompt_pipeline(
            _db(generation_db_session),
            "a red fox in the snow",
            {
                "autoImprove": {"enabled": True},
                "translate": {"enabled": True, "language": "zh-Hans"},
            },
        )

        assert out == "a red fox in the snow"

    async def test_other_llm_failures_still_propagate(
        self, generation_app, generation_db_session, monkeypatch
    ):
        import pytest
        from fastapi import HTTPException
        import routes.prompt_enhancement as pe

        async def broken_improve(request, session):
            raise HTTPException(
                status_code=400,
                detail={"code": "llm_insufficient_balance", "message": "No credits."},
            )

        monkeypatch.setattr(pe, "improve_prompt", broken_improve)

        with pytest.raises(HTTPException) as exc:
            await pp.run_prompt_pipeline(
                _db(generation_db_session),
                "a red fox in the snow",
                {"autoImprove": {"enabled": True}},
            )
        assert exc.value.detail["code"] == "llm_insufficient_balance"


def test_image_tags_in_range_rejects_invented_references_only():
    from prompt_pipeline import _image_tags_in_range

    assert _image_tags_in_range("Replace the sky in <image1> with <image2>'s sunset", 2, "sunset sky")
    assert not _image_tags_in_range("Dress <image1> in the coat from <image3>", 2, "coat swap")
    # A tag the user wrote survives even when it points past the inputs.
    assert _image_tags_in_range("Use <image4> as the style", 1, "style from <image4>")
