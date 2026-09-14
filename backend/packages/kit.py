"""The cover component kit.

One vocabulary every cover uses — the plain auto cover and, above all, the
cover an agent designs. Components provide reusable defaults. The author chooses composition and may
override colors, typography and layout to suit the work and the recipient.

Components, all usable in authored HTML:

    <stimma-section label="Included work" page layout="pair">…</stimma-section>
        page: landscape PDF boundary; layout: single, pair, or stack
    <stimma-media ref="m1" caption="Primary mark" plate>
    <stimma-grid>…<stimma-media>…</stimma-grid>
    <stimma-sizes>       real-size row; children are <stimma-media ref size="40">
    <stimma-columns>…<stimma-column title="…">…</stimma-columns>
    <stimma-files ref="r1">    the file browser
    <stimma-compare a="…" b="…" mode="slider">
    <stimma-appearance>  a Light/Dark switch; children marked when="light" / when="dark"

Every one expands to plain HTML when the bundle is written, so a cover reads
correctly with scripts disabled, from a double-clicked file, and in a frame.
The script only enhances what needs behaviour.
"""

from __future__ import annotations

import html as htmllib
from html.parser import HTMLParser
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from packages.manifest import member_by_id, resolve_ref, run_by_id

KIT_VERSION = 9

# The elements a cover may use. Anything else is the author's own markup.
COMPONENTS = (
    "stimma-section", "stimma-media", "stimma-grid", "stimma-sizes",
    "stimma-columns", "stimma-column", "stimma-files",
    "stimma-compare", "stimma-appearance",
)
# Registered but inert: feedback is a later design pass. An authored cover
# using one renders its children instead of breaking.
RESERVED_COMPONENTS = ("stimma-pick", "stimma-approve", "stimma-comments")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}
VIDEO_EXTS = {".mp4", ".webm", ".mov"}

# The Stimma mark, embedded so a cover carries its maker with it offline.
LOGO_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-label="Stimma"><g transform="translate(512 512)"><path fill="#F38724" transform="rotate(266.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#E73B31" transform="rotate(311.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#BC2073" transform="rotate(356.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#62B253" transform="rotate(41.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#039E96" transform="rotate(86.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#2376BC" transform="rotate(131.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#6C3A91" transform="rotate(176.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/><path fill="#F8CF11" transform="rotate(221.85)" d="M 23.7,-2.0 C 184.5,-101.9 272.2,-196.0 504.2,27.9 C 504.2,37.8 359.8,125.4 314.7,134.2 C 248.2,92.8 306.0,59.5 23.7,-2.0 Z"/></g></svg>'''


def escape(text: Any) -> str:
    return htmllib.escape("" if text is None else str(text), quote=True)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# Builders — for Python callers such as the auto cover, so they
# emit components instead of hand-written markup that drifts.

def section(body: str, *, label: str = "") -> str:
    attr = f' label="{escape(label)}"' if label else ""
    return f"<stimma-section{attr}>{body}</stimma-section>"


def media(ref: str, *, caption: str = "", size: Optional[int] = None, plate: bool = False) -> str:
    attrs = f' ref="{escape(ref)}"'
    if caption:
        attrs += f' caption="{escape(caption)}"'
    if size:
        attrs += f' size="{int(size)}"'
    if plate:
        attrs += " plate"
    return f"<stimma-media{attrs}></stimma-media>"


def grid(items: Iterable[str], *, cell: int = 0) -> str:
    style = f' style="--sp-cell:{int(cell)}px"' if cell else ""
    return f"<stimma-grid{style}>{''.join(items)}</stimma-grid>"


def sizes(items: Iterable[str]) -> str:
    return f"<stimma-sizes>{''.join(items)}</stimma-sizes>"


def columns(entries: Iterable[tuple[str, str]]) -> str:
    body = "".join(
        f'<stimma-column title="{escape(title)}">{escape(text)}</stimma-column>'
        for title, text in entries
    )
    return f"<stimma-columns>{body}</stimma-columns>"


def files(ref: str = "") -> str:
    attr = f' ref="{escape(ref)}"' if ref else ""
    return f"<stimma-files{attr}></stimma-files>"


def hero(*parts: str) -> str:
    return f'<div class="sp-hero">{"".join(parts)}</div>'


