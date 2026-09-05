"""Durable acceptance and shared agent/tool execution; retries never replay work."""

from __future__ import annotations
import asyncio
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import uuid
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from database import Chat, ChatItem
from database_registry import get_database_registry
from core.profile_context import ProfileScope
from .access import access, Caller, McpError
from .models import McpOperation

execution_caller: ContextVar[Caller | None] = ContextVar("mcp_execution", default=None)
execution_chat: ContextVar[int | None] = ContextVar("mcp_execution_chat", default=None)
_tasks: dict[tuple[str, str], asyncio.Task] = {}
_locks: dict[str, asyncio.Lock] = {}
_callers: dict[tuple[str, str], Caller] = {}
_revoked: set[tuple[str, str]] = set()


def check_execution():
    caller = execution_caller.get()
    if caller:
        _, _, stamp = access.stamp(caller.profile_id)
        if stamp != caller.stamp or caller.key in _revoked:
            raise McpError(
                "access_revoked", "External execution authority was revoked."
            )


class AtomicSession(AsyncSession):
    """Domain helpers may flush, but receipt and mutation commit together."""

    async def commit(self):
        await self.flush()

    async def finish(self):
        await super().commit()


def lock_for(profile):
    return _locks.setdefault(profile, asyncio.Lock())


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def envelope(caller, job):
    return {
        "job_ref": access.ref(caller, "job", job.id),
        "state": job.state,
        "controller_version": job.controller_version,
        "chat_ref": access.ref(caller, "chat", job.chat_id) if job.chat_id else None,
        "result": json.loads(job.result_json) if job.result_json else None,
    }


async def receipt(session, operation, key, args, caller):
    existing = (
        await session.execute(
            select(McpOperation).where(
                McpOperation.operation == operation,
                McpOperation.request_key == f"{caller.client_id}:{key}",
            )
        )
    ).scalar_one_or_none()
    if existing and existing.input_hash != fingerprint(args):
        raise McpError(
            "request_key_conflict",
            "Use a new request_key for intentionally changed input.",
        )
    return existing


async def mutate(caller, name, key, args, fn):
    db = get_database_registry().get_database(caller.profile_id)
    async with lock_for(caller.profile_id):
        async with AtomicSession(db.async_engine, expire_on_commit=False) as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            old = await receipt(session, name, key, args, caller)
            if old:
                return json.loads(old.result_json)
            from utils.websocket import defer_broadcasts

            async with defer_broadcasts():
                value = await fn(session)
                row = McpOperation(
                    id=uuid.uuid4().hex,
                    client_id=caller.client_id,
                    operation=name,
                    request_key=f"{caller.client_id}:{key}",
                    input_hash=fingerprint(args),
                    input_json=json.dumps(args),
                    state="succeeded",
                    result_json=json.dumps(value),
                )
                session.add(row)
                await session.finish()
            return value


