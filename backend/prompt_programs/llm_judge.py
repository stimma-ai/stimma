"""The judge: the Tool View model reads each choice of a finished draw and says whether it fits.

A prototype's judge. Every varying choice of a draw is shown in full context (the user's prompt,
the finished prompt with only that choice masked as [Label], what the choice is, and the value
drawn) and answered "no" (it breaks the picture), "rare" (nothing is broken, but it is a stretch)
or "yes". The fix pass (prompt_programs.fix) rerolls a "no", and a "rare" three times in four
(which ones is fixed by the choice and its context, so a draw replays the same).

One call covers a batch of choices, so a draw costs one model call, and one more for each round
that rerolls something. Answers are remembered for the life of the process, keyed by what was
asked, so a choice kept across a reroll in unchanged context isn't asked again.

The fix loop runs in a worker thread and the model call is async, so the judge is made on the
event loop (`ready()`, from fix.await_judge) and its calls are handed back to that loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

RULES = """You check choices made for an image prompt. The user typed a request. A program turned it into a full prompt by drawing values at random for several choices, so that many different images can be made from the one request. Every image must still answer the request, and each must be a believable picture.

You are given the user's request, the finished prompt, and the choices in it: what each choice is, and the value drawn for it.

Give each choice one of three answers:

- "no": the value breaks the picture. It contradicts the user's request or undoes what the request says is happening; or the picture as requested would not show it at all; or it is not the kind of thing the choice asks for; or it cannot be true together with the other values in the prompt.
- "rare": nothing is broken, but it is a stretch: an uncommon combination with the other values, or only loosely what the choice asks for. A detail of a person that reads as another age or another descent than the one the prompt gives them (gray or white hair, deep wrinkles or sagging skin on someone under forty; natural blonde or red hair on someone whose descent rarely has it) is "rare" at best, and "no" when the request states that age or descent. So is clothing made for the other sex than the person's, or for another season or another kind of occasion than the scene.
- "yes": it fits.

Unusual people and places are welcome. When unsure between "rare" and "yes", say "yes". Keep "no" for what is actually wrong.