KIT_CSS = """
:root{
  --sp-bg:#0d0d0e; --sp-fg:#ededee; --sp-muted:#8b8b8f; --sp-faint:#5c5c60;
  --sp-line:#232325; --sp-accent:#2dd4bf; --sp-plate:#151517;
}
@media (prefers-color-scheme: light){
  :root{--sp-bg:#faf9f7; --sp-fg:#17171a; --sp-muted:#6b6b70; --sp-faint:#97979c;
        --sp-line:#e5e2dd; --sp-accent:#0d9488; --sp-plate:#f1efec;}
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--sp-bg);color:var(--sp-fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
img{display:block}
.sp-page{max-width:880px;margin:0 auto;padding:56px 28px 88px}
.sp-title{font-size:clamp(28px,4vw,42px);line-height:1.05;letter-spacing:-0.022em;margin:0;font-weight:600}
.sp-sub{color:var(--sp-muted);margin:8px 0 0;font-size:14px}
.sp-sub b{color:var(--sp-fg);font-weight:500}
.sp-section{margin-top:56px}
.sp-label{font-size:13px;letter-spacing:.01em;color:var(--sp-fg);margin:0 0 18px;font-weight:600}
.sp-note{color:var(--sp-muted);font-size:13px;margin:12px 0 0}
.sp-num{font-variant-numeric:tabular-nums}
.sp-hr{border:0;border-top:1px solid var(--sp-line);margin:0}

/* Media: artwork sits on a matte, never in a bordered card. */
stimma-media{display:block}
stimma-media img,stimma-media video{max-width:100%;height:auto;border-radius:2px}
stimma-media[plate] img{background:var(--sp-plate);padding:24px;border-radius:10px}
stimma-media .sp-caption{font-size:12px;color:var(--sp-muted);padding-top:8px}
stimma-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--sp-cell,200px),1fr));gap:28px}

/* Scrollbars: one quiet style for the whole page — thin, no track, no arrows. */
*{scrollbar-width:thin;scrollbar-color:var(--sp-line) transparent}

/* Files: one button, "View contents", that gives way to a file manager in
   its place. Native <details>, so the listing is still reachable with scripts
   off: the static tree is the data, and the script builds the manager on top
   of it. The archive itself is the app's to offer, not the page's. */
stimma-files{display:block;margin-top:28px}
.sp-files{display:block}
.sp-files>summary{list-style:none;display:flex;align-items:center;justify-content:center;
  padding:2px 0;cursor:pointer}
.sp-files>summary::-webkit-details-marker{display:none}
.sp-files>summary:focus{outline:none}
.sp-files>summary:focus-visible{outline:2px solid var(--sp-accent);outline-offset:4px;border-radius:8px}
.sp-browse{display:inline-flex;align-items:center;gap:8px;font-size:13.5px;font-weight:500;
  color:var(--sp-fg);background:var(--sp-plate);padding:9px 16px;border-radius:7px;flex:none;
  transition:background-color .15s}
.sp-files>summary:hover .sp-browse{background:var(--sp-line)}
/* Once open, the button has done its job; the browser stands where it stood.
   Escape brings it back. With scripts off the tree simply appears beneath. */
.sp-live .sp-files[open]>summary{display:none}
.sp-files[open]>summary .sp-browse .sp-caret{transform:rotate(180deg)}
.sp-caret{width:11px;height:11px;flex:none;display:inline-flex;align-items:center;
  justify-content:center;transition:transform .15s}
.sp-caret svg{width:11px;height:11px;stroke:currentColor;fill:none;stroke-width:2.2;
  stroke-linecap:round;stroke-linejoin:round}

/* The surface: one raised container, one hairline between bar and content. */
.sp-browser{display:flex;flex-direction:column;min-width:0;
  border:1px solid var(--sp-line);border-radius:10px;overflow:hidden}
.sp-browser [hidden]{display:none!important}
stimma-files button{font:inherit;color:inherit;background:none;border:0;padding:0;margin:0;cursor:pointer}
stimma-files button:focus{outline:none}
stimma-files button:focus-visible{outline:2px solid var(--sp-accent);outline-offset:1px}
stimma-files .sp-thumb{width:26px;height:26px;flex:none;border-radius:4px;object-fit:contain;
  background:var(--sp-plate)}
stimma-files .sp-glyph{width:26px;height:26px;flex:none;display:inline-flex;align-items:center;
  justify-content:center;color:var(--sp-faint)}
stimma-files .sp-glyph svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.6;
  stroke-linecap:round;stroke-linejoin:round}
stimma-files .sp-name{flex:1;min-width:0;font-size:13px;line-height:1.35;color:var(--sp-fg);
  overflow-wrap:anywhere}
stimma-files .sp-meta{color:var(--sp-faint);font-size:12px;font-variant-numeric:tabular-nums;flex:none;
  min-width:56px;text-align:right}
.sp-dl{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;
  border-radius:6px;color:var(--sp-faint);flex:none;transition:color .15s,background-color .15s}
.sp-dl:hover{color:var(--sp-fg);background:var(--sp-line)}
.sp-dl:focus{outline:none}
.sp-dl:focus-visible{outline:2px solid var(--sp-accent);outline-offset:-1px}
.sp-dl svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round}

/* The static tree: what a reader with scripts off gets. */
.sp-tree{padding:8px 10px;max-height:520px;overflow:auto}
.sp-live .sp-tree{display:none}
.sp-tree ul{list-style:none;margin:0;padding:0}
.sp-tree li.sp-dir>ul{margin-left:12px;padding-left:14px;border-left:1px solid var(--sp-line)}
.sp-tree .sp-row{display:flex;align-items:center;gap:10px;padding:5px 8px;min-height:34px}
.sp-tree li.sp-dir>.sp-row .sp-name{color:var(--sp-muted)}

/* The bar: where you are, and how you are looking at it. */
.sp-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 10px;min-height:48px;
  border-bottom:1px solid var(--sp-line)}
.sp-crumbs{display:flex;align-items:center;flex-wrap:wrap;gap:1px;flex:1;min-width:0}
.sp-crumb{font-size:13px;color:var(--sp-muted);padding:5px 8px;border-radius:6px;max-width:100%;
  text-align:left;overflow-wrap:anywhere;transition:color .15s,background-color .15s}
.sp-crumb:hover{color:var(--sp-fg);background:var(--sp-plate)}
.sp-crumb[aria-current]{color:var(--sp-fg);cursor:default}
.sp-crumb[aria-current]:hover{background:none}
.sp-crumb-sep{color:var(--sp-faint);font-size:12px;padding:0 2px}
.sp-seg{display:inline-flex;gap:2px;padding:2px;border-radius:8px;background:var(--sp-plate);flex:none}
.sp-seg button{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--sp-muted);
  padding:4px 10px;border-radius:6px;transition:color .15s,background-color .15s}
.sp-seg button:hover{color:var(--sp-fg)}
.sp-seg button[aria-pressed=true]{background:var(--sp-line);color:var(--sp-fg)}
.sp-seg svg{width:13px;height:13px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round}
.sp-vacts{display:inline-flex;align-items:center;gap:2px;flex:none}
.sp-vact{display:inline-flex;align-items:center;justify-content:center;gap:6px;font-size:12px;
  color:var(--sp-muted);padding:5px 9px;min-width:28px;min-height:28px;border-radius:6px;
  transition:color .15s,background-color .15s}
.sp-vact:hover{color:var(--sp-fg);background:var(--sp-plate)}
.sp-vact:disabled{opacity:.35;cursor:default}
.sp-vact:disabled:hover{color:var(--sp-muted);background:none}
.sp-vact[aria-pressed=true]{color:var(--sp-accent)}
.sp-vact svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.75;
  stroke-linecap:round;stroke-linejoin:round}
.sp-vpos{font-size:12px;color:var(--sp-faint);font-variant-numeric:tabular-nums;padding:0 4px}

/* The listing: rows or tiles, never a tree. A click opens. */
.sp-area{height:400px;overflow:auto;padding:6px}
.sp-area:focus{outline:none}
.sp-list{display:flex;flex-direction:column;gap:1px}
.sp-item{display:flex;align-items:center;gap:10px;padding:4px 10px;min-height:34px;
  border-radius:7px;cursor:pointer;user-select:none;position:relative;
  transition:background-color .12s}
.sp-item:hover{background:var(--sp-plate)}
.sp-item:focus{outline:none}
.sp-item:focus-visible{outline:2px solid var(--sp-accent);outline-offset:-2px}
/* Rows size to their tiles: inside a fixed-height scroller, auto rows get squeezed. */
.sp-icons{display:grid;grid-template-columns:repeat(auto-fill,minmax(136px,1fr));gap:2px;
  grid-auto-rows:max-content;align-content:start}
.sp-icons .sp-item{flex-direction:column;justify-content:flex-start;gap:0;padding:10px 6px 8px;
  text-align:center;min-height:0}
.sp-icons .sp-item .sp-thumb,.sp-icons .sp-item .sp-glyph{width:80px;height:80px;border-radius:8px;
  margin-bottom:6px}
.sp-icons .sp-item .sp-glyph svg{width:52px;height:52px;stroke-width:1.2}
.sp-icons .sp-item .sp-name{flex:none;width:100%;font-size:12.5px;line-height:1.3;overflow-wrap:break-word}
.sp-icons .sp-item .sp-meta{font-size:11px;min-width:0;text-align:center;margin-top:1px}
.sp-empty{color:var(--sp-faint);font-size:13px;margin:0;padding:24px 10px;text-align:center}

/* The viewer: the file, and its facts. */
.sp-view{display:flex;flex-direction:column;min-width:0;height:400px}
.sp-view:focus{outline:none}
.sp-facts{font-size:12px;color:var(--sp-faint);font-variant-numeric:tabular-nums;
  padding:10px 14px 0;overflow-wrap:anywhere}
.sp-view-body{flex:1;min-height:0;overflow:auto;padding:12px 14px 14px;
  display:flex;flex-direction:column;gap:10px}
.sp-view-body.sp-center{align-items:center;justify-content:center;text-align:center}
.sp-shot{max-width:100%;width:auto;height:auto;border-radius:2px;
  background:repeating-conic-gradient(#8883 0% 25%,transparent 0% 50%) 50%/16px 16px}
video.sp-shot,audio.sp-shot{width:100%;background:none}
.sp-code{margin:0;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  color:var(--sp-muted);white-space:pre-wrap;word-break:break-word;tab-size:2}
.sp-blank{display:grid;justify-items:center;gap:8px;color:var(--sp-faint);font-size:13px}
.sp-blank .sp-glyph{width:40px;height:40px}
.sp-blank .sp-glyph svg{width:30px;height:30px}
.sp-vnote{color:var(--sp-faint);font-size:12px;margin:0}

/* Compare */
stimma-compare{display:block}
stimma-compare .sp-cmp{display:grid;grid-template-columns:1fr 1fr;gap:20px}
stimma-compare figure{margin:0;min-width:0}
stimma-compare img{display:block;max-width:100%;height:auto}
stimma-compare figcaption{font-size:12px;color:var(--sp-muted);padding-top:8px}
stimma-compare.sp-slider{position:relative}
stimma-compare.sp-slider .sp-cmp{display:block;position:relative}
stimma-compare.sp-slider figure:first-child{position:absolute;inset:0;overflow:hidden;width:var(--sp-split,50%)}
stimma-compare.sp-slider figure:first-child img{width:var(--sp-w,100%);max-width:none}
stimma-compare.sp-slider figure:last-child figcaption{text-align:right}
stimma-compare.sp-slider input[type=range]{position:absolute;left:0;right:0;bottom:32px;width:100%;margin:0}

/* Appearance: one Light/Dark switch, one appearance visible at a time. Pure
   CSS — two radios and :has() — so it works from a double-clicked file with
   scripts off. Until the reader chooses, the system appearance decides. */
stimma-appearance{display:block}
stimma-appearance .sp-seg{margin-bottom:18px}
stimma-appearance .sp-seg label{display:inline-flex;align-items:center;font-size:12.5px;color:var(--sp-muted);
  padding:5px 12px;border-radius:6px;cursor:pointer;user-select:none;transition:background-color .15s,color .15s}
stimma-appearance .sp-seg label:hover{color:var(--sp-fg)}
stimma-appearance input[type=radio]{position:absolute;opacity:0;width:0;height:0}
stimma-appearance .sp-seg label:has(input:focus-visible){outline:2px solid var(--sp-accent);outline-offset:1px}
stimma-appearance .sp-appearance-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px}
stimma-appearance .sp-appearance-head .sp-label{margin:0 0 18px}
/* Both panels share one cell during the crossfade. Grouping preserves each
   authored child's display and reserves enough height to avoid a layout jump. */
.sp-appearance-body{display:grid}
.sp-appearance-panel{grid-area:1/1;min-width:0;align-self:start;opacity:1;visibility:visible;
  transition:opacity .18s ease,visibility 0s}
@media (prefers-color-scheme: dark){
  stimma-appearance:not(:has(input:checked))>.sp-appearance-body>.sp-appearance-panel[data-when=light]{opacity:0;visibility:hidden;pointer-events:none;transition:opacity .18s ease,visibility 0s .18s}
  stimma-appearance:not(:has(input:checked)) .sp-seg label.sp-dark{background:var(--sp-line);color:var(--sp-fg)}
}
@media not (prefers-color-scheme: dark){
  stimma-appearance:not(:has(input:checked))>.sp-appearance-body>.sp-appearance-panel[data-when=dark]{opacity:0;visibility:hidden;pointer-events:none;transition:opacity .18s ease,visibility 0s .18s}
  stimma-appearance:not(:has(input:checked)) .sp-seg label.sp-light{background:var(--sp-line);color:var(--sp-fg)}
}
stimma-appearance:has(.sp-pick-light:checked)>.sp-appearance-body>.sp-appearance-panel[data-when=dark]{opacity:0;visibility:hidden;pointer-events:none;transition:opacity .18s ease,visibility 0s .18s}
stimma-appearance:has(.sp-pick-light:checked) .sp-seg label.sp-light{background:var(--sp-line);color:var(--sp-fg)}
stimma-appearance:has(.sp-pick-dark:checked)>.sp-appearance-body>.sp-appearance-panel[data-when=light]{opacity:0;visibility:hidden;pointer-events:none;transition:opacity .18s ease,visibility 0s .18s}
stimma-appearance:has(.sp-pick-dark:checked) .sp-seg label.sp-dark{background:var(--sp-line);color:var(--sp-fg)}
@media (prefers-reduced-motion:reduce){
  stimma-appearance .sp-appearance-panel,stimma-appearance .sp-seg label{transition:none!important}
}

/* Reserved widgets render their children and nothing else for now. */
stimma-pick,stimma-approve,stimma-comments{display:block}

.sp-footer{margin-top:72px;padding-top:20px;border-top:1px solid var(--sp-line);
  display:flex;align-items:center;gap:9px;color:var(--sp-faint);font-size:12px}
.sp-footer svg{width:17px;height:17px;flex:none}
.sp-footer .sp-brand{display:inline-flex;align-items:baseline;gap:7px;color:var(--sp-muted)}
.sp-footer .sp-wordmark{font-family:"General Sans",system-ui,sans-serif;
  text-transform:lowercase;letter-spacing:.12em;font-size:13px;color:var(--sp-fg)}

/* Section, sizes, device, columns ----------------------------------------- */
stimma-section{display:block;margin-top:56px}
stimma-section:first-child{margin-top:0}
stimma-section[layout]>.sp-section-body{display:grid;gap:24px;align-items:center}
stimma-section[layout=pair]>.sp-section-body{grid-template-columns:repeat(2,minmax(0,1fr))}
stimma-section[layout=single]>.sp-section-body,stimma-section[layout=stack]>.sp-section-body{grid-template-columns:minmax(0,1fr)}
stimma-section[layout]>.sp-section-body>stimma-media{min-width:0}
.sp-section-details{margin-top:24px}
.sp-section-disclosure>details>summary{cursor:pointer;color:var(--sp-muted);font-size:13px;
  padding:12px 0;border-top:1px solid var(--sp-line)}
.sp-section-disclosure>details>summary:hover{color:var(--sp-fg)}
.sp-section-disclosure>details>summary:focus-visible{outline:2px solid var(--sp-accent);outline-offset:4px}
.sp-section-disclosure>details>stimma-appearance{margin-top:16px}
.sp-section-disclosure stimma-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;align-items:start}
@media(max-width:600px){.sp-section-disclosure stimma-grid{grid-template-columns:minmax(0,1fr)}}
.sp-section-details>stimma-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;align-items:start}
@media(max-width:600px){.sp-section-details>stimma-grid{grid-template-columns:minmax(0,1fr)}}
@media(max-width:600px){stimma-section[layout=pair]>.sp-section-body{grid-template-columns:minmax(0,1fr)}}
stimma-sizes{display:flex;align-items:flex-end;gap:30px;flex-wrap:wrap}
stimma-sizes stimma-media{display:grid;justify-items:center;gap:9px}
stimma-sizes stimma-media img{border-radius:22.37%}
stimma-sizes .sp-caption{padding:0;font-size:11px;color:var(--sp-faint);
  font-variant-numeric:tabular-nums}
stimma-columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:28px}
stimma-column{display:block}
stimma-column h3{margin:0 0 5px;font-size:13.5px;font-weight:500}
stimma-column p{margin:0;font-size:13px;color:var(--sp-muted);line-height:1.5}
"""

