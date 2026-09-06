"""Packaged stdio bridge. No PIN persistence; only this client's transport credential."""

from __future__ import annotations
import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlparse
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult, ToolAnnotations


def config_dir():
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "stimma"
        / "mcp"
    )


def config_path(alias):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", alias):
        raise ValueError("Invalid connection alias")
    return config_dir() / (alias + ".json")


def validate(config):
    url = urlparse(config["endpoint"])
    if (
        url.scheme not in ("http", "https")
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Expected an HTTP endpoint without embedded credentials or query parameters"
        )
    if not url.path.startswith("/mcp/profiles/"):
        raise ValueError("Expected a profile-bound MCP endpoint")
    if not isinstance(config.get("credential"), str) or len(config["credential"]) < 32:
        raise ValueError("Missing connection credential")
    return config


def install(path):
    config = validate(json.loads(Path(path).read_text()))
    target = config_path(config["alias"])
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(config, stream)
    os.chmod(target, 0o600)
    print(
        json.dumps(
            {
                "mcpServers": {
                    config["alias"]: {
                        "command": "stimma",
                        "args": ["mcp", "bridge", config["alias"]],
                    }
                }
            },
            indent=2,
        )
    )


async def serve(config):
    from .logging import protect_sdk_logs

    protect_sdk_logs()
    bridge = Server(
        "Stimma bridge",
        instructions="Stimma creative workspace. Use direct operations for known tasks and agent_start for creative judgment. PIN unlock is shared by this configured client. Never guess a PIN or restart an accepted job to check progress.",
    )
    endpoint = config["endpoint"].rstrip("/")
    headers = {"Authorization": "Bearer " + config["credential"]}

    @asynccontextmanager
    async def remote():
        async with httpx.AsyncClient(
            headers=headers, timeout=60, follow_redirects=False
        ) as http:
            async with streamable_http_client(endpoint, http_client=http) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

    @bridge.list_tools()
    async def list_tools():
        async with remote() as session:
            result = await session.list_tools()
        result.tools.extend(
            [
                Tool(
                    name="media_upload",
                    description="Upload a file selected on this assistant’s machine into the bound Stimma profile. Requires an unlocked connection.",
                    inputSchema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    annotations=ToolAnnotations(
                        readOnlyHint=False, idempotentHint=True
                    ),
                ),
                Tool(
                    name="media_download",
                    description="Download an original or complete bundle to this assistant’s machine and return its local path. Does not publish the media.",
                    inputSchema={
                        "type": "object",
                        "properties": {"ref": {"type": "string"}},
                        "required": ["ref"],
                        "additionalProperties": False,
                    },
                    annotations=ToolAnnotations(readOnlyHint=True),
                ),
            ]
        )
        return result.tools

    @bridge.call_tool()
    async def call_tool(name, arguments):
        try:
            if name == "media_upload":
                path = Path(arguments["path"]).expanduser()
                if not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
                    raise ValueError("Choose an existing file smaller than 512 MiB.")

                async def chunks():
                    with path.open("rb") as stream:
                        while data := stream.read(1024 * 1024):
                            yield data

                async with httpx.AsyncClient(
                    headers=headers, timeout=120, follow_redirects=False
                ) as http:
                    response = await http.post(
                        endpoint + "/upload",
                        content=chunks(),
                        headers={
                            "X-Filename": quote(path.name),
                            "Content-Type": "application/octet-stream",
                        },
                    )
                    response.raise_for_status()
                    value = response.json()
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(value))],
                    structuredContent=value,
                )
            if name == "media_download":
                async with remote() as session:
                    result = await session.call_tool(
                        "media_export", {"ref": arguments["ref"]}
                    )
                if result.isError:
                    return result
                value = result.structuredContent or json.loads(result.content[0].text)
                folder = Path(
                    config.get(
                        "download_directory", Path.home() / "Downloads" / "Stimma"
                    )
                )
                folder.mkdir(parents=True, exist_ok=True)
                import uuid

                target = folder / (
                    uuid.uuid4().hex[:8] + "-" + Path(value["filename"]).name
                )
                partial = target.with_name(target.name + ".part")
                digest = hashlib.sha256()
                try:
                    async with httpx.AsyncClient(
                        headers=headers, timeout=120, follow_redirects=False
                    ) as http:
                        async with http.stream(
                            "GET",
                            endpoint
                            + "/download/"
                            + quote(value["transfer_handle"], safe=""),
                        ) as response:
                            response.raise_for_status()
                            with partial.open("xb") as stream:
                                async for data in response.aiter_bytes():
                                    digest.update(data)
                                    stream.write(data)
                            expected = response.headers.get("x-content-sha256")
                    if expected and expected != digest.hexdigest():
                        raise ValueError(
                            "Checksum mismatch; request the download again."
                        )
                    partial.replace(target)
                finally:
                    partial.unlink(missing_ok=True)
                value = {
                    "path": str(target),
                    "sha256": digest.hexdigest(),
                    "media_ref": value["media_ref"],
                }
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(value))],
                    structuredContent=value,
                )
            async with remote() as session:
                return await session.call_tool(name, arguments)
        except Exception:
            # HTTP errors can include request URLs; never expose credentials or PINs.
            return CallToolResult(
                isError=True,
                content=[
                    TextContent(
                        type="text",
                        text="Stimma could not complete the request. Check the backend connection and unlock status. Retry accepted work with the same request_key.",
                    )
                ],
            )

    async with stdio_server() as (read, write):
        await bridge.run(read, write, bridge.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="Stimma MCP bridge")
    parser.add_argument("action", choices=["install", "bridge"])
    parser.add_argument("target")
    args = parser.parse_args()
    if args.action == "install":
        install(args.target)
    else:
        config = validate(json.loads(config_path(args.target).read_text()))
        asyncio.run(serve(config))


if __name__ == "__main__":
    main()
