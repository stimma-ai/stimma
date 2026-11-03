"""Durable transport receipts: recover downloads without repeating generation."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import aiohttp

from .base import ExecutionResult, OutputAsset, OutputSidecar


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temp, path)


def receipt_location(output_path, provider_id, request_id):
    if not output_path:
        return None
    key = hashlib.sha256(f"{provider_id}:{request_id}".encode()).hexdigest()[:32]
    return Path(output_path).parent / ".stp-receipts" / key


async def materialize_result(provider, data, receipt_root=None):
    output = data.get("output") or {}
    metadata = dict(data.get("metadata") or {})
    if output.get("input_usage"):
        metadata["input_usage"] = output["input_usage"]
    assets = sorted(output.get("assets") or [], key=lambda a: 0 if a.get("role", "primary") == "primary" else 1)
    hashes_path = receipt_root / "hashes.json" if receipt_root else None
    hashes = json.loads(hashes_path.read_text()) if hashes_path and hashes_path.exists() else {}

    async def fetch(asset_id, name):
        suffix = Path(asset_id).suffix
        suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,16}", suffix) else ".bin"
        path = receipt_root / (name + suffix) if receipt_root else None
        if path and path.is_file():
            raw = await asyncio.to_thread(path.read_bytes)
            if hashes.get(path.name) == {"asset_id": asset_id, "sha256": hashlib.sha256(raw).hexdigest()}:
                return raw, str(path)
        raw = await provider.download_asset(asset_id)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            await asyncio.to_thread(temp.write_bytes, raw)
            os.replace(temp, path)
            hashes[path.name] = {"asset_id": asset_id, "sha256": hashlib.sha256(raw).hexdigest()}
            atomic_json(hashes_path, hashes)
        return raw, str(path) if path else None

    records = []
    for i, asset in enumerate(assets):
        raw, path = await fetch(asset["asset_id"], f"render_{i}")
        companions = []
        for j, original in enumerate(asset.get("sidecars") or []):
            info = dict(original)
            state, saved = None, None
            if info.get("status") != "unavailable":
                try:
                    state, saved = await fetch(info["asset_id"], f"state_{i}_{j}")
                    if info.get("sha256") and hashlib.sha256(state).hexdigest() != info["sha256"]:
                        raise ValueError("integrity_failed")
                    if info.get("byte_size") is not None and len(state) != info["byte_size"]:
                        raise ValueError("integrity_failed")
                except (OSError, ValueError, RuntimeError, KeyError, aiohttp.ClientError) as exc:
                    state, saved = None, None
                    info.update(status="unavailable", unavailable_reason="integrity_failed" if isinstance(exc, ValueError) else "download_failed")
            companions.append(OutputSidecar(info, state, saved))
        records.append(OutputAsset(asset["asset_id"], asset.get("type", "document"), asset.get("role", "primary"), raw, companions, path))
    if records:
        metadata["_output_asset_id"] = records[0].asset_id
    return ExecutionResult(
        success=True, output_data=records[0].data if records else None,
        additional_outputs=[r.data for r in records[1:]], outputs=records,
        generation_time=metadata.get("generation_time") or output.get("generation_time") or 0,
        actual_seed=metadata.get("actual_seed", output.get("actual_seed")), metadata=metadata,
        receipt_path=str(receipt_root) if receipt_root else None,
    )