KIT_JS = r"""
(function(){
  if (window.__stimmaKit) return; window.__stimmaKit = true;

  var manifestEl = document.getElementById('stimma-package-manifest');
  var manifest = null;
  try { manifest = manifestEl ? JSON.parse(manifestEl.textContent) : null; } catch (e) { manifest = null; }
  window.stimmaPackage = {
    manifest: manifest,
    kitVersion: %(kit_version)d,
    host: document.documentElement.getAttribute('data-stimma-host') || null
  };

  // Components are registered so the page has stable element names, but none
  // of them wire themselves up. A custom element's connectedCallback runs when
  // its opening tag is parsed, before any of its children exist, so anything
  // that queries inside itself there finds an empty element — which is exactly
  // how the file tree ended up inert. Behaviour is attached once the document
  // is parsed, by delegation from the document, which also survives content
  // arriving later.
  function define(name){
    if (window.customElements && !customElements.get(name)) {
      customElements.define(name, class extends HTMLElement {});
    }
  }
  ['stimma-section','stimma-media','stimma-grid','stimma-sizes',
   'stimma-columns','stimma-column','stimma-files','stimma-compare','stimma-appearance',
   'stimma-pick','stimma-approve','stimma-comments'].forEach(define);

  function ready(fn){
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  function closest(el, sel){
    return (el && el.closest) ? el.closest(sel) : null;
  }

  // The file browser. Compact by default: a <details> whose summary is the
  // quiet row, and whose open state is a file manager inside the page — no
  // overlay, no tree-plus-pane. The static tree the server wrote is the data;
  // the manager is built from it here, and text is read straight out of the
  // rows, because a cover has to work from a double-clicked file, where
  // fetch() of a sibling file is blocked by every browser.
  function setupFiles(){
    var DOT = ' · ';
    var ICON = {
      back: '<path d="m15 6-6 6 6 6"/>',
      next: '<path d="m9 6 6 6-6 6"/>',
      list: '<path d="M4 6h16M4 12h16M4 18h16"/>',
      grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/>' +
            '<rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
      file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
    };

    function el(tag, cls){
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      return node;
    }
    function svg(paths){
      return '<svg viewBox="0 0 24 24" aria-hidden="true">' + paths + '</svg>';
    }
    function button(cls, label, paths, text){
      var b = el('button', cls);
      b.type = 'button';
      b.setAttribute('aria-label', label);
      b.innerHTML = paths ? svg(paths) : '';
      if (text) { var t = el('span'); t.textContent = text; b.appendChild(t); }
      return b;
    }
    function unpack(text){
      return text.replace(/<\\\//g, '</').replace(/<\\!--/g, '<!--');
    }
    function sourceOf(li){
      var holder = li.querySelector(':scope > script.sp-src');
      return holder ? unpack(holder.textContent) : null;
    }
    function pretty(text){
      try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return text; }
    }
    function attr(li, name){ return li.getAttribute('data-' + name) || ''; }
    function isDir(li){ return li.classList.contains('sp-dir'); }
    function entries(ul){
      return Array.prototype.filter.call(ul.children, function(li){ return li.tagName === 'LI'; });
    }
    function blank(body, label){
      body.className = 'sp-view-body sp-center';
      var box = el('div', 'sp-blank');
      var glyph = el('span', 'sp-glyph');
      glyph.innerHTML = svg(ICON.file);
      var text = el('span');
      text.textContent = label;
      box.appendChild(glyph); box.appendChild(text);
      body.appendChild(box);
    }
    function focusQuiet(node){
      if (!node) return;
      try { node.focus({ preventScroll: true }); } catch (e) { node.focus(); }
    }

    document.querySelectorAll('stimma-files').forEach(function(files){
      var details = files.querySelector('details.sp-files');
      var tree = files.querySelector('.sp-tree');
      var browser = files.querySelector('.sp-browser');
      var root = tree ? tree.querySelector('ul') : null;
      if (!details || !browser || !root) return;
      files.classList.add('sp-live');

      // Where we are: a folder (a <ul> in the tree), an open file (its <li>),
      // and how the folder is shown.
      var state = { folder: root, file: null, mode: 'list' };

      var bar = el('div', 'sp-bar');
      var crumbs = el('nav', 'sp-crumbs');
      crumbs.setAttribute('aria-label', 'Location');
      var seg = el('div', 'sp-seg');
      seg.setAttribute('role', 'group');
      seg.setAttribute('aria-label', 'View');
      var modes = {};
      [['list', 'List', ICON.list], ['icons', 'Icons', ICON.grid]].forEach(function(spec){
        var b = button('', spec[1], spec[2], spec[1]);
        b.addEventListener('click', function(){ state.mode = spec[0]; draw(); });
        modes[spec[0]] = b;
        seg.appendChild(b);
      });
      var acts = el('div', 'sp-vacts');
      var area = el('div', 'sp-area');
      var view = el('div', 'sp-view');
      view.tabIndex = -1;
      bar.appendChild(crumbs); bar.appendChild(seg); bar.appendChild(acts);
      browser.appendChild(bar); browser.appendChild(area); browser.appendChild(view);

      function parentFolder(ul){ return ul === root ? null : ul.parentElement.parentElement; }
      function chain(){
        var out = [], ul = state.folder;
        while (ul) { out.unshift(ul); ul = parentFolder(ul); }
        return out;
      }
      function labelOf(ul){
        return ul === root ? (tree.getAttribute('data-root') || 'Files') : attr(ul.parentElement, 'name');
      }
      function crumb(label, action){
        var b = el('button', 'sp-crumb');
        b.type = 'button';
        b.textContent = label;
        if (action) b.addEventListener('click', action);
        else b.setAttribute('aria-current', 'page');
        crumbs.appendChild(b);
      }
      function sep(){
        var s = el('span', 'sp-crumb-sep');
        s.textContent = '›';
        s.setAttribute('aria-hidden', 'true');
        crumbs.appendChild(s);
      }
      function drawCrumbs(){
        crumbs.textContent = '';
        var path = chain();
        path.forEach(function(ul, i){
          if (i) sep();
          var here = i === path.length - 1 && !state.file;
          crumb(labelOf(ul), here ? null : function(){ goTo(ul); });
        });
        if (state.file) { sep(); crumb(attr(state.file, 'name'), null); }
      }

      function item(li){
        var dir = isDir(li);
        var node = el('div', 'sp-item' + (dir ? ' sp-folder' : ''));
        node.setAttribute('role', 'button');
        node.tabIndex = -1;
        node.__li = li;
        var lead = li.querySelector(':scope > .sp-row > .sp-thumb, :scope > .sp-row > .sp-glyph');
        if (lead) node.appendChild(lead.cloneNode(true));
        var name = el('span', 'sp-name');
        name.textContent = attr(li, 'name');
        node.appendChild(name);
        var meta = el('span', 'sp-meta');
        meta.textContent = dir ? attr(li, 'count') + (attr(li, 'count') === '1' ? ' file' : ' files')
                               : attr(li, 'size');
        node.appendChild(meta);
        return node;
      }
      function items(){ return Array.prototype.slice.call(area.querySelectorAll('.sp-item')); }
      function itemFor(li){
        return items().filter(function(node){ return node.__li === li; })[0] || null;
      }

      function drawList(focusLi){
        view.hidden = true; acts.hidden = true;
        area.hidden = false; seg.hidden = false;
        area.className = 'sp-area ' + (state.mode === 'icons' ? 'sp-icons' : 'sp-list');
        area.textContent = '';
        Object.keys(modes).forEach(function(key){
          modes[key].setAttribute('aria-pressed', key === state.mode ? 'true' : 'false');
        });
        var list = entries(state.folder);
        if (!list.length) {
          var empty = el('p', 'sp-empty');
          empty.textContent = 'This folder is empty.';
          area.appendChild(empty);
          return;
        }
        list.forEach(function(li){ area.appendChild(item(li)); });
        var target = (focusLi && itemFor(focusLi)) || area.querySelector('.sp-item');
        if (target) target.tabIndex = 0;
        if (focusLi && target) focusQuiet(target);
      }

      function facts(li, extra){
        var name = attr(li, 'name');
        var ext = (name.split('.').pop() || '').toUpperCase();
        var parts = [];
        if (ext && ext !== name.toUpperCase()) parts.push(ext);
        if (extra) parts.push(extra);
        parts.push(attr(li, 'size'));
        return parts.join(DOT);
      }

      function drawView(){
        var li = state.file;
        var kind = attr(li, 'kind');
        var name = attr(li, 'name');
        var path = attr(li, 'path');
        var source = sourceOf(li);

        area.hidden = true; seg.hidden = true;
        view.hidden = false; acts.hidden = false;
        acts.textContent = '';
        var siblings = entries(state.folder).filter(function(x){ return !isDir(x); });
        var at = siblings.indexOf(li);
        var prev = button('sp-vact', 'Previous file', ICON.back);
        prev.disabled = at <= 0;
        prev.addEventListener('click', function(){ step(-1); });
        var pos = el('span', 'sp-vpos');
        pos.textContent = (at + 1) + ' of ' + siblings.length;
        var next = button('sp-vact', 'Next file', ICON.next);
        next.disabled = at >= siblings.length - 1;
        next.addEventListener('click', function(){ step(1); });
        acts.appendChild(prev); acts.appendChild(pos); acts.appendChild(next);
        // No href means the file is not alongside the page (a single-file
        // export), and an inert button is worse than no button.
        var dl = li.querySelector(':scope > .sp-row > .sp-dl');
        if (dl && dl.getAttribute('href')) {
          var copy = dl.cloneNode(true);
          copy.className = 'sp-vact';
          var label = el('span');
          label.textContent = 'Download';
          copy.appendChild(label);
          acts.appendChild(copy);
        }

        view.textContent = '';
        var meta = el('p', 'sp-facts');
        meta.textContent = facts(li);
        var body = el('div', 'sp-view-body');
        view.appendChild(meta); view.appendChild(body);

        if (kind === 'image' || kind === 'svg') {
          body.className = 'sp-view-body sp-center';
          var img = el('img', 'sp-shot');
          img.alt = name;
          img.addEventListener('load', function(){
            if (img.naturalWidth) meta.textContent = facts(li, img.naturalWidth + ' × ' + img.naturalHeight);
          });
          img.addEventListener('error', function(){
            body.textContent = '';
            blank(body, 'This file cannot be shown here');
          });
          // The row's thumbnail is the same file, and it is the one reference
          // a single-file export rewrites — so it is the one worth following.
          var thumb = li.querySelector(':scope > .sp-row > .sp-thumb');
          img.src = (thumb && thumb.getAttribute('src')) || path;
          body.appendChild(img);
          return;
        }
        if (kind === 'text') {
          if (source === null) {
            body.className = 'sp-view-body sp-center';
            var away = el('p', 'sp-empty');
            away.textContent = 'Open the package to view this file.';
            body.appendChild(away);
            return;
          }
          var pre = el('pre', 'sp-code');
          pre.textContent = /\.(json|webmanifest)$/i.test(name) ? pretty(source) : source;
          body.appendChild(pre);
          if (attr(li, 'truncated')) {
            var note = el('p', 'sp-vnote');
            note.textContent = 'Showing the first 64 KB of ' + attr(li, 'size') + '.';
            body.appendChild(note);
          }
          return;
        }
        if (kind === 'video' || kind === 'audio') {
          var player = el(kind, 'sp-shot');
          player.controls = true;
          player.preload = 'metadata';
          player.src = path;
          if (kind === 'video') {
            player.addEventListener('loadedmetadata', function(){
              if (player.videoWidth) meta.textContent = facts(li, player.videoWidth + ' × ' + player.videoHeight);
            });
          }
          body.appendChild(player);
          return;
        }
        blank(body, kind === 'icns' ? 'macOS icon' : 'No preview for this file');
      }

      function draw(focusLi){
        drawCrumbs();
        if (state.file) drawView(); else drawList(focusLi);
      }
      function goTo(ul){
        var was = state.file, came = state.folder;
        state.file = null; state.folder = ul;
        // Backing out lands on what we came from, so the reader keeps their place.
        var child = came === ul ? null : came;
        while (child && parentFolder(child) !== ul) child = parentFolder(child);
        draw(child ? child.parentElement : was);
      }
      function open(li){
        if (isDir(li)) { state.folder = li.querySelector(':scope > ul'); state.file = null; draw(); focusQuiet(area.querySelector('.sp-item')); }
        else { state.file = li; draw(); focusQuiet(view); }
      }
      function step(delta){
        var list = entries(state.folder).filter(function(x){ return !isDir(x); });
        var next = list[list.indexOf(state.file) + delta];
        if (!next) return;
        state.file = next; draw();
        focusQuiet(view);
      }
      function back(){
        var was = state.file;
        state.file = null;
        draw(was);
      }
      function up(){
        var parent = parentFolder(state.folder);
        if (parent) goTo(parent);
      }

      function moveFocus(delta){
        var list = items();
        var from = list.indexOf(document.activeElement);
        var to = from < 0 ? 0 : Math.max(0, Math.min(list.length - 1, from + delta));
        if (!list[to]) return;
        list.forEach(function(node){ node.tabIndex = -1; });
        list[to].tabIndex = 0;
        list[to].focus();
      }
      function columns(){
        var list = items();
        if (list.length < 2) return 1;
        var top = list[0].offsetTop, n = 1;
        while (n < list.length && list[n].offsetTop === top) n++;
        return n;
      }

      area.addEventListener('click', function(ev){
        var node = ev.target.closest('.sp-item');
        if (node && node.__li) open(node.__li);
      });
      files.addEventListener('keydown', function(ev){
        if (ev.target.closest('summary')) return;
        if (ev.key === 'Escape') {
          ev.preventDefault();
          if (state.file) back();
          else { details.open = false; focusQuiet(details.querySelector('summary')); }
          return;
        }
        if (state.file) {
          if (ev.key === 'ArrowLeft') { ev.preventDefault(); step(-1); }
          else if (ev.key === 'ArrowRight') { ev.preventDefault(); step(1); }
          return;
        }
        if (ev.target.closest('a, button')) return;
        var node = ev.target.closest('.sp-item');
        var grid = state.mode === 'icons';
        switch (ev.key) {
          case 'Enter': case ' ':
            if (node && node.__li) { ev.preventDefault(); open(node.__li); }
            break;
          case 'ArrowDown': ev.preventDefault(); moveFocus(grid ? columns() : 1); break;
          case 'ArrowUp': ev.preventDefault(); moveFocus(grid ? -columns() : -1); break;
          case 'ArrowRight': ev.preventDefault(); moveFocus(1); break;
          case 'ArrowLeft': ev.preventDefault(); moveFocus(-1); break;
          case 'Home': ev.preventDefault(); moveFocus(-items().length); break;
          case 'End': ev.preventDefault(); moveFocus(items().length); break;
          case 'Backspace': ev.preventDefault(); up(); break;
        }
      });
      draw();
    });
  }

  function setupCompare(){
    document.querySelectorAll('stimma-compare[mode="slider"]').forEach(function(el){
      var wrap = el.querySelector('.sp-cmp');
      if (!wrap) return;
      var imgs = wrap.querySelectorAll('img');
      if (imgs.length < 2) return;
      el.classList.add('sp-slider');
      var range = document.createElement('input');
      range.type = 'range'; range.min = 0; range.max = 100; range.value = 50;
      range.setAttribute('aria-label', 'Compare');
      function apply(){ el.style.setProperty('--sp-split', range.value + '%'); }
      function size(){ el.style.setProperty('--sp-w', wrap.clientWidth + 'px'); }
      range.addEventListener('input', apply);
      window.addEventListener('resize', size);
      imgs[1].addEventListener('load', size);
      el.appendChild(range); size(); apply();
    });
  }

  ready(function(){ setupFiles(); setupCompare(); });
})();
"""


