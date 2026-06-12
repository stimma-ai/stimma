"""
Seed the docs-demo sandbox with a curated demo library.

Drives the backend HTTP API exactly like the frontend does: submits real
generation jobs to the demo provider (scripts/docs-shots/demo_provider.py),
then arranges the results into boards and markers. Everything created here
has genuine lineage, so library, remix, and history shots look real.

Usage (backend for the docs-demo sandbox must be running):

    python3 scripts/docs-shots/seed.py --port 9300

Idempotence: re-running adds duplicates. For a clean slate, recreate the
sandbox (stimma fork destroy docs-demo --yes && stimma fork create docs-demo
--empty) and re-apply the provider config — see scripts/docs-shots/README.md.
"""

import argparse
import json
import sys
import time
import urllib.request

BASE = None
PROFILE = None


def api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}",
        method=method,
        headers={"X-Profile-ID": PROFILE or "", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or "null")


# (tool, prompt, width, height, seed) — prompts match the procedural-art look.
GENERATIONS = [
    ("comfyui:flux-dev", "flowing gradient study, teal into amber, soft grain", 1024, 1024, 101),
    ("comfyui:flux-dev", "layered dunes at dusk, warm ember palette", 1344, 768, 102),
    ("comfyui:flux-dev", "translucent ribbons over deep indigo, studio light", 1344, 768, 103),
    ("comfyui:flux-dev", "mid-century geometric poster, harbor blues", 832, 1216, 104),
    ("comfyui:flux-dev", "soft glow field, slate and gold accents", 1024, 1024, 105),
    ("comfyui:flux-dev", "meadow gradient bands, spring greens", 1024, 1024, 106),
    ("comfyui:flux-dev", "dusk gradient with rose undertones", 832, 1216, 107),
    ("comfyui:flux-dev", "poster composition, bold red blocks on cream", 1024, 1024, 108),
    ("comfyui:flux-dev", "deep water gradient, cyan glow currents", 1344, 768, 109),
    ("comfyui:flux-dev", "plum ribbons, quiet motion", 1024, 1024, 110),
    ("comfyui:flux-dev", "ember horizon study, layered waves", 1344, 768, 111),
    ("comfyui:flux-dev", "cream and teal bands, calm rhythm", 1024, 1024, 112),
    ("comfyui:sdxl", "geometric forms, slate palette, gallery wall", 1024, 1024, 201),
    ("comfyui:sdxl", "sunrise gradient, soft amber wash", 1216, 832, 202),
    ("comfyui:sdxl", "indigo poster blocks, modernist layout", 832, 1216, 203),
    ("comfyui:sdxl", "glow studies in deep harbor blue", 1024, 1024, 204),
    ("comfyui:sdxl", "wave silhouettes, warm dusk light", 1216, 832, 205),
    ("comfyui:sdxl", "spring meadow color field", 1024, 1024, 206),
    ("comfyui:sdxl", "red and cream poster shapes", 1024, 1024, 207),
    ("comfyui:sdxl", "ribbon currents, cool palette", 1344, 768, 208),
]

BOARDS = {
    "Brand Refresh": [0, 3, 7, 11, 14, 18],     # indexes into GENERATIONS results
    "Moodboard — Dusk Series": [1, 6, 10, 16],
    "Gallery Prints": [2, 4, 8, 12, 15, 19],
}

FAVORITES = [0, 1, 4, 9, 14, 16]


def submit(tool_id: str, task_type: str, params: dict, folder: str) -> int:
    out = api("POST", "/api/generate/submit", {
        "tool_id": tool_id,
        "task_type": task_type,
        "folder_path": folder,
        "parameters": params,
        # The API defaults to 24h auto-delete; demo media must persist.
        "auto_delete_duration": None,
    })
    return out["job_id"]


def wait_for(job_ids: list[int], timeout: float = 300) -> dict[int, int]:
    """Wait for jobs; return job_id → result_media_id."""
    deadline = time.time() + timeout
    done: dict[int, int] = {}
    while time.time() < deadline and len(done) < len(job_ids):
        ids = ",".join(str(j) for j in job_ids)
        for job in api("GET", f"/api/generate/jobs/status?ids={ids}"):
            if job["status"] == "completed":
                done[job["id"]] = job["result_media_id"]
            elif job["status"] in ("failed", "cancelled"):
                raise RuntimeError(f"job {job['id']} {job['status']}: {job.get('error')}")
        time.sleep(1)
    if len(done) < len(job_ids):
        raise TimeoutError(f"only {len(done)}/{len(job_ids)} jobs completed")
    return done


def main() -> None:
    global BASE, PROFILE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9300)
    args = ap.parse_args()
    BASE = f"http://localhost:{args.port}"

    profiles = api("GET", "/api/profiles")["profiles"]
    PROFILE = profiles[0]["id"]
    print(f"profile: {PROFILE}")

    # The profile's generate-capable folder is where outputs land.
    folder = api("GET", "/api/generate/folder")["path"]
    print(f"folder: {folder}")

    # 1. Base generations
    job_ids = []
    for tool, prompt, w, h, seed in GENERATIONS:
        job_ids.append(submit(tool, "text-to-image", {
            "prompt": prompt, "width": w, "height": h, "seed": seed,
        }, folder))
    print(f"submitted {len(job_ids)} generations")
    media = wait_for(job_ids)
    media_ids = [media[j] for j in job_ids]  # in GENERATIONS order
    print(f"completed: {media_ids}")

    # 2. Lineage chains: upscale two results, restyle one, cut out one.
    chain_jobs = {
        "upscale-a": submit("comfyui:ultrasharp-4x", "upscale-image",
                            {"input_images": [media_ids[1]], "scale_factor": 2}, folder),
        "upscale-b": submit("comfyui:ultrasharp-4x", "upscale-image",
                            {"input_images": [media_ids[14]], "scale_factor": 2}, folder),
        "restyle": submit("comfyui:kontext-edit", "image-to-image",
                          {"prompt": "shift the palette toward warm ember tones",
                           "input_images": [media_ids[0]], "strength": 0.6, "seed": 7}, folder),
        "cutout": submit("comfyui:birefnet", "remove-background",
                         {"input_images": [media_ids[7]]}, folder),
    }
    chain_media = wait_for(list(chain_jobs.values()))
    print(f"lineage chains: {chain_media}")

    # 3. Boards
    for name, indexes in BOARDS.items():
        board = api("POST", "/api/boards", {"name": name})
        api("POST", f"/api/boards/{board['id']}/items",
            {"media_ids": [media_ids[i] for i in indexes]})
        print(f"board '{name}': {len(indexes)} items")

    # 4. Favorites
    markers = api("GET", "/api/markers")
    fav = next(m for m in markers if m["name"].lower() == "favorite")
    for i in FAVORITES:
        api("POST", f"/api/media/{media_ids[i]}/markers/{fav['id']}")
    print(f"favorited {len(FAVORITES)} items")

    print("seed complete")


if __name__ == "__main__":
    main()
