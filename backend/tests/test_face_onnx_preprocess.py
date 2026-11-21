"""SCRFD preprocessing feeds the network RGB, as upstream does."""

import numpy as np

from face_onnx import SCRFDDetector


def test_scrfd_preprocess_swaps_bgr_to_rgb():
    det = SCRFDDetector.__new__(SCRFDDetector)
    det.det_size = (640, 640)
    bgr = np.zeros((640, 640, 3), dtype=np.uint8)
    bgr[..., 0] = 255  # pure blue in BGR
    tensor, scale, size = det._preprocess(bgr)
    assert scale == 1.0 and size == (640, 640)
    # Channel 0 of the NCHW tensor is red (0 -> -127.5/128), channel 2 is blue.
    assert np.allclose(tensor[0, 0], -127.5 / 128.0)
    assert np.allclose(tensor[0, 2], 127.5 / 128.0)