def footer(text: str = "Made with Stimma") -> str:
    """The maker's mark. Embedded, so it survives a zip on a plane."""
    label = escape(text).replace("Stimma", '</span><span class="sp-wordmark">stimma</span><span>')
    return (
        f'<p class="sp-footer">{LOGO_SVG}'
        f'<span class="sp-brand"><span>{label}</span></span></p>'
    )


# Expansion ------------------------------------------------------------------

_TAG_RE_TEMPLATE = r"<{tag}\b(?P<attrs>[^>]*?)(?:/>|>(?P<inner>.*?)</{tag}>)"
_ATTR_RE = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'=<>`]+)))?')


def _parse_attrs(text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(text or ""):
        name = m.group(1)
        value = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        attrs[name.lower()] = "" if value is None else value
    return attrs


def _attr_str(attrs: dict[str, str]) -> str:
    return "".join(f' {k}="{htmllib.escape(v, quote=True)}"' for k, v in attrs.items())


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _media_markup(path: str, *, alt: str = "", caption: str = "") -> str:
    ext = Path(path).suffix.lower()
    src = htmllib.escape(path, quote=True)
    if ext in VIDEO_EXTS:
        body = f'<video controls preload="metadata" src="{src}"></video>'
    elif ext in IMAGE_EXTS:
        body = f'<img src="{src}" alt="{htmllib.escape(alt, quote=True)}" loading="lazy">'
    else:
        body = f'<a href="{src}" download>{htmllib.escape(Path(path).name)}</a>'
    if caption:
        body += f'<div class="sp-caption">{htmllib.escape(caption)}</div>'
    return body


def _tree(entries: list[dict[str, Any]], root: str) -> dict[str, Any]:
    """Nest flat file entries under ``root`` into {name: {..}} folders."""
    tree: dict[str, Any] = {}
    for entry in entries:
        rel = entry["path"][len(root):] if root and entry["path"].startswith(root) else entry["path"]
        parts = rel.split("/")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {"__dir__": True})
        node[parts[-1]] = {"__file__": entry}
    return tree