Reply with one JSON object per line and nothing else, in the form {"id": 1, "answer": "yes"}."""

CUT = 0.5                # above this a choice is rerolled: every "no", and most "rare"
RARE_KEPT = 0.25         # the share of "rare" answers a draw keeps
BATCH = 24               # choices per call: a draw's choices go together
TIMEOUT = 45.0           # seconds for one pass of the fix loop's questions


def _score(key: Tuple[str, str, str, str, str], answer: str) -> float:
    if answer == "no":
        return 1.0
    if answer == "rare":   # kept once in a while, the same every time this choice is asked in this context
        kept = int(hashlib.sha256("\x1f".join(key).encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF < RARE_KEPT
        return 0.25 if kept else 0.75
    return 0.0


_ANSWER = re.compile(r'"id"\s*:\s*(\d+)[^{}]*"answer"\s*:\s*"(yes|rare|no)"')


class LlmJudge:
    """What fix.py asks of a judge: p_wrong(items), cut, version."""

    cut = CUT
    reroll_all = True

    def __init__(self, loop: asyncio.AbstractEventLoop, cfg: Any, key: str = "") -> None:
        self.loop = loop
        self.cfg = cfg
        self.key = key   # the model and endpoint it asks: another one is another judge
        where = hashlib.sha256(key.encode("utf-8")).hexdigest()[:6] if key else ""
        self.version = f"llm:{getattr(cfg, 'model', '') or 'tool-assistant'}" + (f"@{where}" if where else "")
        self._answers: Dict[Tuple[str, str, str, str, str], str] = {}
        self._lock = threading.Lock()
        self.calls = 0

    def p_wrong(self, items: Sequence[Any]) -> List[float]:
        keys = [(it.user_prompt, it.state, it.label, it.about, it.value) for it in items]
        with self._lock:
            todo = list(dict.fromkeys(k for k in keys if k not in self._answers))
        if todo:
            try:
                here: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
            except RuntimeError:
                here = None
            if here is self.loop:   # it would wait on itself: the fix pass runs in a worker thread
                raise RuntimeError("the judge was asked from its own event loop's thread")
            asked = asyncio.run_coroutine_threadsafe(self._ask(todo), self.loop)
            try:
                got = asked.result(TIMEOUT)
            except BaseException:   # too slow, or this thread is ending: the model call is given up, not left running
                asked.cancel()
                raise
            with self._lock:
                self._answers.update(got)
                if len(self._answers) > 50_000:
                    self._answers.clear()
        with self._lock:
            return [_score(k, self._answers.get(k, "yes")) for k in keys]

    async def _ask(self, todo: List[Tuple[str, str, str, str, str]]) -> Dict[Tuple[str, str, str, str, str], str]:
        # One call per finished prompt: its choices are read together, against the prompt whole.
        draws: Dict[Tuple[str, str], List[Tuple[str, str, str, str, str]]] = {}
        for k in todo:
            user_prompt, state, label, _about, value = k
            draws.setdefault((user_prompt, state.replace(f"[{label}]", value, 1)), []).append(k)
        chunks = [(head, ks[i:i + BATCH]) for head, ks in draws.items() for i in range(0, len(ks), BATCH)]
        out: Dict[Tuple[str, str, str, str, str], str] = {}
        got = await asyncio.gather(*(self._call(head, ks) for head, ks in chunks), return_exceptions=True)
        for (_head, ks), answers in zip(chunks, got):
            if isinstance(answers, BaseException):   # a failed call judges nothing: those choices stand
                log.warning(f"[fluent-judge] the judge's call failed: {answers}")
                continue
            for i, k in enumerate(ks):
                if (i + 1) in answers:
                    out[k] = answers[i + 1]
        return out

    async def _call(self, head: Tuple[str, str], chunk: List[Tuple[str, str, str, str, str]]) -> Dict[int, str]:
        from agent.v2.llm_options import agent_llm_options
        from llm import llm_completion
        from llm_correlation import llm_correlation_context
        user_prompt, finished = head
        lines = [f"The user's request: {user_prompt}", "", f"The finished prompt: {finished}", "", "The choices in it:"]
        for i, (_user, _state, label, about, value) in enumerate(chunk):
            what = f"{label} ({about})" if about and about.lower() != label.lower() else label
            lines.append(f"{i + 1}. {what}: {value}")
        messages = [{"role": "system", "content": RULES}, {"role": "user", "content": "\n".join(lines)}]
        self.calls += 1
        with llm_correlation_context("prompt-program-judge"):
            resp = await llm_completion(self.cfg, messages, max_tokens=40 * len(chunk) + 60, temperature=0,
                                        **agent_llm_options(enable_thinking=False))
        return {int(m.group(1)): m.group(2) for m in _ANSWER.finditer(getattr(resp, "content", "") or "")}

    def stats(self) -> Dict[str, Any]:
        return {"version": self.version, "calls": self.calls, "answers": len(self._answers)}


_judges: Dict[Optional[int], LlmJudge] = {}   # by project: a project may set its own Tool View model


async def ready(project_id: Optional[int] = None) -> Optional[LlmJudge]:
    """The judge for the Tool View model as configured now for this project, made on the running
    loop. None when no model can be resolved: the draw then ships unjudged."""
    from llm_resolver import get_effective_llm_config
    try:
        cfg = await get_effective_llm_config("tool_assistant", project_id)
    except Exception as e:
        log.debug(f"[fluent-judge] no Tool View model for the judge: {e}")
        _judges.pop(project_id, None)
        return None
    loop = asyncio.get_running_loop()
    key = json.dumps([getattr(cfg, "model", ""), getattr(cfg, "url", ""), getattr(cfg, "provider_kind", "")], default=str)
    judge = _judges.get(project_id)
    if judge is None or judge.loop is not loop or judge.key != key:
        judge = _judges[project_id] = LlmJudge(loop, cfg, key)
    else:
        judge.cfg = cfg   # fresh credentials, the same judge and its answers
    return judge


def current(project_id: Optional[int] = None) -> Optional[LlmJudge]:
    return _judges.get(project_id)


def reset() -> None:
    _judges.clear()


__all__ = ["CUT", "LlmJudge", "RULES", "current", "ready", "reset"]
