"""Asset browser grouping: Auto work threads and Themes.

Each Asset gets one home per kind, once, when it is ready, in arrival order
(``Asset.created_at``, ``Asset.id``). Nothing here splits on time: time only
orders things, and the activity windows below say when a group may still take
soft joins.

Auto places a new Asset by the first rule that matches:

1. Lineage: it joins its source's group while that group was touched in the
   last 8 days. A source in a quieter group becomes a "Made from" ref of the
   group the new Asset lands in instead (a revisit).
2. Same typed prompt (exact equality; never word overlap).
3. Same chat.
4. Same import folder and month (watched files with no tool and no chat), or the
   same upload batch (managed uploads arriving within 10 minutes of the last one).
5. Drift: same tool, under 40 minutes after that tool's previous frame, and
   the mean CLIP similarity to the last 4 frames of that frame's group is at
   least the drift threshold. Otherwise it's a hop, and rule 6 may not pull
   it straight back into that group.
6. Looks alike: the mean of the top 3 similarities against the last 48
   frames of a group active in the last 21 days, at least the looks-alike
   threshold.
7. A new group.

Theme is a union-find over lineage edges plus the same typed prompt. When a
new Asset links two themes, the smaller one's members move to the larger one.

The engine keeps its state in memory per profile. A warm-up rebuilds that
state from the inputs frozen on member rows, never from current Media, so a
restart decides exactly as an unbroken run would.

Ported from the prototype at stimma-plans ``mocks/asset-browser/policy/group.py``.
"""

from __future__ import annotations

import collections
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
from sqlalchemy import String, and_, exists, func, select, text, type_coerce, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import (
    Asset,
    AssetGroup,
    AssetGroupMember,
    AssetGroupRef,
    AssetRevision,
    Chat,
    ChatItem,
    MediaItem,
    MediaLineage,
    Project,
    ProjectAsset,
)

log = get_logger(__name__)

AUTO = "auto"
THEME = "theme"
KINDS = (AUTO, THEME)

# Policy knobs (Brian, 9 Nov).
ACTIVE_DAYS = 21          # a group takes looks-alike joins until idle this long
REVISIT_DAYS = 8          # lineage from a group idle longer than this starts a revisit
CONT_MINUTES = 40         # "continuing a run": same tool, previous frame this recent
TOPK = 3                  # looks-alike = mean of the k best matches
RECENT = 48               # frames per group kept for looks-alike
TAIL = 4                  # frames drift is judged against
CANDIDATES = 400          # most recently touched groups considered for looks-alike

# Calibration falls back to these below MIN_SAMPLES samples.
DEFAULT_LOOKS_ALIKE = 0.89
DEFAULT_DRIFT = 0.79
MIN_SAMPLES = 200

CLIP_DIM = 512
CLIP_WAIT = timedelta(minutes=10)
BATCH_SIZE = 500
TITLE_CHARS = 64

_ACTIVE = timedelta(days=ACTIVE_DAYS)
_REVISIT = timedelta(days=REVISIT_DAYS)
_CONT = timedelta(minutes=CONT_MINUTES)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_CLAUSE = re.compile(r"[,;:\n]|\.\s")
UPLOAD_KEY = "@upload"
UPLOAD_BATCH = timedelta(minutes=10)

_TITLE_RANK = {"none": 0, "folder": 1, "prompt": 2, "chat": 3}


# ---------------------------------------------------------------------------
# Inputs


@dataclass
class Item:
    """One Asset's grouping inputs, as frozen at assignment."""

    asset_id: int
    arrived_at: datetime
    media_id: Optional[int] = None
    typed_prompt: Optional[str] = None
    tool_id: Optional[str] = None
    chat_id: Optional[int] = None
    import_key: Optional[str] = None
    vector: Optional[np.ndarray] = None       # float32 decoded from the float16 bytes
    vector_bytes: Optional[bytes] = None
    # Not frozen: only read when the Asset is placed.
    sources: list = field(default_factory=list)   # [(source asset id, reason)]
    display_at: Optional[datetime] = None
    chat_name: Optional[str] = None
    folder_title: Optional[str] = None
    project_id: Optional[int] = None


