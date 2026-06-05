import numpy as np

from utils import image_ops


def test_bgr_rgb_roundtrip():
    rng = np.random.default_rng(7)
    bgr = rng.integers(0, 256, size=(32, 48, 3), dtype=np.uint8)
    rgb = image_ops.bgr_to_rgb(bgr)
    bgr2 = image_ops.rgb_to_bgr(rgb)
    assert np.array_equal(bgr, bgr2)


def test_resize_float32_shape_and_dtype():
    rng = np.random.default_rng(11)
    depth = rng.normal(size=(64, 96)).astype(np.float32)
    resized = image_ops.resize(depth, (160, 120), mode="bicubic")
    assert resized.shape == (120, 160)
    assert resized.dtype == np.float32


def test_threshold_otsu_bimodal():
    gray = np.zeros((32, 32), dtype=np.uint8)
    gray[:, :16] = 15
    gray[:, 16:] = 220
    threshold = image_ops.threshold_otsu(gray)
    assert 15 <= threshold <= 220
    out = image_ops.threshold_binary(gray, threshold)
    assert out[:, :16].max() == 0
    assert out[:, 16:].min() == 255


def test_affine_identity_warp():
    rng = np.random.default_rng(31)
    img = rng.integers(0, 256, size=(112, 112, 3), dtype=np.uint8)
    src = np.array(
        [[10.0, 20.0], [80.0, 25.0], [50.0, 60.0], [25.0, 95.0], [85.0, 95.0]],
        dtype=np.float32,
    )
    m = image_ops.estimate_affine(src, src)
    assert m is not None
    warped = image_ops.warp_affine(img, m, (112, 112))
    # Bilinear resampling introduces tiny differences; keep tolerance tight.
    mae = np.mean(np.abs(warped.astype(np.int16) - img.astype(np.int16)))
    assert mae < 1.0


def test_canny_output_shape_and_values():
    img = np.zeros((64, 64), dtype=np.uint8)
    img[16:48, 16:48] = 255
    edges = image_ops.canny(img, low_thresh=40, high_thresh=80)
    assert edges.shape == img.shape
    assert edges.dtype == np.uint8
    assert set(np.unique(edges)).issubset({0, 255})
