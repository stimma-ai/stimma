import numpy as np

from controlnet import _depth_anything_resize_lower_bound, _normalize_depth_for_controlnet


def test_depth_anything_resize_lower_bound_preserves_aspect_and_multiple_of_14():
    image = np.zeros((333, 1000, 3), dtype=np.uint8)

    resized = _depth_anything_resize_lower_bound(image, width=518, height=518, multiple_of=14)

    h, w = resized.shape[:2]
    assert h >= 518
    assert w >= 518
    assert h % 14 == 0
    assert w % 14 == 0

    original_ar = 1000 / 333
    resized_ar = w / h
    assert abs(resized_ar - original_ar) < 0.03


def test_normalize_depth_for_controlnet_uses_robust_percentiles():
    # Dense central range with two extreme outliers.
    base = np.linspace(0.4, 0.6, 512 * 512, dtype=np.float32).reshape(512, 512)
    base[0, 0] = -100.0
    base[-1, -1] = 100.0

    depth_u8 = _normalize_depth_for_controlnet(base)

    assert depth_u8.dtype == np.uint8
    # Robust normalization should still use most of the output range.
    assert int(depth_u8.max()) > 245
    assert int(depth_u8.min()) < 10