async def accept(caller, name, key, args):
    db = get_database_registry().get_database(caller.profile_id)
    async with lock_for(caller.profile_id):
        async with db.async_session_maker() as session:
            old = await receipt(session, name, key, args, caller)
            if old:
                return envelope(caller, old)
            payload = dict(args)
            from .workspace import (
                media_row,
                tool_descriptor,
                tool_version,
                tool_parameters,
            )

            if name == "content_update" and args.get("source_ref"):
                source = await media_row(caller, args["source_ref"], session)
                payload["source_ref"] = access.ref(caller, "media", source.id)
            if name == "tools_run":
                if args.get("batch") and args.get("chain"):
                    raise McpError("invalid_arguments", "Choose a batch or a chain.")
                payload = json.loads(json.dumps(args))
                steps = [
                    {
                        "tool_ref": args["tool_ref"],
                        "schema_version": args["schema_version"],
                        "parameters": p,
                    }
                    for p in (payload.get("batch") or [payload["parameters"]])
                ] + payload.get("chain", [])
                for step in steps:
                    _, _, descriptor = await tool_descriptor(caller, step["tool_ref"])
                    if tool_version(descriptor) != step["schema_version"]:
                        raise McpError(
                            "schema_changed",
                            "Inspect the changed tool before starting new work.",
                        )
                    for field, schema in descriptor.parameter_schema.get(
                        "properties", {}
                    ).items():
                        if "x-accept-media" in schema and field in step["parameters"]:
                            value = step["parameters"][field]
                            many = isinstance(value, list)
                            pinned = [
                                access.ref(
                                    caller,
                                    "media",
                                    (await media_row(caller, ref, session)).id,
                                )
                                for ref in (value if many else [value])
                            ]
                            step["parameters"][field] = pinned if many else pinned[0]
                    if not step.get("input_from_previous"):
                        await tool_parameters(
                            caller, descriptor, step["parameters"], session
                        )
            if (
                name == "content_update"
                and args.get("target_asset_ref")
                and not args.get("expected_current_revision")
            ):
                raise McpError(
                    "invalid_arguments",
                    "Revising an Asset requires expected_current_revision.",
                )
            if args.get("references") or args.get("media_refs"):
                refs = [
                    *args.get("references", []),
                    *[{"ref": ref} for ref in args.get("media_refs", [])],
                ]
                pinned = []
                notes = []
                for reference in refs:
                    row = await media_row(caller, reference["ref"], session)
                    pinned.append(access.ref(caller, "media", row.id))
                    notes.append(
                        f"Media {row.id}: {reference.get('role', 'reference')} {reference.get('note', '')}"
                    )
                payload["media_refs"] = pinned
                payload["_reference_notes"] = "\n".join(notes)
            for skill in args.get("skills", []):
                from agent.v2.stimpacks import find_skill

                if not find_skill(skill):
                    raise McpError(
                        "not_found", "A requested skill is unavailable in this profile."
                    )
            # Ordinary chats inherit real project/profile model and tool policy.
            from database import Project

            project_id = (
                int(access.resolve(caller, args["project_ref"], "project"))
                if args.get("project_ref")
                else None
            )
            if project_id and not await session.get(Project, project_id):
                raise McpError("not_found", "Project is unavailable.")
            chat = Chat(
                name=args.get("brief", name)[:80],
                project_id=project_id,
                throttle="off",
                generation_settings=json.dumps({"mcp_origin": caller.client_id}),
            )
            if args.get("source_chat"):
                source_id = int(
                    access.resolve(caller, args["source_chat"]["chat_ref"], "chat")
                )
                checkpoint = int(
                    access.resolve(
                        caller, args["source_chat"]["checkpoint_ref"], "chat_item"
                    )
                )
                source = await session.get(Chat, source_id)
                item = await session.get(ChatItem, checkpoint)
                if (
                    not source
                    or source.deleted_at
                    or not item
                    or item.chat_id != source.id
                ):
                    raise McpError(
                        "not_found", "The source chat checkpoint is unavailable."
                    )
                chat.original_chatitem_id = checkpoint
                chat.additional_instructions = source.additional_instructions
                chat.model_slug = source.model_slug
                chat.agent_tool_config = source.agent_tool_config
                chat.project_id = project_id or source.project_id
            session.add(chat)
            await session.flush()
            job = McpOperation(
                id=uuid.uuid4().hex,
                client_id=caller.client_id,
                operation=name,
                request_key=f"{caller.client_id}:{key}",
                input_hash=fingerprint(args),
                input_json=json.dumps(payload),
                state="queued",
                chat_id=chat.id,
            )
            session.add(job)
            if name == "agent_start":
                brief = args["brief"]
                if payload.get("_reference_notes"):
                    brief += "\n" + payload["_reference_notes"]
                if args.get("skills"):
                    brief += "\nUse these skills: " + ", ".join(args["skills"])
                if args.get("deliverables"):
                    brief += "\nDeliverables: " + json.dumps(args["deliverables"])
                if args.get("interaction") == "unattended":
                    brief += "\nWork unattended where possible. Park on essential questions and permissions."
                session.add(
                    ChatItem(
                        chat_id=chat.id, item_type="user_message", message_text=brief
                    )
                )
            await session.commit()
            result = envelope(caller, job)
        _revoked.discard(caller.key)
        spawn(caller, job.id)
        return result


def spawn(caller, job_id, response=None, message=None):
    _callers[caller.profile_id, job_id] = caller
    _tasks[caller.profile_id, job_id] = asyncio.create_task(
        run(caller, job_id, response=response, message=message)
    )


async def pending_interaction(session, chat_id):
    requests = (
        await session.scalars(
            select(ChatItem)
            .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "hitl_request")
            .order_by(ChatItem.id.desc())
            .limit(100)
        )
    ).all()
    if not requests:
        return None
    responses = (
        await session.scalars(
            select(ChatItem).where(
                ChatItem.chat_id == chat_id,
                ChatItem.item_type == "hitl_response",
                ChatItem.id > requests[-1].id,
            )
        )
    ).all()
    exact = {
        json.loads(row.item_metadata or "{}").get("_mcp_interaction_id")
        for row in responses
    }
    generic_after = max(
        (
            row.id
            for row in responses
            if "_mcp_interaction_id" not in json.loads(row.item_metadata or "{}")
        ),
        default=0,
    )
    return next(
        (row for row in requests if row.id not in exact and row.id > generic_after),
        None,
    )