_ICON_DOWNLOAD = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>'
)
_ICON_ARCHIVE = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M3 7h18M4 7v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7M3 7l1.6-3h14.8L21 7M10 12h4"/></svg>'
)


_CARET = '<span class="sp-caret"><svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg></span>'
_GLYPH_FOLDER = ('<span class="sp-glyph"><svg viewBox="0 0 24 24">'
                 '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
                 '</svg></span>')
_GLYPH_FILE = ('<span class="sp-glyph"><svg viewBox="0 0 24 24">'
               '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
               '<path d="M14 3v5h5"/></svg></span>')

# What the row can show as a thumbnail: the browser draws these itself.
_PREVIEWABLE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}
_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
# Anything a person would open in a text editor. A package is full of these —
# Contents.json, a manifest, a readme — and they are the files the engineer
# integrating the work actually needs to read.
_TEXT_EXTS = {
    ".json", ".webmanifest", ".txt", ".md", ".markdown", ".xml", ".html", ".htm",
    ".css", ".js", ".mjs", ".ts", ".plist", ".tres", ".tscn", ".yaml", ".yml",
    ".csv", ".tsv", ".toml", ".ini", ".cfg", ".conf", ".svg", ".srt", ".vtt",
    ".strings", ".gitignore", ".log", ".sql",
}
# A viewer shows a slab, not a whole book: past this the page pays for bytes
# nobody reads. The rest of the file is one download away.
TEXT_INLINE_MAX = 64 * 1024


