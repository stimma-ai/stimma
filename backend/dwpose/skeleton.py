"""Skeleton rendering for DWPose keypoints.

Renders keypoints as filled circles and bones as lines onto a BGR canvas,
matching the visual output of rtmlib's mmpose-style draw_skeleton.

Color convention: keypoint/bone colors in the coco133 dict are intended
to be passed directly to cv2 (which interprets them as BGR). We render
on a BGR numpy array via PIL — PIL byte order is mode-agnostic, so
colors written through ImageDraw end up in the same byte positions
regardless of mode label.
"""

import numpy as np
from PIL import Image, ImageDraw

from .coco133 import coco133


def draw_skeleton(
    img: np.ndarray,
    keypoints: np.ndarray,
    scores: np.ndarray,
    kpt_thr: float = 0.5,
    radius: int = 2,
    line_width: int = 2,
) -> np.ndarray:
    """Draw COCO-133 wholebody skeleton on a BGR image.

    Args:
        img: BGR uint8 image (H, W, 3) to draw on.
        keypoints: (N, 133, 2) array of (x, y) per-instance keypoints.
        scores: (N, 133) array of confidence scores.
        kpt_thr: minimum score for a keypoint to be drawn.
        radius: keypoint circle radius in pixels.
        line_width: bone line thickness in pixels.

    Returns:
        New BGR uint8 image with skeleton drawn.
    """
    if keypoints.ndim == 2:
        keypoints = keypoints[None, :, :]
        scores = scores[None, :]

    keypoint_info = coco133["keypoint_info"]
    skeleton_info = coco133["skeleton_info"]

    name_to_id = {info["name"]: info["id"] for info in keypoint_info.values()}

    # PIL is mode-label agnostic at the byte level. We tell it 'RGB' but
    # the underlying buffer is BGR; colors flow through unchanged.
    pil = Image.fromarray(img, mode="RGB")
    draw = ImageDraw.Draw(pil)

    for inst_idx in range(keypoints.shape[0]):
        kpts = keypoints[inst_idx]
        sc = scores[inst_idx]
        vis = sc >= kpt_thr

        for ske in skeleton_info.values():
            link = ske["link"]
            i0 = name_to_id[link[0]]
            i1 = name_to_id[link[1]]
            if not (vis[i0] and vis[i1]):
                continue
            color = tuple(int(c) for c in ske["color"])
            x0, y0 = float(kpts[i0, 0]), float(kpts[i0, 1])
            x1, y1 = float(kpts[i1, 0]), float(kpts[i1, 1])
            draw.line((x0, y0, x1, y1), fill=color, width=int(line_width))

        for kpt_id, info in keypoint_info.items():
            if not vis[kpt_id]:
                continue
            color = tuple(int(c) for c in info["color"])
            x, y = float(kpts[kpt_id, 0]), float(kpts[kpt_id, 1])
            r = float(radius)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

    return np.asarray(pil, dtype=np.uint8)