async def run(caller, job_id, *, response=None, message=None):
    token = execution_caller.set(caller)
    db = get_database_registry().get_database(caller.profile_id)
    with ProfileScope(caller.profile_id):
        try:
            check_execution()
            async with db.async_session_maker() as session:
                job = await session.get(McpOperation, job_id)
                job.state = "running"
                await session.commit()
                chat = await session.get(Chat, job.chat_id)
                execution_chat.set(chat.id)
                start_item_id = await session.scalar(
                    select(func.coalesce(func.max(ChatItem.id), 0)).where(
                        ChatItem.chat_id == chat.id
                    )
                )
                from .workspace import refresh_custom_tools

                await refresh_custom_tools()
                args = json.loads(job.input_json)
                from utils.websocket import ws_manager

                await ws_manager.broadcast("chat_created", {"chat": chat.to_dict()})
                if response is not None:
                    from routes.chats import submit_human_response, HITLResponseRequest

                    await submit_human_response(
                        chat.id, HITLResponseRequest(**response), session
                    )
                elif job.operation == "agent_start":
                    from agent import run_agent

                    refs = [
                        int(access.resolve(caller, ref, "media"))
                        for ref in args.get("media_refs", [])
                    ]
                    brief = message or args["brief"]
                    if not message:
                        if args.get("_reference_notes"):
                            brief += "\n" + args["_reference_notes"]
                        if args.get("skills"):
                            brief += "\nUse these skills: " + ", ".join(args["skills"])
                        if args.get("deliverables"):
                            brief += "\nDeliverables: " + json.dumps(
                                args["deliverables"]
                            )
                        if args.get("interaction") == "unattended":
                            brief += "\nWork unattended where possible. Park on essential questions and permissions."
                    await run_agent(
                        chat=chat,
                        user_message=brief,
                        session=session,
                        ws_manager=ws_manager,
                        selected_media_ids=refs,
                    )
                elif job.operation == "tools_run":
                    from .workspace import execute_tools

                    job.result_json = json.dumps(
                        await execute_tools(caller, args, session, chat, job)
                    )
                elif job.operation == "content_update":
                    from .content import update

                    job.result_json = json.dumps(
                        await update(caller, args, session, chat)
                    )
                elif job.operation.startswith("bound:"):
                    from .operations import FAMILIES

                    _, family, action = job.operation.split(":", 2)
                    binding = FAMILIES[family][1][action]
                    value = await binding.run(caller, args, session)
                    job.result_json = json.dumps(value)
                elif job.operation == "flows_run":
                    from .workspace import execute_flow

                    job.result_json = json.dumps(
                        await execute_flow(caller, args, session, chat)
                    )
                check_execution()
                await session.refresh(job, ["state"])
                if job.state not in ("cancelled", "control_changed"):
                    pending = await pending_interaction(session, chat.id)
                    failed = await session.scalar(
                        select(ChatItem.id)
                        .where(
                            ChatItem.chat_id == chat.id,
                            ChatItem.id > start_item_id,
                            ChatItem.item_type == "error",
                        )
                        .limit(1)
                    )
                    partial_failure = (
                        job.result_json
                        and any(
                            i.get("state") in ("failed", "interrupted")
                            for i in json.loads(job.result_json).get("items", [])
                            if isinstance(i, dict)
                        )
                        if job.operation == "tools_run"
                        else False
                    )
                    job.state = (
                        "failed"
                        if failed or partial_failure
                        else "input_required"
                        if pending
                        else "succeeded"
                    )
                    job.updated_at = datetime.utcnow()
                    await session.commit()
        except asyncio.CancelledError:
            await set_state(caller, job_id, "cancelled")
        except Exception as exc:
            code = exc.code if isinstance(exc, McpError) else "execution_failed"
            # No raw provider exceptions, prompts, paths or credentials in MCP errors.
            await set_state(
                caller,
                job_id,
                "failed",
                {
                    "code": code,
                    "message": "Execution stopped. Inspect the chat for details.",
                },
            )
        finally:
            execution_caller.reset(token)
            _tasks.pop((caller.profile_id, job_id), None)
            if "job" in locals() and job.state != "input_required":
                _callers.pop((caller.profile_id, job_id), None)


async def set_state(caller, job_id, state, result=None):
    db = get_database_registry().get_database(caller.profile_id)
    async with db.async_session_maker() as session:
        job = await session.get(McpOperation, job_id)
        if job and job.state != "control_changed":
            job.state, job.updated_at = state, datetime.utcnow()
            if result:
                job.result_json = json.dumps(result)
            await session.commit()