def decode_vector(raw: Optional[bytes]) -> Optional[np.ndarray]:
    if not raw:
        return None
    return np.frombuffer(raw, dtype=np.float16).astype(np.float32)


def encode_embedding(raw: Optional[bytes]) -> tuple[Optional[bytes], Optional[np.ndarray]]:
    """A CLIP embedding as normalized float16 bytes, and the float32 the engine uses.

    The engine always works from the float16 round trip, so the vector it uses
    while placing an Asset is bit-identical to the one a warm-up decodes.
    """
    if not raw or len(raw) != CLIP_DIM * 4:
        return None, None
    v = np.frombuffer(raw, dtype=np.float32)
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n == 0:
        return None, None
    stored = (v / n).astype(np.float16)
    if not np.all(np.isfinite(stored)):
        return None, None
    return stored.tobytes(), stored.astype(np.float32)


def typed_prompt_of(generation_metadata: Optional[str], extracted_prompt: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """The prompt the person typed, and an inspired-by source Media id.

    Auto-improve rewrites nearly every final prompt, so the typed one
    (``prompt_metadata.original_prompt``) is what identifies a run.
    """
    gm = {}
    if generation_metadata:
        try:
            gm = json.loads(generation_metadata)
        except (TypeError, ValueError):
            gm = {}
    if not isinstance(gm, dict):
        gm = {}
    pm = gm.get("prompt_metadata")
    pm = pm if isinstance(pm, dict) else {}
    prompt = pm.get("original_prompt") or gm.get("prompt") or extracted_prompt or ""
    if not isinstance(prompt, str):
        prompt = json.dumps(prompt, sort_keys=True)  # JSON-mode prompts
    prompt = prompt.strip() or None
    params = gm.get("parameters")
    params = params if isinstance(params, dict) else {}
    inspired = gm.get("inspired_by")
    inspired = inspired if isinstance(inspired, dict) else {}
    source = params.get("inspired_by_media_id") or inspired.get("media_id")
    try:
        source = int(source) if source is not None else None
    except (TypeError, ValueError):
        source = None
    return prompt, source


def prompt_title(prompt: str) -> str:
    """Display only: the prompt's first clause, cut at 64 characters."""
    s = prompt.strip()
    clause = _CLAUSE.split(s, 1)[0].strip() or s
    if len(clause) > TITLE_CHARS:
        clause = clause[:TITLE_CHARS].rstrip() + "…"
    return clause


def _title_of(item: Item) -> tuple[str, str]:
    if item.chat_name:
        return "chat", item.chat_name
    if item.typed_prompt:
        return "prompt", prompt_title(item.typed_prompt)
    if item.folder_title:
        return "folder", item.folder_title
    return "none", "Untitled"


def is_ready(*, state: str, asset_deleted: bool, created_at: datetime, metadata_status: Optional[str],
             clip_status: Optional[str], file_unavailable: bool, media_gone: bool,
             clip_enabled: bool, now: datetime) -> bool:
    """Whether an Asset can be placed now.

    Trashed and deleting Assets are placed like any other, so a restore keeps
    its group, but never hold up the pass.
    """
    if state in ("trashed", "deleting") or asset_deleted or media_gone or file_unavailable:
        return True
    if metadata_status not in ("completed", "failed"):
        return False
    if clip_status in ("completed", "failed", "skipped") or not clip_enabled:
        return True
    return now - created_at > CLIP_WAIT


# ---------------------------------------------------------------------------
# In-memory state


class _Group:
    __slots__ = ("id", "kind", "title", "title_source", "project_id", "first_at", "last_at",
                 "created_at", "deleted_at", "last_arrive", "recent", "n_recent", "pos", "tail",
                 "size", "new", "dirty")

    def __init__(self, gid, kind, *, title="Untitled", title_source="none", project_id=None,
                 first_at=None, last_at=None, created_at=None, deleted_at=None, new=False):
        self.id, self.kind = gid, kind
        self.title, self.title_source, self.project_id = title, title_source, project_id
        self.first_at, self.last_at = first_at, last_at
        self.created_at, self.deleted_at = created_at, deleted_at
        self.last_arrive = None
        self.recent = None
        self.n_recent = 0
        self.pos = 0
        self.tail = collections.deque(maxlen=TAIL)
        self.size = 0
        self.new, self.dirty = new, False

    def add_vector(self, v):
        if self.recent is None:
            self.recent = np.empty((RECENT, v.shape[0]), dtype=np.float32)
        self.recent[self.pos] = v
        self.pos = (self.pos + 1) % RECENT
        self.n_recent = min(self.n_recent + 1, RECENT)
        self.tail.append(v)

    def touch(self, arrived_at):
        if self.last_arrive is None or arrived_at > self.last_arrive:
            self.last_arrive = arrived_at

    def tail_sim(self, v) -> float:
        if not self.tail:
            return -1.0
        return float((np.array(self.tail) @ v).mean())

    def sim(self, v) -> float:
        if not self.n_recent:
            return -1.0
        s = self.recent[: self.n_recent] @ v
        k = min(TOPK, len(s))
        return float(np.sort(s)[-k:].mean())

    def place(self, item: Item, at: Optional[datetime]):
        """Record a new member's display facts and mark the row for writing."""
        if at is not None:
            if self.first_at is None or at < self.first_at:
                self.first_at = at
            if self.last_at is None or at > self.last_at:
                self.last_at = at
        source, title = _title_of(item)
        if self.title_source == "none" and source != "none":
            self.title_source, self.title = source, title
        if self.project_id is None and item.project_id is not None:
            self.project_id = item.project_id
        self.dirty = True


def calibrate(items) -> dict:
    """Thresholds from the library itself (the prototype's ``calibrate``).

    ``items`` are frozen Auto inputs in placement order. Looks-alike must beat
    almost every random pair: max(p99 of random pairs, p10 of same-prompt
    pairs). Drift is the p5 of same-prompt steps: a frame against the 4 its
    tool just made with the same typed prompt, minutes apart.
    """
    rng = np.random.default_rng(0)
    by_prompt = collections.defaultdict(list)
    allv = []
    for it in items:
        if it.vector is None:
            continue
        allv.append(it.vector)
        if it.typed_prompt and it.tool_id:
            by_prompt[it.typed_prompt].append(it.vector)
    same = []
    for vs in by_prompt.values():
        if len(vs) >= 2:
            for _ in range(min(6, len(vs))):
                a, b = rng.choice(len(vs), 2, replace=False)
                same.append(float(vs[a] @ vs[b]))
    rand_p99 = None
    if len(allv) >= 2:
        arr = np.array(allv)
        idx = rng.choice(len(arr), (4000, 2))
        rand = np.einsum("ij,ij->i", arr[idx[:, 0]], arr[idx[:, 1]])
        rand_p99 = float(np.percentile(rand, 99))
    steps, last, tails = [], {}, collections.defaultdict(lambda: collections.deque(maxlen=TAIL))
    for it in items:
        if not it.tool_id or it.vector is None:
            continue
        p = last.get(it.tool_id)
        if p and p.typed_prompt == it.typed_prompt and it.arrived_at - p.arrived_at < _CONT:
            steps.append(float((np.array(tails[it.tool_id]) @ it.vector).mean()))
        elif not p or p.typed_prompt != it.typed_prompt:
            tails[it.tool_id].clear()
        tails[it.tool_id].append(it.vector)
        last[it.tool_id] = it
    looks_alike = DEFAULT_LOOKS_ALIKE
    if len(same) >= MIN_SAMPLES and rand_p99 is not None:
        looks_alike = max(rand_p99, float(np.percentile(same, 10)))
    drift = float(np.percentile(steps, 5)) if len(steps) >= MIN_SAMPLES else DEFAULT_DRIFT
    return {"looks_alike": looks_alike, "drift": drift, "n_same": len(same), "n_steps": len(steps)}


class GroupingEngine:
    """Per-profile grouping state; ``process`` places the next ready Assets."""

    def __init__(self):
        self.warm = False
        self.groups: dict[int, _Group] = {}
        # Auto
        self.auto_of: dict[int, int] = {}
        self.recency: collections.OrderedDict[int, _Group] = collections.OrderedDict()
        self.by_prompt: dict[str, int] = {}
        self.by_chat: dict[int, int] = {}
        self.by_import: dict[str, int] = {}
        self.last_by_tool: dict[str, tuple[int, datetime]] = {}
        # The latest upload (managed files with no tool and no chat): the next one
        # within UPLOAD_BATCH joins its group.
        self.last_upload: Optional[tuple[int, datetime]] = None
        # Theme
        self.theme_of: dict[int, int] = {}
        self.theme_parent: dict[int, int] = {}
        self.theme_by_prompt: dict[str, int] = {}
        self.thresholds = {"looks_alike": DEFAULT_LOOKS_ALIKE, "drift": DEFAULT_DRIFT, "n_same": 0, "n_steps": 0}
        # Pending writes for the batch being placed.
        self._next_id = 1
        self._members: list[tuple[str, Item, int, str]] = []
        self._refs: set[tuple[int, int]] = set()
        self._merged: list[int] = []

    # -- warm-up --------------------------------------------------------------

    async def warm_up(self, session: AsyncSession):
        self.__init__()
        for g in (await session.execute(select(AssetGroup).where(AssetGroup.deleted_at.is_(None)))).scalars():
            self.groups[g.id] = _Group(
                g.id, g.kind, title=g.title, title_source=g.title_source or "none",
                project_id=g.project_id, first_at=g.first_at, last_at=g.last_at,
                created_at=g.created_at,
            )
        rows = await session.execute(
            select(
                AssetGroupMember.kind, AssetGroupMember.asset_id, AssetGroupMember.group_id,
                AssetGroupMember.arrived_at, AssetGroupMember.typed_prompt, AssetGroupMember.tool_id,
                AssetGroupMember.chat_id, AssetGroupMember.import_key, AssetGroupMember.vector,
                AssetGroupMember.media_id,
            ).order_by(AssetGroupMember.assigned_at, AssetGroupMember.arrived_at, AssetGroupMember.asset_id)
        )
        auto_items = []
        for kind, asset_id, gid, arrived, prompt, tool, chat, key, raw, media_id in rows:
            g = self.groups.get(gid)
            if g is None:
                continue
            item = Item(asset_id, arrived, media_id=media_id, typed_prompt=prompt, tool_id=tool,
                        chat_id=chat, import_key=key, vector=decode_vector(raw), vector_bytes=raw)
            if kind == AUTO:
                self._remember_auto(item, g)
                auto_items.append(item)
            elif kind == THEME:
                self._remember_theme(item, g)
        self.thresholds = calibrate(auto_items)
        self._next_id = await self._max_group_id(session) + 1
        self.warm = True
        t = self.thresholds
        log.info(
            f"GROUPING: warmed {len(self.groups)} groups, {len(self.auto_of)} members; "
            f"looks-alike {t['looks_alike']:.3f}, drift {t['drift']:.3f} "
            f"({t['n_same']}/{t['n_steps']} samples)"
        )

    @staticmethod
    async def _max_group_id(session) -> int:
        top = await session.scalar(select(func.max(AssetGroup.id))) or 0
        try:
            seq = await session.scalar(text("SELECT seq FROM sqlite_sequence WHERE name = 'asset_groups'")) or 0
        except Exception:
            seq = 0
        return max(int(top), int(seq))

    def _remember_auto(self, item: Item, g: _Group):
        """State shared by placement and warm-up: everything a later Asset reads."""
        self.auto_of[item.asset_id] = g.id
        g.size += 1
        if item.vector is not None:
            g.add_vector(item.vector)
        g.touch(item.arrived_at)
        if item.typed_prompt and item.tool_id:
            self.by_prompt[item.typed_prompt] = g.id
        if item.chat_id is not None:
            self.by_chat[item.chat_id] = g.id
        if item.import_key == UPLOAD_KEY:
            self.last_upload = (g.id, item.arrived_at)
        elif item.import_key:
            self.by_import[item.import_key] = g.id
        if item.tool_id:
            self.last_by_tool[item.tool_id] = (g.id, item.arrived_at)
        # Groups in the order they were last touched, for the looks-alike window.
        self.recency[g.id] = g
        self.recency.move_to_end(g.id)

    def _remember_theme(self, item: Item, g: _Group):
        self.theme_of[item.asset_id] = g.id
        g.size += 1
        if item.typed_prompt and item.tool_id:
            self.theme_by_prompt[item.typed_prompt] = g.id

    # -- placement ------------------------------------------------------------

    def _new_group(self, kind: str, now: datetime) -> _Group:
        g = _Group(self._next_id, kind, created_at=now, new=True)
        self._next_id += 1
        self.groups[g.id] = g
        return g

    def _find(self, gid: int) -> int:
        root = gid
        while root in self.theme_parent:
            root = self.theme_parent[root]
        while gid != root:  # path compression
            nxt = self.theme_parent[gid]
            self.theme_parent[gid] = root
            gid = nxt
        return root

    def place_auto(self, item: Item, now: datetime) -> tuple[int, str]:
        v = item.vector
        g, reason, refs = None, None, []
        # 1. Lineage, while the source's group is active; otherwise a ref.
        for source_id, why in item.sources:
            gid = self.auto_of.get(source_id)
            if gid is None:
                continue
            sg = self.groups[gid]
            if sg.last_arrive is not None and item.arrived_at - sg.last_arrive > _REVISIT:
                refs.append(source_id)
                continue
            g, reason = sg, why
            break
        # 2. Same typed prompt (exact).
        if g is None and item.typed_prompt and item.tool_id and item.typed_prompt in self.by_prompt:
            g, reason = self.groups[self.by_prompt[item.typed_prompt]], "same prompt"
        # 3. Same chat.
        if g is None and item.chat_id is not None and item.chat_id in self.by_chat:
            g, reason = self.groups[self.by_chat[item.chat_id]], "chat"
        # 4. Same import folder and month, or the same upload batch.
        if g is None and item.import_key == UPLOAD_KEY and self.last_upload \
                and item.arrived_at - self.last_upload[1] <= UPLOAD_BATCH:
            g, reason = self.groups[self.last_upload[0]], "upload batch"
        elif g is None and item.import_key and item.import_key != UPLOAD_KEY and item.import_key in self.by_import:
            g, reason = self.groups[self.by_import[item.import_key]], "import folder"
        # 5. Drift or hop, against the frames the same tool just made.
        left = None
        if g is None and v is not None and item.tool_id:
            last = self.last_by_tool.get(item.tool_id)
            if last is not None and item.arrived_at - last[1] < _CONT:
                pg = self.groups[last[0]]
                if pg.tail_sim(v) >= self.thresholds["drift"]:
                    g, reason = pg, "drift"
                else:
                    left = pg  # a hop: looks-alike may not pull it straight back
        # 6. Looks alike a recently active group.
        if g is None and v is not None:
            best, best_sim = None, self.thresholds["looks_alike"]
            for n, cand in enumerate(reversed(self.recency.values())):
                if n >= CANDIDATES:
                    break
                if cand.last_arrive is not None and item.arrived_at - cand.last_arrive > _ACTIVE:
                    break  # touched in arrival order: everything older is idle too
                if cand is left:
                    continue
                s = cand.sim(v)
                # Newest wins a tie, as in the prototype's forward scan.
                if (best is None and s >= best_sim) or (best is not None and s > best_sim):
                    best, best_sim = cand, s
            if best is not None:
                g, reason = best, "looks alike"
        # 7. A new group.
        if g is None:
            g = self._new_group(AUTO, now)
            reason = "revisit" if refs else "hop" if left is not None else "new"
        self._remember_auto(item, g)
        g.place(item, item.display_at)
        for source_id in refs:
            if self.auto_of.get(source_id) != g.id:
                self._refs.add((g.id, source_id))
        self._members.append((AUTO, item, g.id, reason))
        return g.id, reason

    def place_theme(self, item: Item, now: datetime) -> tuple[int, str]:
        linked: list[tuple[int, str]] = []
        for source_id, _why in item.sources:
            gid = self.theme_of.get(source_id)
            if gid is not None:
                linked.append((self._find(gid), "lineage"))
        if item.typed_prompt and item.tool_id and item.typed_prompt in self.theme_by_prompt:
            linked.append((self._find(self.theme_by_prompt[item.typed_prompt]), "same prompt"))
        if not linked:
            g, reason = self._new_group(THEME, now), "new"
        else:
            roots = list(dict.fromkeys(gid for gid, _ in linked))
            reason = linked[0][1]
            # The largest theme absorbs the rest; the oldest wins a tie.
            target = self.groups[min(roots, key=lambda gid: (-self.groups[gid].size, gid))]
            for gid in roots:
                if gid != target.id:
                    self._merge_theme(self.groups[gid], target, now)
            g = target
        self._remember_theme(item, g)
        g.place(item, item.display_at)
        self._members.append((THEME, item, g.id, reason))
        return g.id, reason

    def _merge_theme(self, small: _Group, big: _Group, now: datetime):
        self.theme_parent[small.id] = big.id
        big.size += small.size
        if small.first_at is not None and (big.first_at is None or small.first_at < big.first_at):
            big.first_at = small.first_at
        if small.last_at is not None and (big.last_at is None or small.last_at > big.last_at):
            big.last_at = small.last_at
        if big.title_source == "none" and small.title_source != "none":
            big.title, big.title_source = small.title, small.title_source
        if big.project_id is None:
            big.project_id = small.project_id
        small.size = 0
        small.deleted_at = now
        small.dirty = big.dirty = True
        self._merged.append(small.id)

    # -- the pass ---------------------------------------------------------------

    async def process(self, session: AsyncSession, *, clip_enabled: bool = True,
                      now: Optional[datetime] = None, limit: int = BATCH_SIZE) -> int:
        """Place up to ``limit`` ready Assets and commit. Returns how many.

        Stops at the first Asset that isn't ready, so arrival order holds.
        The caller must drop this engine if it raises: memory may then be
        ahead of the database.
        """
        now = now or datetime.utcnow()
        if not self.warm:
            await self.warm_up(session)
        candidates = (
            await session.execute(
                select(
                    Asset.id, Asset.created_at, Asset.state, Asset.deleted_at,
                    MediaItem.id, MediaItem.metadata_status, MediaItem.clip_status,
                    MediaItem.file_unavailable, MediaItem.deleted_at, MediaItem.deletion_pending_at,
                )
                .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
                .join(MediaItem, MediaItem.id == AssetRevision.primary_media_id)
                .where(
                    ~exists().where(
                        AssetGroupMember.asset_id == Asset.id,
                        AssetGroupMember.kind == AUTO,
                    )
                )
                .order_by(Asset.created_at, Asset.id)
                .limit(limit)
            )
        ).all()
        ready = []
        for (asset_id, created_at, state, asset_deleted, media_id, meta, clip,
             unavailable, media_deleted, pending_delete) in candidates:
            if not is_ready(
                state=state, asset_deleted=asset_deleted is not None, created_at=created_at,
                metadata_status=meta, clip_status=clip, file_unavailable=bool(unavailable),
                media_gone=media_deleted is not None or pending_delete is not None,
                clip_enabled=clip_enabled, now=now,
            ):
                break
            ready.append((asset_id, created_at, media_id))
        if not ready:
            return 0
        items = await load_items(session, ready)
        for item in items:
            self.place_auto(item, now)
            self.place_theme(item, now)
        await self._write(session, now)
        await session.commit()
        return len(items)

    async def _write(self, session: AsyncSession, now: datetime):
        new_groups = [g for g in self.groups.values() if g.new]
        if new_groups:
            await session.execute(
                sqlite_insert(AssetGroup),
                [
                    {
                        "id": g.id, "kind": g.kind, "title": g.title, "title_source": g.title_source,
                        "project_id": g.project_id, "first_at": g.first_at, "last_at": g.last_at,
                        "created_at": g.created_at or now, "deleted_at": g.deleted_at,
                    }
                    for g in new_groups
                ],
            )
        changed = [g for g in self.groups.values() if g.dirty and not g.new]
        if changed:
            await session.execute(
                update(AssetGroup),
                [
                    {
                        "id": g.id, "title": g.title, "title_source": g.title_source,
                        "project_id": g.project_id, "first_at": g.first_at, "last_at": g.last_at,
                        "deleted_at": g.deleted_at,
                    }
                    for g in changed
                ],
            )
        if self._members:
            await session.execute(
                sqlite_insert(AssetGroupMember),
                [
                    {
                        "asset_id": item.asset_id, "kind": kind,
                        "group_id": self._find(gid) if kind == THEME else gid,
                        "reason": reason, "assigned_at": now, "media_id": item.media_id,
                        "arrived_at": item.arrived_at, "typed_prompt": item.typed_prompt,
                        "tool_id": item.tool_id, "chat_id": item.chat_id,
                        "import_key": item.import_key, "vector": item.vector_bytes,
                    }
                    for kind, item, gid, reason in self._members
                ],
            )
        for gid in self._merged:
            await session.execute(
                update(AssetGroupMember)
                .where(AssetGroupMember.kind == THEME, AssetGroupMember.group_id == gid)
                .values(group_id=self._find(gid))
            )
        if self._refs:
            await session.execute(
                sqlite_insert(AssetGroupRef).on_conflict_do_nothing(),
                [{"group_id": gid, "asset_id": aid} for gid, aid in sorted(self._refs)],
            )
        for g in self.groups.values():
            g.new = g.dirty = False
        for gid in self._merged:
            self.groups.pop(gid, None)
        self._members, self._refs, self._merged = [], set(), []


async def load_items(session: AsyncSession, ready: list[tuple[int, datetime, int]]) -> list[Item]:
    """Read each Asset's current Media into grouping inputs, in the given order."""
    media_ids = [m for _, _, m in ready]
    asset_ids = [a for a, _, _ in ready]
    media = {
        row.id: row
        for row in (
            await session.execute(
                select(
                    MediaItem.id, type_coerce(MediaItem.file_path, String).label("file_path"),
                    MediaItem.created_date, MediaItem.indexed_date, MediaItem.tool_id,
                    MediaItem.generation_metadata, MediaItem.extracted_prompt,
                    MediaItem.clip_status, MediaItem.clip_embedding, MediaItem.chat_item_id,
                ).where(MediaItem.id.in_(media_ids))
            )
        ).all()
    }

    # Lineage: derived edges first, in input order; then an inspired-by source.
    lineage = collections.defaultdict(list)
    for media_id, source_id, task, rel in (
        await session.execute(
            select(
                MediaLineage.media_id, MediaLineage.source_media_id,
                MediaLineage.task_type, MediaLineage.relationship_type,
            )
            .where(MediaLineage.media_id.in_(media_ids), MediaLineage.source_media_id.is_not(None))
            .order_by(MediaLineage.media_id, MediaLineage.source_order)
        )
    ).all():
        lineage[media_id].append((source_id, "remix" if rel == "inspired" else "lineage"))
    prompts = {}
    for mid, row in media.items():
        prompt, inspired = typed_prompt_of(row.generation_metadata, row.extracted_prompt)
        prompts[mid] = prompt
        if inspired and not any(s == inspired for s, _ in lineage[mid]):
            lineage[mid].append((inspired, "remix"))
    # Sources resolve Media -> Asset through every revision, not just heads.
    source_media = {s for edges in lineage.values() for s, _ in edges}
    asset_of_media = {}
    if source_media:
        asset_of_media = dict(
            (
                await session.execute(
                    select(AssetRevision.primary_media_id, AssetRevision.asset_id)
                    .where(AssetRevision.primary_media_id.in_(source_media))
                )
            ).all()
        )

    # Chat: the Media's chat item, else the first chat item that shows it.
    chat_of_media: dict[int, int] = {}
    chat_item_ids = {row.chat_item_id for row in media.values() if row.chat_item_id}
    if chat_item_ids:
        item_chat = dict(
            (await session.execute(select(ChatItem.id, ChatItem.chat_id).where(ChatItem.id.in_(chat_item_ids)))).all()
        )
        for mid, row in media.items():
            if row.chat_item_id in item_chat:
                chat_of_media[mid] = item_chat[row.chat_item_id]
    chat_of_asset: dict[int, int] = {}
    for chat_id, mid, aid in (
        await session.execute(
            select(ChatItem.chat_id, ChatItem.media_id, ChatItem.asset_id)
            .where((ChatItem.media_id.in_(media_ids)) | (ChatItem.asset_id.in_(asset_ids)))
            .order_by(ChatItem.id)
        )
    ).all():
        if mid is not None:
            chat_of_media.setdefault(mid, chat_id)
        if aid is not None:
            chat_of_asset.setdefault(aid, chat_id)
    for column, target in (("media_ids", chat_of_media), ("asset_ids", chat_of_asset)):
        wanted = media_ids if column == "media_ids" else asset_ids
        placeholders = ",".join(str(int(v)) for v in wanted)
        for chat_id, value in (
            await session.execute(
                text(
                    f"SELECT ci.chat_id, je.value FROM chat_items ci, json_each(ci.{column}) je "
                    f"WHERE ci.{column} IS NOT NULL AND json_valid(ci.{column}) "
                    f"AND je.value IN ({placeholders}) ORDER BY ci.id"
                )
            )
        ).all():
            try:
                target.setdefault(int(value), chat_id)
            except (TypeError, ValueError):
                pass
    chat_ids = set(chat_of_media.values()) | set(chat_of_asset.values())
    chats = {}
    if chat_ids:
        chats = {
            cid: (name, project_id)
            for cid, name, project_id in (
                await session.execute(select(Chat.id, Chat.name, Chat.project_id).where(Chat.id.in_(chat_ids)))
            ).all()
        }

    # The Asset's earliest live project.
    project_of: dict[int, int] = {}
    for aid, pid in (
        await session.execute(
            select(ProjectAsset.asset_id, ProjectAsset.project_id)
            .join(Project, Project.id == ProjectAsset.project_id)
            .where(
                ProjectAsset.asset_id.in_(asset_ids),
                ProjectAsset.deleted_at.is_(None),
                Project.deleted_at.is_(None),
            )
            .order_by(ProjectAsset.added_at, ProjectAsset.id)
        )
    ).all():
        project_of.setdefault(aid, pid)

    items = []
    for asset_id, arrived_at, media_id in ready:
        row = media.get(media_id)
        item = Item(asset_id, arrived_at, media_id=media_id)
        if row is None:
            items.append(item)
            continue
        item.typed_prompt = prompts.get(media_id)
        item.tool_id = row.tool_id or None
        item.chat_id = chat_of_media.get(media_id, chat_of_asset.get(asset_id))
        if row.clip_status == "completed":
            item.vector_bytes, item.vector = encode_embedding(row.clip_embedding)
        item.display_at = row.created_date or row.indexed_date or arrived_at
        if item.chat_id is not None and item.chat_id in chats:
            name, chat_project = chats[item.chat_id]
            item.chat_name = name or None
            item.project_id = chat_project
        if not item.tool_id and item.chat_id is None and (row.file_path or "").startswith("@data/"):
            # A managed file (an upload): its folder is per-file storage, so it
            # groups by upload batch instead.
            item.import_key = UPLOAD_KEY
            item.folder_title = "Uploads"
        elif not item.tool_id and item.chat_id is None:
            folder = os.path.dirname(row.file_path or "")
            month = row.created_date.strftime("%Y-%m") if row.created_date else ""
            item.import_key = f"{folder}|{month}"
            label = os.path.basename(folder.rstrip("/\\")) or "Imported"
            if row.created_date:
                label = f"{label} · {_MONTHS[row.created_date.month - 1]} {row.created_date.year}"
            item.folder_title = label
        item.project_id = project_of.get(asset_id, item.project_id)
        item.sources = [
            (asset_of_media[s], why)
            for s, why in lineage.get(media_id, [])
            if s in asset_of_media and asset_of_media[s] != asset_id
        ]
        items.append(item)
    return items


async def grouping_version(session: AsyncSession) -> Optional[str]:
    """The latest assignment time: changes whenever the pass places Assets."""
    value = await session.scalar(select(func.max(AssetGroupMember.assigned_at)))
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


async def run_grouping_pass(engines: dict, profile_id: str, db, *, clip_enabled: bool) -> int:
    """One pass for one profile with its cached engine; drops the engine on error."""
    engine = engines.get(profile_id)
    if engine is None or getattr(engine, "db", None) is not db:
        # A profile re-registered with another database starts fresh.
        engine = engines[profile_id] = GroupingEngine()
        engine.db = db
    try:
        async with db.async_session_maker() as session:
            return await engine.process(session, clip_enabled=clip_enabled)
    except Exception:
        engines.pop(profile_id, None)
        raise