def _file_kind(name: str) -> str:
    """Which viewer a file gets. Extension only — the cover is written once."""
    ext = Path(name).suffix.lower()
    if ext == ".svg":
        return "svg"
    if ext == ".icns":
        return "icns"
    if ext in _RASTER_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _TEXT_EXTS:
        return "text"
    return "other"


def _download_href(path: str) -> str:
    sep = "&" if "?" in path else "?"
    return htmllib.escape(f"{path}{sep}download=1", quote=True)


def _inline_text(bundle_dir: Optional[Path], rel: str) -> Optional[tuple[str, bool]]:
    """The file's text, for embedding in the row. ``(text, truncated)`` or None.

    A cover is opened from a double-clicked file as often as from a server, and
    there ``fetch()`` of a sibling file is blocked by every browser — so the
    text has to travel inside the page or not at all.
    """
    if bundle_dir is None:
        return None
    base = Path(bundle_dir)
    target = base / rel
    try:
        target.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return None
    try:
        if not target.is_file():
            return None
        raw = target.read_bytes()[: TEXT_INLINE_MAX + 1]
    except OSError:
        return None
    truncated = len(raw) > TEXT_INLINE_MAX
    raw = raw[:TEXT_INLINE_MAX]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        if not truncated:
            return None  # binary wearing a text extension
        text = raw.decode("utf-8", errors="ignore")
    return text, truncated


def _source_script(text: str) -> str:
    """Text as an inert child of the row.

    ``</`` and ``<!--`` are the only sequences that can end or confuse script
    data, so they are the only ones escaped; the viewer puts them back, which
    keeps a file's bytes intact through the round trip.
    """
    payload = text.replace("</", "<\\/").replace("<!--", "<\\!--")
    return f'<script type="text/plain" class="sp-src">{payload}</script>'