async def get(caller, job_ref, after=0):
    job_id = access.resolve(caller, job_ref, "job")
    db = get_database_registry().get_database(caller.profile_id)
    async with db.async_session_maker() as session:
        job = await session.get(McpOperation, job_id)
        if not job or job.deleted_at:
            raise McpError("not_found", "Job is unavailable.")
        if (
            job.state in ("queued", "running", "input_required")
            and (caller.profile_id, job_id) not in _callers
        ):
            job.state = "interrupted"
            job.result_json = json.dumps(
                {
                    "code": "execution_outcome_unknown",
                    "message": "The backend restarted. Inspect retained outputs; work was not replayed.",
                }
            )
            await session.commit()
        output = envelope(caller, job)
        if job.chat_id:
            from .operations import present

            items = list(
                (
                    await session.scalars(
                        select(ChatItem)
                        .where(
                            ChatItem.chat_id == job.chat_id,
                            ChatItem.id > after,
                            ChatItem.item_type.in_(
                                [
                                    "user_message",
                                    "assistant_message",
                                    "media_display",
                                    "hitl_request",
                                    "hitl_response",
                                    "error",
                                ]
                            ),
                        )
                        .order_by(ChatItem.id)
                        .limit(100)
                    )
                ).all()
            )
            output["events"] = [
                present(
                    caller,
                    {
                        "id": i.id,
                        "type": i.item_type,
                        "text": i.message_text,
                        "show_role": i.show_role,
                        "asset_ids": json.loads(i.asset_ids or "[]"),
                        "media_ids": json.loads(i.media_ids or "[]"),
                        "metadata": json.loads(i.item_metadata)
                        if i.item_metadata
                        else None,
                    },
                    "chat_item",
                )
                for i in items
            ]
            output["next_cursor"] = items[-1].id if items else after
            pending = await pending_interaction(session, job.chat_id)
            if pending and job.state not in (
                "cancelled",
                "failed",
                "interrupted",
                "control_changed",
            ):
                output["state"] = "input_required"
                output["interaction"] = {
                    "ref": access.ref(caller, "interaction", pending.id),
                    "version": 1,
                    "request": present(
                        caller, json.loads(pending.item_metadata or "{}")
                    ),
                }
        return output


async def control(
    caller, job_ref, version, key, message=None, interaction_ref=None, response=None
):
    job_id = access.resolve(caller, job_ref, "job")
    args = {
        "job_ref": job_ref,
        "version": version,
        "message": message,
        "interaction_ref": interaction_ref,
        "response": response,
    }
    db = get_database_registry().get_database(caller.profile_id)
    async with lock_for(caller.profile_id):
        async with db.async_session_maker() as session:
            old = await receipt(session, "job_control", key, args, caller)
            if old:
                return json.loads(old.result_json)
            job = await session.get(McpOperation, job_id)
            if not job or job.deleted_at:
                raise McpError("not_found", "Job is unavailable.")
            if job.controller_version != version or job.state in (
                "control_changed",
                "cancelled",
                "interrupted",
            ):
                raise McpError(
                    "control_changed",
                    "Control has changed. Retrieve the job before continuing.",
                )
            pending = await pending_interaction(session, job.chat_id)
            if interaction_ref:
                interaction_id = int(
                    access.resolve(caller, interaction_ref, "interaction")
                )
                if not pending or pending.id != interaction_id:
                    raise McpError(
                        "control_changed",
                        "This question has already been answered or replaced.",
                    )
            elif pending:
                raise McpError(
                    "input_required", "Answer the outstanding interaction first."
                )
            active = _tasks.get((caller.profile_id, job_id))
            inprocess = (
                json.loads(pending.item_metadata or "{}")
                .get("v2_tool_args", {})
                .get("_inprocess_request_id")
                if pending
                else None
            )
            if inprocess:
                from agent.v2.tool_permission_gate import _PENDING

                future = _PENDING.get(inprocess)
                if future is None or future.done():
                    raise McpError(
                        "control_changed",
                        "This question is no longer waiting for an answer.",
                    )
            if active and not active.done() and not inprocess:
                raise McpError(
                    "job_running", "Wait for the current turn before continuing."
                )
            if message and job.operation != "agent_start":
                raise McpError(
                    "not_delegated",
                    "Only delegated agent jobs accept conversation follow-ups.",
                )
            if message:
                session.add(
                    ChatItem(
                        chat_id=job.chat_id,
                        item_type="user_message",
                        message_text=message,
                    )
                )
            job.controller_version += 1
            job.client_id = caller.client_id
            job.state = "running" if inprocess else "queued"
            result = envelope(caller, job)
            session.add(
                McpOperation(
                    id=uuid.uuid4().hex,
                    client_id=caller.client_id,
                    operation="job_control",
                    request_key=f"{caller.client_id}:{key}",
                    input_hash=fingerprint(args),
                    input_json=json.dumps(args),
                    state="succeeded",
                    result_json=json.dumps(result),
                )
            )
            await session.commit()
            if inprocess:
                from agent.v2.tool_permission_gate import resolve_pending_permission

                if not resolve_pending_permission(inprocess, response):
                    raise McpError(
                        "execution_outcome_unknown",
                        "The waiting execution is no longer available.",
                    )
                session.add(
                    ChatItem(
                        chat_id=job.chat_id,
                        item_type="hitl_response",
                        item_metadata=json.dumps(
                            {**response, "_mcp_interaction_id": pending.id}
                        ),
                    )
                )
                await session.commit()
            else:
                _revoked.discard(caller.key)
                spawn(caller, job.id, response=response, message=message)
            return result


