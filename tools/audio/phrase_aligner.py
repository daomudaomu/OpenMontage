"""Phrase-to-time aligner for acoustically-grounded subtitles.

Turns word/boundary tokens from a TTS engine into an SRT whose cue timestamps
come from the *audio*, not from a character-count interpolation.

Why this exists
---------------
`subtitle_gen` assumes it is handed word-level timestamps from an ASR pass
(`transcriber`), which is the documented path in `skills/core/subtitle-sync.md`.
That path needs `faster_whisper` and a second pass over the audio. Edge TTS can
emit timings for free during synthesis — but its tokens are *not* words for
Chinese: `它不接管方向盘` is tokenised as `它/不/接/管方/向盘`.

The workaround (measured, see `docs/USAGE_NOTES_zh-CN.md` §8): rebuild a
**per-character time axis** by splitting each token's duration evenly across its
characters, then sequentially match each target phrase against that character
stream. Matching 40/40 real cues this way reproduces the hand-tuned reference to
a median error of 0.05 s, versus 0.55 ms residual for pure interpolation — i.e.
the timestamps carry real acoustic information.

`subtitle_gen` is also unusable for Chinese even with correct timings: it joins
words with `" ".join`, which renders `车 道 偏 离 预 警`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolStability,
    ToolTier,
)


# Sentence-ending punctuation: a cue boundary that must be respected.
_HARD_PUNCT = "。！？!?；;"
# Clause punctuation: the primary cue boundary in natural Chinese subtitling.
_SOFT_PUNCT = "，、：,:"
# Dash/ellipsis behave like a sentence break for captioning purposes.
_DASH_PUNCT = "—…"

# Everything dropped from the rendered cue text. The project's art direction
# requires punctuation-free Chinese subtitles (see
# `projects/ldws-teaching/art-direction.md` §字幕规则), and dropping it here is
# also what makes tolerant matching work.
_DROP_PUNCT = (
    _HARD_PUNCT
    + _SOFT_PUNCT
    + _DASH_PUNCT
    + "「」『』（）()《》〈〉【】〔〕“”‘’\"'·、"
)

# A clause longer than this is force-split: 21 CJK chars already overflows a
# 1920px frame at the sizes this project uses.
_HARD_MAX_CHARS = 24


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF      # CJK unified ideographs
        or 0x3400 <= cp <= 0x4DBF   # extension A
        or 0xF900 <= cp <= 0xFAFF   # compatibility ideographs
        or 0x3040 <= cp <= 0x30FF   # kana (present in mixed Chinese text)
    )


def _is_droppable(ch: str) -> bool:
    return ch.isspace() or ch in _DROP_PUNCT


def _display_width(text: str) -> int:
    """Approximate rendered column count: CJK and fullwidth forms count double."""
    width = 0
    for ch in text:
        cp = ord(ch)
        if _is_cjk(ch) or 0xFF01 <= cp <= 0xFF60 or 0x3000 <= cp <= 0x303F:
            width += 2
        else:
            width += 1
    return width


def normalise(text: str) -> str:
    """Strip whitespace and punctuation — the form used for matching.

    Latin/digit runs survive intact so `LDWS`, `ADAS`, `Canny` stay matchable.
    """
    return "".join(ch for ch in text if not _is_droppable(ch))


def display_text(text: str) -> str:
    """Punctuation-free cue text with CJK<->Latin spacing restored.

    `是智能网联汽车 ADAS 中的一项预警功能` round-trips to itself; a source with
    no spaces (`是智能网联汽车ADAS中的一项预警功能`) gains them, because unspaced
    CJK/Latin runs read as a typo in the rendered caption.
    """
    out: list[str] = []
    for ch in text:
        if _is_droppable(ch):
            continue
        if out and _is_cjk(out[-1]) != _is_cjk(ch):
            out.append(" ")
        out.append(ch)
    return "".join(out)


class PhraseAligner(BaseTool):
    name = "phrase_aligner"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "subtitle"
    provider = "openmontage"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC

    dependencies = []  # pure Python
    install_instructions = "No external dependencies required."
    agent_skills = ["edge-tts"]

    capabilities = ["align_phrases_to_audio", "generate_srt"]

    input_schema = {
        "type": "object",
        "required": ["tokens", "phrases"],
        "properties": {
            "tokens": {
                "type": "array",
                "description": (
                    "Boundary tokens with absolute seconds, as returned by "
                    "edge_tts: [{'text': str, 'start': float, 'end': float}, ...]. "
                    "Also accepts {'offset'/'duration'} in seconds or 100-ns ticks."
                ),
            },
            "phrases": {
                "type": "array",
                "description": (
                    "Cue texts in spoken order. Either plain strings (timing is "
                    "fully acoustic) or objects {'text', 'start'?, 'end'?} where a "
                    "supplied start/end overrides the matched value — this is the "
                    "manual-tuning escape hatch."
                ),
            },
            "output_path": {"type": "string"},
            "format": {"type": "string", "enum": ["srt", "json"], "default": "srt"},
            "boundary_mode": {
                "type": "string",
                "enum": ["butt", "onset"],
                "default": "butt",
                "description": (
                    "butt: each cue ends exactly when the next begins (no gaps, no "
                    "flicker — what the hand-tuned LDWS reference does). onset: each "
                    "cue ends at its own last acoustic token, leaving the natural "
                    "pause uncovered."
                ),
            },
            "start_offset": {
                "type": "number",
                "default": 0.0,
                "description": (
                    "Lead-in added to every matched start, in seconds. 0 by "
                    "default: edge-tts rarely places the first audio sample before "
                    "the boundary offset, so a positive lead-in only makes cues "
                    "appear early. Raise it if your renderer lags audio."
                ),
            },
            "min_duration": {
                "type": "number",
                "default": 0.3,
                "description": "Floor on cue length so a cue is always readable.",
            },
            "max_chars_per_line": {"type": "integer", "default": 20},
            "audio_end": {
                "type": "number",
                "description": (
                    "Optional total audio duration in seconds. The final cue is "
                    "clamped to this so a subtitle can never outlive the audio."
                ),
            },
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=64, vram_mb=0, disk_mb=5)
    idempotency_key_fields = ["tokens", "phrases", "boundary_mode", "start_offset"]
    side_effects = ["writes subtitle file to output_path"]
    user_visible_verification = [
        "Play the video and confirm each cue appears as its line is spoken",
    ]

    # ---------------------------------------------------------------- public

    @staticmethod
    def segment_text(text: str, max_chars: int = _HARD_MAX_CHARS) -> list[str]:
        """Split narration into subtitle cues on punctuation.

        Punctuation-delimited clauses are the cue unit — measured against the
        hand-tuned LDWS reference, clause splitting reproduces its structure
        exactly (40/40 cues) whereas a length-based packer merges unrelated
        sentences (`开车时车辆突然向车道线偏移而你却没有察觉`).

        A clause longer than `max_chars` is split near its midpoint, so the
        result stays renderable.
        """
        cues: list[str] = []
        buf = ""
        for ch in text:
            if ch in _HARD_PUNCT or ch in _SOFT_PUNCT or ch in _DASH_PUNCT:
                if buf:
                    cues.append(buf)
                    buf = ""
            elif _is_droppable(ch):
                continue
            else:
                buf += ch
        if buf:
            cues.append(buf)

        out: list[str] = []
        for cue in cues:
            if max_chars > 0 and len(cue) > max_chars:
                parts = PhraseAligner._force_split(cue, max_chars)
            else:
                parts = [cue]
            # Cue text is the rendered form: no punctuation, CJK/Latin spacing
            # restored. Matching strips it again, so this is display-safe.
            out.extend(display_text(p) for p in parts if p)
        return out

    @staticmethod
    def _force_split(cue: str, max_chars: int) -> list[str]:
        parts: list[str] = []
        rest = cue
        while len(rest) > max_chars:
            cut = PhraseAligner._nearest_cjk_boundary(rest, max_chars, hi=max_chars)
            if not 0 < cut <= max_chars or cut >= len(rest):
                cut = max_chars
            parts.append(rest[:cut])
            rest = rest[cut:]
        if rest:
            parts.append(rest)
        return parts

    @staticmethod
    def _nearest_cjk_boundary(text: str, target: int, hi: int | None = None) -> int:
        """Index near `target` that does not split a CJK run from a Latin run.

        `hi` bounds the search so a forced split can never produce a piece
        longer than the caller's budget.
        """
        upper = len(text) - 1 if hi is None else min(hi, len(text) - 1)
        for delta in range(0, len(text)):
            for cand in (target + delta, target - delta):
                if 0 < cand <= upper and _is_cjk(text[cand - 1]) == _is_cjk(text[cand]):
                    return cand
        return target

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        try:
            tokens = self._normalise_tokens(inputs["tokens"])
        except Exception as exc:
            return ToolResult(success=False, error=f"Invalid tokens: {exc}")

        phrases = inputs["phrases"]
        if not phrases:
            return ToolResult(success=False, error="phrases must not be empty")

        if not tokens:
            return ToolResult(
                success=False,
                error=(
                    "No boundary tokens were supplied. Edge TTS only emits them "
                    "when constructed with boundary='WordBoundary'."
                ),
            )

        timeline = self._char_timeline(tokens)
        if not timeline.chars:
            return ToolResult(
                success=False,
                error="Boundary tokens contained no matchable characters",
            )

        cues = self._align(
            timeline=timeline,
            phrases=phrases,
            boundary_mode=inputs.get("boundary_mode", "butt"),
            start_offset=float(inputs.get("start_offset", 0.0)),
            min_duration=float(inputs.get("min_duration", 0.3)),
            audio_end=inputs.get("audio_end"),
        )

        fmt = inputs.get("format", "srt")
        max_chars_per_line = int(inputs.get("max_chars_per_line", 20))
        if fmt == "json":
            content = json.dumps({"cues": cues}, indent=2, ensure_ascii=False)
            ext = ".json"
        elif fmt == "srt":
            content = self._render_srt(cues, max_chars_per_line)
            ext = ".srt"
        else:
            return ToolResult(success=False, error=f"Unknown format: {fmt}")

        output_path = inputs.get("output_path") or f"subtitles{ext}"
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")

        unmatched = [c["index"] for c in cues if c.get("estimated")]
        return ToolResult(
            success=True,
            data={
                "format": fmt,
                "cue_count": len(cues),
                "output": str(out),
                "token_count": len(tokens),
                "char_count": len(timeline.chars),
                "unmatched_count": len(unmatched),
                "unmatched_indices": unmatched,
                "audio_span_seconds": round(
                    timeline.span_end - timeline.span_start, 3
                ),
                "first_cue_start": cues[0]["start"] if cues else None,
                "last_cue_end": cues[-1]["end"] if cues else None,
                "cue_source_srt": "phrase_aligner",
            },
            artifacts=[str(out)],
            duration_seconds=round(time.time() - start, 2),
        )

    # ------------------------------------------------------------- internals

    class _Timeline:
        __slots__ = ("chars", "starts", "ends", "norm", "norm_index", "span_start", "span_end")

        def __init__(self) -> None:
            self.chars: list[str] = []
            self.starts: list[float] = []
            self.ends: list[float] = []
            # Punctuation/space-free character stream plus, for each of its
            # positions, the index back into `chars`.
            self.norm: str = ""
            self.norm_index: list[int] = []
            self.span_start: float = 0.0
            self.span_end: float = 0.0

    @staticmethod
    def _normalise_tokens(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ticks = any(
            isinstance(t, dict) and ("offset" in t or "duration" in t) for t in raw
        )
        out: list[dict[str, Any]] = []
        for t in raw:
            if not isinstance(t, dict):
                raise ValueError(f"token must be an object, got {type(t).__name__}")
            text = t.get("text")
            if text is None:
                raise ValueError("token is missing 'text'")
            if "start" in t and "end" in t:
                s, e = float(t["start"]), float(t["end"])
            elif "offset" in t:
                o, d = float(t["offset"]), float(t.get("duration", 0))
                if ticks:
                    o, d = o / 10_000_000, d / 10_000_000
                s, e = o, o + d
            else:
                raise ValueError("token needs start/end or offset/duration")
            if e < s:
                raise ValueError(f"token {text!r} ends before it starts")
            out.append({"text": text, "start": s, "end": e})
        out.sort(key=lambda x: x["start"])
        return out

    @classmethod
    def _char_timeline(cls, tokens: list[dict[str, Any]]) -> "PhraseAligner._Timeline":
        """Split every token's duration evenly across its characters.

        This is the step that neutralises edge-tts's wrong Chinese tokenisation:
        `管方` and `向盘` are meaningless as words, but as *character spans* they
        still place each character at the right time.
        """
        tl = cls._Timeline()
        for tok in tokens:
            text = tok["text"]
            n = len(text)
            if n == 0:
                continue
            dur = tok["end"] - tok["start"]
            for j, ch in enumerate(text):
                tl.chars.append(ch)
                tl.starts.append(tok["start"] + dur * j / n)
                tl.ends.append(tok["start"] + dur * (j + 1) / n)
        if not tl.chars:
            return tl
        tl.span_start = tl.starts[0]
        tl.span_end = tl.ends[-1]
        tl.norm = "".join(c for c in tl.chars if not _is_droppable(c))
        tl.norm_index = [i for i, c in enumerate(tl.chars) if not _is_droppable(c)]
        return tl

    @staticmethod
    def _align(
        timeline: "PhraseAligner._Timeline",
        phrases: list[Any],
        boundary_mode: str,
        start_offset: float,
        min_duration: float,
        audio_end: float | None,
    ) -> list[dict[str, Any]]:
        cues: list[dict[str, Any]] = []
        cursor = 0

        for i, phrase in enumerate(phrases):
            if isinstance(phrase, dict):
                raw_text = phrase.get("text", "")
                manual_start = phrase.get("start")
                manual_end = phrase.get("end")
            else:
                raw_text = str(phrase)
                manual_start = manual_end = None

            target = normalise(raw_text)
            if not target:
                continue

            found = timeline.norm.find(target, cursor)
            estimated = False
            if found < 0:
                # Fall back to an unanchored search before giving up: a dropped
                # or misheard clause should cost one cue, not every cue after it.
                found = timeline.norm.find(target)
            if found < 0:
                estimated = True
                s, e = PhraseAligner._interpolate(
                    timeline, cues, i, len(phrases), len(target)
                )
            else:
                first = timeline.norm_index[found]
                last = timeline.norm_index[found + len(target) - 1]
                s, e = timeline.starts[first], timeline.ends[last]
                cursor = found + len(target)

            if manual_start is not None:
                s = float(manual_start)
            if manual_end is not None:
                e = float(manual_end)

            cues.append(
                {
                    "index": i + 1,
                    "start": max(0.0, s + (0.0 if estimated else start_offset)),
                    "end": e,
                    "text": display_text(raw_text),
                    "estimated": estimated,
                }
            )

        # Butt-join: each cue runs until the next one starts. This is what the
        # hand-tuned reference does, and it removes both flicker (a 1-frame gap)
        # and overlap (two cues visible at once).
        if boundary_mode == "butt":
            for i in range(len(cues) - 1):
                cues[i]["end"] = cues[i + 1]["start"]
        elif boundary_mode != "onset":
            raise ValueError(f"Unknown boundary_mode: {boundary_mode}")

        for i, cue in enumerate(cues):
            manual = isinstance(phrases[cue["index"] - 1], dict)
            if manual and phrases[cue["index"] - 1].get("end") is not None:
                continue
            if cue["end"] - cue["start"] < min_duration:
                cue["end"] = cue["start"] + min_duration
            if audio_end is not None:
                cue["end"] = min(cue["end"], float(audio_end))
            cue["start"] = round(cue["start"], 3)
            cue["end"] = round(max(cue["end"], cue["start"] + 0.05), 3)

        for i, cue in enumerate(cues):
            cue["index"] = i + 1
        return cues

    @staticmethod
    def _interpolate(
        timeline: "PhraseAligner._Timeline",
        done: list[dict[str, Any]],
        i: int,
        total: int,
        length: int,
    ) -> tuple[float, float]:
        """Last-resort placement for an unmatched phrase.

        Uses the neighbouring matched cues when they exist, otherwise spreads
        the phrase across the audio span proportionally. Marked `estimated`.
        """
        if done:
            s = done[-1]["end"]
        else:
            s = timeline.span_start
        remaining = total - i
        span = max(0.0, timeline.span_end - s)
        dur = span / remaining if remaining else 0.0
        if dur <= 0:
            dur = timeline.span_end - timeline.span_start
        return s, s + max(dur, 0.05 * length)

    @staticmethod
    def _wrap(text: str, max_chars: int) -> list[str]:
        """Wrap on *display width*, not character count.

        `是智能网联汽车 ADAS 中的一项预警功能` is 21 characters but only 36
        columns wide (CJK counts double, Latin single) — so a "20 汉字" budget
        keeps it on one line, matching the hand-tuned reference. Counting
        characters instead would split it for no visual reason.
        """
        if max_chars <= 0:
            return [text]
        budget = max_chars * 2
        if _display_width(text) <= budget:
            return [text]
        if " " in text:
            words = text.split(" ")
            lines: list[str] = []
            cur = ""
            for w in words:
                cand = f"{cur} {w}" if cur else w
                if cur and _display_width(cand) > budget:
                    lines.append(cur)
                    cur = w
                else:
                    cur = cand
            if cur:
                lines.append(cur)
            return lines
        mid = len(text) // 2
        cut = PhraseAligner._nearest_cjk_boundary(text, mid)
        return [text[:cut], text[cut:]]

    @classmethod
    def _render_srt(cls, cues: list[dict[str, Any]], max_chars_per_line: int) -> str:
        blocks: list[str] = []
        for cue in cues:
            body = "\n".join(cls._wrap(cue["text"], max_chars_per_line))
            blocks.append(
                f"{cue['index']}\n"
                f"{cls._ts_srt(cue['start'])} --> {cls._ts_srt(cue['end'])}\n"
                f"{body}"
            )
        return "\n\n".join(blocks) + "\n"

    @staticmethod
    def _hmsms(seconds: float) -> tuple[int, int, int, int]:
        total_ms = int(round(max(0.0, seconds) * 1000))
        h, rem = divmod(total_ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1_000)
        return h, m, s, ms

    @classmethod
    def _ts_srt(cls, seconds: float) -> str:
        h, m, s, ms = cls._hmsms(seconds)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


__all__ = ["PhraseAligner", "normalise", "display_text"]
