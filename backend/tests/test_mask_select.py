import base64
import io
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

import sam3_service
import sam3_tracker_service
from ben2_service import BEN2Result
from routes import mask_assistant
from sam3_service import BBox, SAM3Detection, SAM3Result
from skywater_service import SkyWaterResult


def _image_data_url(width: int = 4, height: int = 2) -> str:
    image = Image.new("RGB", (width, height), (24, 48, 72))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _png_bytes(values: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(values.astype(np.uint8), mode="L").save(buf, format="PNG")
    return buf.getvalue()


def _response_alpha(response) -> np.ndarray:
    data_url = response.detections[0].mask_data_url
    encoded = data_url.partition(",")[2]
    image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")
    return np.asarray(image)[:, :, 3]


async def test_subject_intent_dispatches_to_ben2_and_preserves_soft_alpha():
    subject = np.array([[0, 64, 128, 255], [7, 80, 192, 240]], dtype=np.uint8)
    service = MagicMock()
    service.subject_alpha = AsyncMock(return_value=BEN2Result(
        alpha=subject, original_width=4, original_height=2,
    ))

    with patch("ben2_service.get_ben2_service", return_value=service):
        response = await mask_assistant.select_mask(mask_assistant.SelectRequest(
            image_data_url=_image_data_url(), intent="subject",
        ))

    assert response.success is True
    assert len(response.detections) == 1
    service.subject_alpha.assert_awaited_once()
    np.testing.assert_array_equal(_response_alpha(response), subject)
    assert set(np.unique(_response_alpha(response))) > {0, 255}


async def test_background_intent_is_exact_subject_alpha_inverse():
    subject = np.array([[0, 1, 127, 255], [12, 64, 128, 250]], dtype=np.uint8)
    service = MagicMock()
    service.subject_alpha = AsyncMock(return_value=BEN2Result(
        alpha=subject, original_width=4, original_height=2,
    ))

    with patch("ben2_service.get_ben2_service", return_value=service):
        response = await mask_assistant.select_mask(mask_assistant.SelectRequest(
            image_data_url=_image_data_url(), intent="background",
        ))

    assert response.success is True
    service.subject_alpha.assert_awaited_once()
    np.testing.assert_array_equal(_response_alpha(response), 255 - subject)


async def test_sky_intent_dispatches_to_skywater_and_preserves_soft_alpha():
    sky = np.array([[0, 32, 160, 255], [0, 80, 220, 255]], dtype=np.uint8)
    service = MagicMock()
    service.sky_alpha = AsyncMock(return_value=SkyWaterResult(
        alpha=sky, score=0.93, original_width=4, original_height=2,
    ))

    with patch("skywater_service.get_skywater_service", return_value=service):
        response = await mask_assistant.select_mask(mask_assistant.SelectRequest(
            image_data_url=_image_data_url(), intent="sky",
        ))

    assert response.success is True
    service.sky_alpha.assert_awaited_once()
    np.testing.assert_array_equal(_response_alpha(response), sky)
    assert response.detections[0].score == pytest.approx(0.93)


async def test_sky_intent_reports_no_sky_for_empty_alpha():
    service = MagicMock()
    service.sky_alpha = AsyncMock(return_value=SkyWaterResult(
        alpha=np.zeros((2, 4), dtype=np.uint8), score=0.2,
        original_width=4, original_height=2,
    ))

    with patch("skywater_service.get_skywater_service", return_value=service):
        response = await mask_assistant.select_mask(mask_assistant.SelectRequest(
            image_data_url=_image_data_url(), intent="sky",
        ))

    assert response.success is False
    assert response.error == "No sky found"


async def test_existing_prompt_request_still_dispatches_to_sam3():
    result = SAM3Result(
        detections=[SAM3Detection(
            bbox=BBox(0, 0, 2, 1),
            score=0.9,
            mask_data=_png_bytes(np.array([[255, 0]], dtype=np.uint8)),
        )],
        original_width=2,
        original_height=1,
    )
    service = MagicMock()
    service.segment = AsyncMock(return_value=result)

    with patch.object(mask_assistant, "get_sam3_service", return_value=service):
        response = await mask_assistant.select_mask(mask_assistant.SelectRequest(
            image_data_url=_image_data_url(2, 1), prompt="cat",
        ))

    assert response.success is True
    service.segment.assert_awaited_once()
    assert service.segment.await_args.kwargs["prompt"] == "cat"


async def test_existing_point_request_still_dispatches_to_tracker():
    result = SAM3Result(
        detections=[SAM3Detection(
            bbox=BBox(0, 0, 2, 1),
            score=0.8,
            mask_data=_png_bytes(np.array([[0, 255]], dtype=np.uint8)),
        )],
        original_width=2,
        original_height=1,
    )
    service = MagicMock()
    service.point_masks = AsyncMock(return_value=result)

    with patch("sam3_tracker_service.get_sam3_tracker_service", return_value=service):
        response = await mask_assistant.select_mask(mask_assistant.SelectRequest(
            image_data_url=_image_data_url(2, 1), point={"x": 0.25, "y": 0.75},
        ))

    assert response.success is True
    service.point_masks.assert_awaited_once()
    assert service.point_masks.await_args.kwargs["points"] == [(0.25, 0.75, 1)]


async def test_point_progress_reports_the_trackers_real_stage():
    service = MagicMock()
    service.selection_stage.return_value = "processing_image"
    request_id = "point-progress-test"
    mask_assistant._register_select_progress(request_id, "point", "image-cache-key")

    with patch("sam3_tracker_service.get_sam3_tracker_service", return_value=service):
        response = await mask_assistant.select_progress(request_id)

    assert response.stage == "processing_image"
    service.selection_stage.assert_called_once_with("image-cache-key")


async def test_sky_progress_reports_skywaters_real_stage():
    service = MagicMock()
    service.selection_stage.return_value = "downloading_model"
    request_id = "sky-progress-test"
    mask_assistant._register_select_progress(request_id, "sky", "image-cache-key")

    with patch("skywater_service.get_skywater_service", return_value=service):
        response = await mask_assistant.select_progress(request_id)

    assert response.stage == "downloading_model"
    service.selection_stage.assert_called_once_with("image-cache-key")


async def test_unknown_progress_request_starts_without_guessing_a_stage():
    response = await mask_assistant.select_progress("not-a-real-selection-request")

    assert response.stage == "starting"


def test_tracker_progress_distinguishes_download_load_encode_and_select(monkeypatch):
    service = sam3_tracker_service.SAM3TrackerService()
    monkeypatch.setattr(
        sam3_tracker_service, "_runtime_encoder_files",
        lambda: sam3_tracker_service.ENCODER_FILES_CPU,
    )
    monkeypatch.setattr(sam3_tracker_service, "_models_present", lambda files: False)
    assert service.selection_stage("image-a") == "downloading_model"

    monkeypatch.setattr(sam3_tracker_service, "_models_present", lambda files: True)
    assert service.selection_stage("image-a") == "loading"

    service._load_stage = "ready"
    service._sess_encoder = object()
    service._sess_decoder = object()
    assert service.selection_stage("image-a") == "processing_image"
    service._embed_cache["image-a"] = []
    assert service.selection_stage("image-a") == "selecting"


def test_prompt_progress_distinguishes_download_load_encode_and_select(monkeypatch):
    service = sam3_service.SAM3Service()
    monkeypatch.setattr(sam3_service, "_models_present", lambda: False)
    assert service.selection_stage("image-a") == "downloading_model"

    monkeypatch.setattr(sam3_service, "_models_present", lambda: True)
    assert service.selection_stage("image-a") == "loading"

    service._load_stage = "ready"
    service._sess_image = object()
    service._sess_language = object()
    service._sess_decoder = object()
    assert service.selection_stage("image-a") == "processing_image"
    service._encoder_cache_key = "image-a"
    assert service.selection_stage("image-a") == "selecting"


@pytest.mark.parametrize("payload", [
    {},
    {"prompt": "cat", "point": {"x": 0.5, "y": 0.5}},
    {"prompt": "cat", "intent": "subject"},
    {"point": {"x": 0.5, "y": 0.5}, "intent": "background"},
])
def test_missing_or_conflicting_request_shapes_fail_clearly(payload):
    with pytest.raises(ValidationError, match="exactly one of point, prompt, or intent"):
        mask_assistant.SelectRequest(image_data_url=_image_data_url(), **payload)


def test_blank_prompt_and_invalid_intent_fail_clearly():
    with pytest.raises(ValidationError, match="Prompt must not be blank"):
        mask_assistant.SelectRequest(image_data_url=_image_data_url(), prompt="   ")
    with pytest.raises(ValidationError, match="Input should be 'subject', 'background' or 'sky'"):
        mask_assistant.SelectRequest(image_data_url=_image_data_url(), intent="person")


def test_segment_mask_conversion_thresholds_and_inverts_alpha():
    from routes.mask_assistant import _convert_grayscale_to_rgba

    gray = Image.new("L", (4, 2), 0)
    gray.putpixel((0, 0), 255)
    gray.putpixel((1, 0), 129)
    gray.putpixel((2, 0), 128)
    buf = io.BytesIO()
    gray.save(buf, "PNG")
    out = Image.open(io.BytesIO(_convert_grayscale_to_rgba(buf.getvalue())))
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0)) == (255, 255, 255, 0)
    assert out.getpixel((1, 0)) == (255, 255, 255, 0)
    assert out.getpixel((2, 0)) == (0, 0, 0, 255)
    assert out.getpixel((3, 1)) == (0, 0, 0, 255)