async def cancel(caller, job_ref):
    job_id = access.resolve(caller, job_ref, "job")
    db = get_database_registry().get_database(caller.profile_id)
    async with db.async_session_maker() as session:
        job = await session.get(McpOperation, job_id)
        if not job:
            raise McpError("not_found", "Job is unavailable.")
        if job.state == "control_changed":
            raise McpError("control_changed", "The desktop controls this chat now.")
        if job.state in ("succeeded", "failed", "cancelled", "interrupted"):
            return envelope(caller, job)
        task = _tasks.get((caller.profile_id, job_id))
        if task:
            task.cancel()
        job.state = "cancelled"
        job.controller_version += 1
        await session.commit()
        return envelope(caller, job)


async def revoke(profile_id, client_id=None):
    access.lock(profile_id, client_id)
    db = get_database_registry().get_database(profile_id)
    async with db.async_session_maker() as session:
        query = select(McpOperation).where(
            McpOperation.state.in_(["queued", "running", "input_required"])
        )
        if client_id:
            query = query.where(McpOperation.client_id == client_id)
        for job in (await session.scalars(query)).all():
            _revoked.add((profile_id, job.client_id))
            task = _tasks.get((profile_id, job.id))
            if task:
                task.cancel()
            job.state = "cancelled"
            job.controller_version += 1
        await session.commit()


async def takeover(profile_id, chat_id):
    """Desktop user input owns the chat from this point; stale MCP replies fail."""
    db = get_database_registry().get_database(profile_id)
    async with lock_for(profile_id):
        async with db.async_session_maker() as session:
            rows = await session.scalars(
                select(McpOperation).where(
                    McpOperation.chat_id == chat_id,
                    McpOperation.operation.in_(
                        ["agent_start", "tools_run", "flows_run"]
                    ),
                )
            )
            for job in rows:
                job.controller_version += 1
                job.state = "control_changed"
                task = _tasks.get((profile_id, job.id))
                if task:
                    task.cancel()
            await session.commit()


async def watch_revocations():
    """PIN/config changes revoke parked work as well as future dispatches."""
    while True:
        await asyncio.sleep(1)
        for key, caller in list(_callers.items()):
            try:
                _, _, stamp = access.stamp(caller.profile_id)
                if stamp == caller.stamp:
                    continue
            except (McpError, KeyError, ValueError):
                pass
            try:
                await revoke(caller.profile_id, caller.client_id)
            except (McpError, KeyError, ValueError):
                task = _tasks.get(key)
                if task:
                    task.cancel()
            _callers.pop(key, None)


async def retry(caller, job_ref, key):
    db = get_database_registry().get_database(caller.profile_id)
    async with db.async_session_maker() as session:
        old = await session.get(McpOperation, access.resolve(caller, job_ref, "job"))
        if not old or old.operation != "tools_run" or old.state != "failed":
            raise McpError(
                "retry_unavailable",
                "Only known failed tool items can be retried. Unknown outcomes need review.",
            )
        args = json.loads(old.input_json)
        if args.get("chain"):
            raise McpError(
                "retry_unavailable",
                "Inspect the retained chain outputs and start the failed step explicitly.",
            )
        items = json.loads(old.result_json or "{}").get("items", [])
        failed = [i["index"] for i in items if i.get("state") == "failed"]
        if not failed:
            raise McpError(
                "retry_unavailable",
                "There are no confirmed failed dispatches to retry.",
            )
        batches = args.get("batch") or [args["parameters"]]
        args["batch"] = [batches[i] for i in failed]
        args["_retry_of"] = job_ref
    return await accept(caller, "tools_run", key, args)
