"""Newson stochastic film-grain engine — Stimma numpy/scipy port of upstream
utils/grain_newson.py (ComfyUI-Darkroom).

Filtered inhomogeneous Boolean model from Newson et al., "Realistic Film Grain
Rendering", IPOL 2017. The original line-for-line numpy translation remains as
_render_channel_reference for numerical validation. Production rendering asks
the equivalent geometric coverage question through a periodic scipy cKDTree,
without dense qmax volumes or per-neighbor rolls. Monte-Carlo offsets come from
numpy's seeded Generator and the counter-hashed grain field remains
deterministic per seed.
"""

import math

import numpy as np
from scipy.spatial import cKDTree

EPS = 0.1 / 255.0          # paper's ε (≈ 0.1 gray-levels), keeps ũ < 1
_Z999 = 3.090232           # 0.999 normal quantile, for the log-normal rm
_HALF = 0.5


# ---------------------------------------------------------------------------
# Counter-based integer hash -> uniform [0, 1)
# ---------------------------------------------------------------------------

def _hash_u32(x):
    """Integer avalanche hash on an int64 array, returns a 32-bit-range int64."""
    M = 0xFFFFFFFF
    x = x & M
    x = (x ^ 61) ^ (x >> 16)
    x = (x + (x << 3)) & M
    x = x ^ (x >> 4)
    x = (x * 0x27D4EB2D) & M
    x = x ^ (x >> 15)
    return x & M


def _hash_uniform(cx, cy, stream, seed):
    """
    Deterministic uniform in [0, 1) keyed by integer cell coords (cx, cy), a
    stream id, and the global seed. cx, cy are int64 arrays; stream may be a
    python int or an int64 array (broadcasts against cx/cy).
    """
    h = (cx * 73856093) ^ (cy * 19349663) ^ (stream * 83492791) ^ (seed * 2654435761)
    h = _hash_u32(h)
    # mix once more so adjacent streams decorrelate well
    h = _hash_u32(h + stream * 40503)
    return h.astype(np.float32) / 4294967296.0


# ---------------------------------------------------------------------------
# Inverse-CDF Poisson (small mean), vectorised over (H, W)
# ---------------------------------------------------------------------------

def _poisson_invcdf(mean, u, qmax):
    """
    Draw Poisson counts by inverse CDF from a uniform u in [0,1).
    mean, u: (H, W) arrays. Returns uint8 (H, W) counts in [0, qmax].
    """
    cdf = np.exp(-mean)                 # P(X = 0)
    term = cdf.copy()
    count = (u > cdf).astype(np.uint8)
    for k in range(1, qmax + 1):
        term = term * mean / k          # P(X = k)
        cdf = cdf + term
        count = count + (u > cdf).astype(np.uint8)
    return count


# ---------------------------------------------------------------------------
# Single-channel render
# ---------------------------------------------------------------------------