def _render_tree(
    node: dict[str, Any],
    prefix: str,
    depth: int = 0,
    bundle_dir: Optional[Path] = None,
) -> str:
    """The static tree: folders first, then files, each a row of facts.

    This is what a reader with scripts off sees, and the data the scripted
    file manager is built from — every row carries what its viewer needs.
    """
    items = sorted(node.items(), key=lambda kv: (not isinstance(kv[1], dict) or "__file__" in kv[1], kv[0].lower()))
    out = ["<ul>"]
    for name, child in items:
        if name in ("__dir__", "__file__"):
            continue
        safe = htmllib.escape(name)
        quoted = htmllib.escape(name, quote=True)
        if "__file__" in child:
            entry = child["__file__"]
            path = entry["path"]
            size = int(entry.get("size") or 0)
            kind = _file_kind(name)
            src_path = htmllib.escape(path, quote=True)
            lead = (
                f'<img class="sp-thumb" src="{src_path}" alt="" loading="lazy">'
                if Path(name).suffix.lower() in _PREVIEWABLE else _GLYPH_FILE
            )
            body = ""
            extra = ""
            if kind in ("text", "svg"):
                inlined = _inline_text(bundle_dir, path)
                if inlined is None and kind == "text" and bundle_dir is not None:
                    kind = "other"  # binary wearing a text extension
                elif inlined is not None:
                    body = _source_script(inlined[0])
                    if inlined[1]:
                        extra = ' data-truncated="1"'
            out.append(
                f'<li class="sp-file" data-kind="{kind}" data-path="{src_path}"'
                f' data-name="{quoted}" data-bytes="{size}"'
                f' data-size="{human_size(size)}"{extra}>'
                f'<div class="sp-row">{lead}<span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{human_size(size)}</span>'
                f'<a class="sp-dl" href="{_download_href(path)}" download'
                f' aria-label="Download {quoted}">{_ICON_DOWNLOAD}</a></div>{body}</li>'
            )
        else:
            count = _count_files(child)
            out.append(
                f'<li class="sp-dir" data-kind="folder" data-name="{quoted}" data-count="{count}">'
                f'<div class="sp-row">{_GLYPH_FOLDER}<span class="sp-name">{safe}</span>'
                f'<span class="sp-meta">{count}</span></div>'
                f'{_render_tree(child, prefix + name + "/", depth + 1, bundle_dir)}</li>'
            )
    out.append("</ul>")
    return "".join(out)


def _count_files(node: dict[str, Any]) -> int:
    total = 0
    for name, child in node.items():
        if name in ("__dir__", "__file__") or not isinstance(child, dict):
            continue
        total += 1 if "__file__" in child else _count_files(child)
    return total


def _browser_markup(tree: str, root_label: str = "") -> str:
    """The button, and the browser it opens into.

    ``<details>`` rather than a scripted toggle: closed is the resting state,
    and a reader with scripts off can still open it and read the tree.
    """
    root = f' data-root="{htmllib.escape(root_label, quote=True)}"' if root_label else ""
    return (
        '<details class="sp-files"><summary class="sp-files-top">'
        '<span class="sp-browse">View contents</span>'
        '</summary>'
        f'<div class="sp-browser"><div class="sp-tree"{root}>{tree}</div></div></details>'
    )


def _files_markup(manifest: dict[str, Any], ref: str, bundle_dir: Optional[Path] = None) -> str:
    run = run_by_id(manifest, ref)
    if run is not None:
        root = (run.get("root") or "").rstrip("/")
        entries = run.get("files") or []
        tree = _render_tree(_tree(entries, root + "/"), root + "/", bundle_dir=bundle_dir)
        return _browser_markup(tree, root_label=f"{root}.zip")

    sections = [{"path": m["path"], "size": m.get("size", 0)} for m in manifest.get("members") or []]
    for run in manifest.get("runs") or []:
        sections.extend(run.get("files") or [])
    for extra in manifest.get("extras") or []:
        sections.append({"path": extra["path"], "size": extra.get("size", 0)})
    tree = _render_tree(_tree(sections, ""), "", bundle_dir=bundle_dir)
    return _browser_markup(tree)


def _resolve_path(manifest: dict[str, Any], ref: str) -> Optional[str]:
    resolved = resolve_ref(manifest, ref)
    if resolved is None or resolved["kind"] == "run":
        return None
    return resolved["path"]


def _appearance_body(source: str) -> str:
    """Group direct light/dark children without changing their own layout.

    Keep original HTML slices, including SVG, entities and authored styles.
    Multiple children in the same appearance retain their document order.
    """
    class Children(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.depth = 0
            self.start = self.cursor = 0
            self.mode = None
            self.groups = {"light": [], "dark": [], None: []}
            self.offsets = [0]
            for line in source.splitlines(keepends=True):
                self.offsets.append(self.offsets[-1] + len(line))

        def position(self):
            line, column = self.getpos()
            return self.offsets[line - 1] + column

        def finish(self, end):
            self.groups[None].append(source[self.cursor:self.start])
            self.groups[self.mode].append(source[self.start:end])
            self.cursor = end

        def handle_starttag(self, tag, attrs):
            if self.depth == 0:
                self.start = self.position()
                when = dict(attrs).get("when")
                self.mode = when if when in ("light", "dark") else None
            if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input",
                       "link", "meta", "param", "source", "track", "wbr"}:
                if self.depth == 0:
                    self.finish(self.position() + len(self.get_starttag_text()))
            else:
                self.depth += 1

        def handle_startendtag(self, tag, attrs):
            if self.depth == 0:
                self.start = self.position()
                when = dict(attrs).get("when")
                self.mode = when if when in ("light", "dark") else None
                self.finish(self.position() + len(self.get_starttag_text()))

        def handle_endtag(self, tag):
            if self.depth:
                self.depth -= 1
                if not self.depth:
                    self.finish(source.index(">", self.position()) + 1)

    parser = Children()
    parser.feed(source)
    parser.close()
    parser.groups[None].append(source[parser.cursor:])
    common = "".join(parser.groups[None])
    panels = "".join(
        f'<div class="sp-appearance-panel" data-when="{mode}">{"".join(parser.groups[mode])}</div>'
        for mode in ("light", "dark")
    )
    return common + f'<div class="sp-appearance-body">{panels}</div>'