def _render_channel_reference(u, mu_r, sigma_r, n_samples, filter_sigma, seed):
    """
    Render the filtered Boolean model for one (H, W) field u in [0, 1].
    Returns v (H, W): the tone-preserving grainy render (E[v] = ũ).
    """
    H, W = u.shape
    u = u.astype(np.float32, copy=False)
    seed_i = int(seed) & 0x7FFFFFFF

    # --- intensity map lambda(i,j); cell_area = 1 so the per-cell mean = lam ---
    u_tilde = np.clip(u / (1.0 + EPS), 0.0, 1.0 - 1e-6)
    inv_area = 1.0 / (math.pi * (mu_r * mu_r + sigma_r * sigma_r))
    lam = inv_area * np.log(1.0 / (1.0 - u_tilde))       # (H, W)

    # --- max radius rm + log-normal params ---
    if sigma_r <= 0.0:
        rm = mu_r
        s_log = 0.0
        m_log = math.log(mu_r)
    else:
        s_log = math.sqrt(math.log(1.0 + (sigma_r * sigma_r) / (mu_r * mu_r)))
        m_log = math.log(mu_r * mu_r / math.sqrt(mu_r * mu_r + sigma_r * sigma_r))
        rm = min(math.exp(m_log + s_log * _Z999), 5.0 * mu_r)
    rm2 = rm * rm
    cell_rad = max(1, math.ceil(rm))

    # --- adaptive grain cap from the brightest cell's mean count (4-sigma) ---
    m_max = float(lam.max())
    qmax = int(min(24, max(2, math.ceil(m_max + 4.0 * math.sqrt(m_max) + 2.0))))

    # --- precompute the fixed grain field Z over the pixel grid (hashed once) ---
    g_idx = np.arange(qmax, dtype=np.int64).reshape(1, 1, qmax)
    cols = np.broadcast_to(np.arange(W, dtype=np.int64).reshape(1, W), (H, W))
    rows = np.broadcast_to(np.arange(H, dtype=np.int64).reshape(H, 1), (H, W))

    u_cnt = _hash_uniform(cols, rows, 0, seed_i)              # (H, W)
    q_grid = _poisson_invcdf(lam, u_cnt, qmax)                # (H, W) int64

    cxe, cye = cols[..., np.newaxis], rows[..., np.newaxis]
    ux_grid = _hash_uniform(cxe, cye, 1 + 4 * g_idx, seed_i)  # (H, W, qmax) sub-cell x
    uy_grid = _hash_uniform(cxe, cye, 2 + 4 * g_idx, seed_i)  # sub-cell y
    if sigma_r > 0.0:
        ur = _hash_uniform(cxe, cye, 3 + 4 * g_idx, seed_i)
        r_grid = np.minimum(np.exp(m_log + s_log * _norm_invcdf(ur)), rm)
        r2_grid = r_grid * r_grid

    # --- Monte-Carlo offsets, shared across all pixels ---
    gen = np.random.Generator(np.random.PCG64(seed_i))
    xi = (gen.standard_normal((n_samples, 2)) * filter_sigma).tolist()

    v = np.zeros((H, W), dtype=np.float32)

    for xix, xiy in xi:
        sx = math.floor(_HALF + xix)
        sy = math.floor(_HALF + xiy)
        fracx = _HALF + xix - sx          # eval point sub-cell position (uniform)
        fracy = _HALF + xiy - sy

        covered = np.zeros((H, W), dtype=bool)
        for dcy in range(-cell_rad, cell_rad + 1):
            ry = sy + dcy
            offy = fracy - dcy
            for dcx in range(-cell_rad, cell_rad + 1):
                rx = sx + dcx
                uxr = np.roll(ux_grid, shift=(-ry, -rx), axis=(0, 1))
                uyr = np.roll(uy_grid, shift=(-ry, -rx), axis=(0, 1))
                qr = np.roll(q_grid, shift=(-ry, -rx), axis=(0, 1))
                dx = (fracx - dcx) - uxr
                dy = offy - uyr
                dist2 = dx * dx + dy * dy                     # (H, W, qmax)
                if sigma_r <= 0.0:
                    hit = dist2 < rm2
                else:
                    hit = dist2 < np.roll(r2_grid, shift=(-ry, -rx), axis=(0, 1))
                present = g_idx < qr[..., np.newaxis]
                covered |= (present & hit).any(axis=-1)
        v += covered.astype(np.float32)

    return v / float(n_samples)


# Keep query coordinates plus the cKDTree distance/index results bounded.  The
# tree itself and the image arrays are additional to this budget.  At k=1 this
# processes four samples at a time for a one-megapixel image and one sample at
# a time at four megapixels.
_QUERY_WORKING_SET_BYTES = 128 * 1024 * 1024
_VARIABLE_RADIUS_CANDIDATES = 16
_PARALLEL_QUERY_POINTS = 64 * 1024