def expand_kit_elements(
    manifest: dict[str, Any],
    body: str,
    bundle_dir: Optional[Path] = None,
) -> tuple[str, list[str]]:
    """Expand empty kit elements into static HTML. Returns (html, problems).

    ``bundle_dir`` is where the package's files are on disk while it is being
    written. With it, text files travel inside the page and the file browser
    can show them offline; without it (a cover rendered from a manifest alone)
    the rows simply carry no source.
    """
    problems: list[str] = []
    counters: dict[str, int] = {}
    seen_ids: set[str] = set()

    def next_id(tag: str, ref: str) -> str:
        counters[tag] = counters.get(tag, 0) + 1
        base = re.sub(r"[^a-z0-9-]+", "-", (ref or tag).lower()).strip("-") or tag
        candidate = f"{base}-{counters[tag]}"
        while candidate in seen_ids:
            counters[tag] += 1
            candidate = f"{base}-{counters[tag]}"
        return candidate

    def register_id(attrs: dict[str, str], tag: str) -> None:
        el_id = attrs.get("id")
        if el_id:
            if el_id in seen_ids:
                problems.append(f"duplicate id {el_id!r} on <{tag}>")
            seen_ids.add(el_id)
        else:
            attrs["id"] = next_id(tag, attrs.get("ref", ""))
            seen_ids.add(attrs["id"])

    def media_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        register_id(attrs, "stimma-media")
        ref = attrs.get("ref", "")
        path = _resolve_path(manifest, ref)
        if path is None:
            problems.append(f"<stimma-media ref=\"{ref}\"> does not resolve to a member or file in this package")
            return f"<stimma-media{_attr_str(attrs)}>{inner}</stimma-media>"
        attrs["data-path"] = path
        if inner:
            return f"<stimma-media{_attr_str(attrs)}>{inner}</stimma-media>"
        member = member_by_id(manifest, ref)
        alt = attrs.get("alt") or (member.get("name") if member else Path(path).name)
        px = attrs.get("size")
        caption = attrs.get("caption", "")
        if px and px.isdigit():
            # A real-size preview: the browser must not scale it.
            inner_html = (
                f'<img src="{htmllib.escape(path, quote=True)}" width="{px}" height="{px}"'
                f' alt="{htmllib.escape(alt or "", quote=True)}">'
            )
            if not caption:
                caption = px
            inner_html += f'<div class="sp-caption">{htmllib.escape(str(caption))}</div>'
            return f"<stimma-media{_attr_str(attrs)}>{inner_html}</stimma-media>"
        return f"<stimma-media{_attr_str(attrs)}>{_media_markup(path, alt=alt, caption=caption)}</stimma-media>"

    def files_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        register_id(attrs, "stimma-files")
        ref = attrs.get("ref", "")
        if ref and run_by_id(manifest, ref) is None and ref != "package":
            problems.append(f"<stimma-files ref=\"{ref}\"> does not name a run in this package (use a run id or omit ref)")
            return f"<stimma-files{_attr_str(attrs)}>{inner}</stimma-files>"
        if inner:
            return f"<stimma-files{_attr_str(attrs)}>{inner}</stimma-files>"
        return f"<stimma-files{_attr_str(attrs)}>{_files_markup(manifest, ref, bundle_dir)}</stimma-files>"

    def compare_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        register_id(attrs, "stimma-compare")
        if inner:
            return f"<stimma-compare{_attr_str(attrs)}>{inner}</stimma-compare>"
        a, bref = attrs.get("a", ""), attrs.get("b", "")
        pa, pb = _resolve_path(manifest, a), _resolve_path(manifest, bref)
        if pa is None or pb is None:
            problems.append(f"<stimma-compare a=\"{a}\" b=\"{bref}\"> has an unresolved side")
            return f"<stimma-compare{_attr_str(attrs)}></stimma-compare>"
        la = htmllib.escape(attrs.get("label-a", "A"))
        lb = htmllib.escape(attrs.get("label-b", "B"))
        body = (
            f'<div class="sp-cmp"><figure>{_media_markup(pa)}<figcaption>{la}</figcaption></figure>'
            f'<figure>{_media_markup(pb)}<figcaption>{lb}</figcaption></figure></div>'
        )
        return f"<stimma-compare{_attr_str(attrs)}>{body}</stimma-compare>"

    def appearance_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = m.group("inner") or ""
        register_id(attrs, "stimma-appearance")
        label = attrs.pop("label", "")
        name = attrs["id"]
        switch = (
            f'<div class="sp-seg" role="radiogroup" aria-label="Appearance">'
            f'<label class="sp-light"><input type="radio" name="{htmllib.escape(name, quote=True)}" class="sp-pick-light">Light</label>'
            f'<label class="sp-dark"><input type="radio" name="{htmllib.escape(name, quote=True)}" class="sp-pick-dark">Dark</label>'
            f'</div>'
        )
        head = (
            f'<div class="sp-appearance-head"><p class="sp-label">{htmllib.escape(label)}</p>{switch}</div>'
            if label else switch
        )
        return f"<stimma-appearance{_attr_str(attrs)}>{head}{_appearance_body(inner)}</stimma-appearance>"

    def grid_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        register_id(attrs, "stimma-grid")
        return f"<stimma-grid{_attr_str(attrs)}>"

    def section_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = m.group("inner") or ""
        label = attrs.pop("label", "")
        layout = attrs.get("layout")
        details = []

        def take_details(match):
            grid_attrs = _parse_attrs(match.group("attrs"))
            if grid_attrs.get("slot") != "details":
                return match.group(0)
            details.append(match.group(0))
            return ""

        # Extract native disclosures before their nested grids/appearance groups.
        inner = re.sub(_TAG_RE_TEMPLATE.format(tag="details"), take_details, inner, flags=re.IGNORECASE | re.DOTALL)
        disclosure = bool(details)
        inner = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-grid"), take_details, inner, flags=re.IGNORECASE | re.DOTALL)
        if len(details) > 1:
            problems.append(f"Section {label!r}: use one details grid or disclosure")
        if details and not disclosure and len(re.findall(r"<stimma-media\b", details[0], re.IGNORECASE)) > 2:
            problems.append(f"Section {label!r}: use one details grid with at most two media items")
        if layout is not None and layout not in ("single", "pair", "stack"):
            problems.append(f"Section {label!r}: layout must be single, pair or stack")
        if layout in ("single", "pair", "stack"):
            count = len(re.findall(r"<stimma-media\b", inner, re.IGNORECASE))
            expected = 1 if layout == "single" else 2
            if count != expected:
                problems.append(f"Section {label!r}: layout={layout} needs {expected} media items; split crowded groups into separate sections")
        if "page" in attrs and len(re.findall(r"<stimma-appearance\b", inner, re.IGNORECASE)) > 1:
            problems.append(f"Section {label!r}: use one appearance group per PDF page section")
        if "page" in attrs or layout:
            register_id(attrs, "stimma-section")
            inner = f'<div class="sp-section-body">{inner}</div>'
        if details:
            detail_class = "sp-section-details sp-section-disclosure" if disclosure else "sp-section-details"
            inner += f'<div class="{detail_class}">{"".join(details)}</div>'
        head = f'<p class="sp-label">{htmllib.escape(label)}</p>' if label else ""
        return f"<stimma-section{_attr_str(attrs)}>{head}{inner}</stimma-section>"

    def column_sub(m: re.Match) -> str:
        attrs = _parse_attrs(m.group("attrs"))
        inner = (m.group("inner") or "").strip()
        title = attrs.pop("title", "")
        head = f"<h3>{htmllib.escape(title)}</h3>" if title else ""
        return f"<stimma-column{_attr_str(attrs)}>{head}<p>{inner}</p></stimma-column>"

    flags = re.IGNORECASE | re.DOTALL
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-column"), column_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-section"), section_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-media"), media_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-files"), files_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-compare"), compare_sub, body, flags=flags)
    body = re.sub(_TAG_RE_TEMPLATE.format(tag="stimma-appearance"), appearance_sub, body, flags=flags)
    body = re.sub(r"<stimma-grid\b(?P<attrs>[^>]*)>", grid_sub, body, flags=flags)
    for tag in RESERVED_COMPONENTS:
        for m in re.finditer(rf"<{tag}\b(?P<attrs>[^>]*)>", body, flags=flags):
            attrs = _parse_attrs(m.group("attrs"))
            if attrs.get("id"):
                if attrs["id"] in seen_ids:
                    problems.append(f"duplicate id {attrs['id']!r} on <{tag}>")
                seen_ids.add(attrs["id"])
    return body, problems