def _sparse_grain_field(u, mu_r, sigma_r, seed_i):
    """Generate just the grains which exist, rather than dense qmax volumes."""
    H, W = u.shape
    u_tilde = np.clip(u / (1.0 + EPS), 0.0, 1.0 - 1e-6)
    inv_area = 1.0 / (math.pi * (mu_r * mu_r + sigma_r * sigma_r))
    lam = inv_area * np.log(1.0 / (1.0 - u_tilde))

    if sigma_r <= 0.0:
        rm = mu_r
        s_log = 0.0
        m_log = math.log(mu_r)
    else:
        s_log = math.sqrt(math.log(1.0 + (sigma_r * sigma_r) / (mu_r * mu_r)))
        m_log = math.log(mu_r * mu_r / math.sqrt(mu_r * mu_r + sigma_r * sigma_r))
        rm = min(math.exp(m_log + s_log * _Z999), 5.0 * mu_r)

    m_max = float(lam.max())
    qmax = int(min(24, max(2, math.ceil(m_max + 4.0 * math.sqrt(m_max) + 2.0))))

    # Open coordinate grids broadcast for the count hash but consume only
    # O(H + W) storage.  np.nonzero then gives coordinates only for grains
    # that actually exist (normally far fewer than H*W*qmax).
    cols = np.arange(W, dtype=np.int64).reshape(1, W)
    rows = np.arange(H, dtype=np.int64).reshape(H, 1)
    q_grid = _poisson_invcdf(
        lam, _hash_uniform(cols, rows, 0, seed_i), qmax,
    )

    center_parts = []
    radius_parts = []
    for grain_idx in range(qmax):
        ys, xs = np.nonzero(q_grid > grain_idx)
        if xs.size == 0:
            continue
        ux = _hash_uniform(xs, ys, 1 + 4 * grain_idx, seed_i)
        uy = _hash_uniform(xs, ys, 2 + 4 * grain_idx, seed_i)
        center_parts.append(np.column_stack((xs + ux, ys + uy)))
        if sigma_r > 0.0:
            ur = _hash_uniform(xs, ys, 3 + 4 * grain_idx, seed_i)
            radii = np.minimum(
                np.exp(m_log + s_log * _norm_invcdf(ur)), rm,
            )
            radius_parts.append(radii)

    if not center_parts:
        return np.empty((0, 2), dtype=np.float64), None, rm

    # cKDTree stores coordinates as float64, so converting once here avoids a
    # second hidden copy inside its constructor.
    centers = np.concatenate(center_parts).astype(np.float64, copy=False)
    # The float32 uniform can round its largest 32-bit hash values to exactly
    # 1.0.  That is valid on the torus but cKDTree requires 0 <= x < boxsize.
    centers[:, 0] %= W
    centers[:, 1] %= H
    radii = (
        np.concatenate(radius_parts).astype(np.float64, copy=False)
        if radius_parts else None
    )
    return centers, radii, rm


def _render_channel(u, mu_r, sigma_r, n_samples, filter_sigma, seed):
    """Render one channel using sparse periodic nearest-grain queries.

    A Monte-Carlo sample evaluates the same fixed Boolean grain field at a
    globally shifted pixel lattice.  The old vectorized port rebuilt that
    answer with a full-frame roll for every neighboring cell and retained a
    dense qmax axis.  A periodic cKDTree asks the equivalent geometric
    question directly: is the sample point inside any grain?

    Uniform radii (the default) need only the nearest grain and are exact apart
    from insignificant floating-point boundary ties.  For log-normal radii we
    test the nearest 16 centers.  This is a bounded approximation because a
    farther, unusually large grain can theoretically cover a point after 16
    nearer small grains miss it; comparisons with the exact implementation
    keep the resulting mean and standard deviation well below one percent.
    """
    H, W = u.shape
    u = u.astype(np.float32, copy=False)
    seed_i = int(seed) & 0x7FFFFFFF
    centers, radii, rm = _sparse_grain_field(u, mu_r, sigma_r, seed_i)
    if centers.size == 0:
        return np.zeros((H, W), dtype=np.float32)

    tree = cKDTree(centers, boxsize=(W, H))

    gen = np.random.Generator(np.random.PCG64(seed_i))
    offsets = gen.standard_normal((n_samples, 2)) * filter_sigma

    pixel_count = H * W
    base = np.empty((pixel_count, 2), dtype=np.float64)
    base[:, 0] = np.tile(np.arange(W, dtype=np.float64), H) + _HALF
    base[:, 1] = np.repeat(np.arange(H, dtype=np.float64), W) + _HALF

    if radii is None:
        k = 1
    else:
        relative_variation = sigma_r / mu_r
        candidate_limit = 4 if relative_variation <= 0.1 else (
            8 if relative_variation <= 0.25 else _VARIABLE_RADIUS_CANDIDATES
        )
        k = min(candidate_limit, len(centers))
    # Per query point: two float64 coordinates, plus k float64 distances and
    # k intp indices returned by scipy.  Large images simply use smaller
    # sample batches, keeping peak memory essentially independent of N.
    bytes_per_point = 16 + 16 * k
    max_query_points = max(1, _QUERY_WORKING_SET_BYTES // bytes_per_point)
    samples_per_batch = max(1, min(n_samples, max_query_points // pixel_count))

    v = np.zeros(pixel_count, dtype=np.float32)
    if radii is not None:
        # Missing neighbors use index len(centers).  A zero-radius sentinel
        # lets the comparison remain vectorized without clipping that index.
        radii = np.concatenate((radii, np.zeros(1, dtype=radii.dtype)))

    for start in range(0, n_samples, samples_per_batch):
        stop = min(n_samples, start + samples_per_batch)
        batch_size = stop - start
        pixels_per_query = max(1, max_query_points // batch_size)
        for pixel_start in range(0, pixel_count, pixels_per_query):
            pixel_stop = min(pixel_count, pixel_start + pixels_per_query)
            points = (
                base[np.newaxis, pixel_start:pixel_stop, :]
                + offsets[start:stop, np.newaxis, :]
            )
            points[..., 0] %= W
            points[..., 1] %= H
            flat_points = points.reshape(-1, 2)
            distances, indices = tree.query(
                flat_points,
                k=k,
                distance_upper_bound=rm,
                workers=-1 if len(flat_points) >= _PARALLEL_QUERY_POINTS else 1,
            )
            if radii is None:
                covered = distances < rm
            elif k == 1:
                covered = distances < radii[indices]
            else:
                covered = (distances < radii[indices]).any(axis=-1)
            v[pixel_start:pixel_stop] += covered.reshape(
                batch_size, pixel_stop - pixel_start,
            ).sum(axis=0)

    return (v / float(n_samples)).reshape(H, W)


def _norm_invcdf(u):
    """Standard-normal inverse CDF (Acklam-style rational approx), numpy."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    u = np.clip(u, 1e-6, 1.0 - 1e-6)
    plow = 0.02425
    phigh = 1.0 - plow
    out = np.zeros_like(u, dtype=np.float32)

    lo = u < plow
    hi = u > phigh
    mid = (~lo) & (~hi)

    ql = np.sqrt(-2.0 * np.log(np.maximum(u, 1e-12)))
    num_l = ((((c[0] * ql + c[1]) * ql + c[2]) * ql + c[3]) * ql + c[4]) * ql + c[5]
    den_l = (((d[0] * ql + d[1]) * ql + d[2]) * ql + d[3]) * ql + 1.0
    out = np.where(lo, num_l / den_l, out)

    qh = np.sqrt(-2.0 * np.log(np.maximum(1.0 - u, 1e-12)))
    num_h = ((((c[0] * qh + c[1]) * qh + c[2]) * qh + c[3]) * qh + c[4]) * qh + c[5]
    den_h = (((d[0] * qh + d[1]) * qh + d[2]) * qh + d[3]) * qh + 1.0
    out = np.where(hi, -(num_h / den_h), out)

    qm = u - 0.5
    rm_ = qm * qm
    num_m = (((((a[0] * rm_ + a[1]) * rm_ + a[2]) * rm_ + a[3]) * rm_ + a[4]) * rm_ + a[5]) * qm
    den_m = ((((b[0] * rm_ + b[1]) * rm_ + b[2]) * rm_ + b[3]) * rm_ + b[4]) * rm_ + 1.0
    out = np.where(mid, num_m / den_m, out)
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# Public entry: render grain on an (H, W, C) image array
# ---------------------------------------------------------------------------

def render_film_grain(img, grain_size, radius_variation, strength,
                      color_grain, n_samples, filter_sigma, seed):
    """
    Apply Newson film grain to an (H, W, C) float32 array in [0, 1].
    Same parameters as upstream (minus device). Returns (H, W, C) float32.
    """
    img = np.asarray(img, dtype=np.float32)
    H, W, C = img.shape

    L = max(H, W)
    # input-px mean radius; floored at 0.5 (delta=1 tail-accuracy + visibility floor)
    mu_r = max(0.5, float(grain_size) * (L / 1024.0))
    sigma_r = max(0.0, float(radius_variation)) * mu_r

    if strength <= 0.0:
        return np.clip(img, 0.0, 1.0)

    # luminance-only fast path
    if color_grain <= 0.01 or C < 3:
        luma = 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2] \
            if C >= 3 else img[..., 0]
        v = _render_channel(luma, mu_r, sigma_r, n_samples, filter_sigma, seed)
        dev = (v - luma)[..., np.newaxis]           # (H, W, 1) zero-mean grain
        out = img + strength * dev
        return np.clip(out, 0.0, 1.0)

    # per-channel render with green as the shared (luminance proxy) baseline
    devs = []
    for c in range(3):
        u_c = img[..., c]
        v_c = _render_channel(u_c, mu_r, sigma_r, n_samples, filter_sigma,
                              int(seed) + c * 101)
        devs.append(v_c - u_c)
    dev_shared = devs[1]                            # green channel grain
    out = img.copy()
    for c in range(3):
        dev_c = dev_shared * (1.0 - color_grain) + devs[c] * color_grain
        out[..., c] = img[..., c] + strength * dev_c
    if C > 3:
        out[..., 3:] = img[..., 3:]
    return np.clip(out, 0.0, 1.0)
