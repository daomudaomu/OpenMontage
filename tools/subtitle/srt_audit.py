"""SRT auditing primitives — real parse plus coverage/timing maths.

Why this module exists
----------------------
`video_compose._run_final_review` used to treat "an .srt file exists on disk"
as proof that subtitles were present and correctly timed, and hard-coded
``coverage_ratio = 1.0``.  Neither ``coverage_ratio`` nor
``timing_drift_detected`` had any computation anywhere in the repository, so
the LDWS ``final_review`` artifact's "subtitles pass / no drift" claim carried
no evidence at all.

This module supplies the missing maths with zero third-party dependencies (the
same posture as ``tools/audio/phrase_aligner.py``).  It deliberately contains
no policy: the caller injects the video/narration durations it already probed,
and decides what a finding means.  Everything here is a pure function of its
inputs except the ffmpeg visibility probe, which degrades to an error report
rather than raising.

Vocabulary
----------
- **cue** — one SRT block: index, start/end in seconds, text.
- **coverage** — length of the *union* of cue intervals divided by the video
  duration.  A union (not a sum) so overlapping cues cannot inflate coverage
  past 1.0.  This is the number ``coverage_ratio`` was always meant to be.
- **bottom-band ink** — fraction of near-white pixels in the lower-centre band
  of sampled frames.  Burned Chinese subtitles with a light stroke push this to
  roughly 1-3%; a frame with no burned text measures 0.0%.  It is a heuristic,
  useful as a warning, not as a gate.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "Cue",
    "parse_srt",
    "audit_srt",
    "compare_cue_grid",
    "probe_bottom_band_ink",
    "file_sha256",
    "normalise_text",
    "union_span",
]

# Matches an SRT timing line.  Millisecond field is exactly 3 digits, which is
# what strict parsers (ffmpeg's subtitles filter, VLC) require — a malformed
# `,1000` must *not* silently parse as a valid cue.
CUE_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2}),(\d{3})"
)

# Dropped when comparing declared caption text against cue text: punctuation,
# whitespace, and the BOM some editors leave behind.  Kept identical in spirit
# to `phrase_aligner.display_text` so "the same sentence" compares equal whether
# or not the author stripped punctuation.
_STRIP_RE = re.compile(r"[\s\u3000\ufeff]+")
_PUNCT_CHARS = "。！？!?；;，、：,:\u2014\u2026\u00b7\u3001\u3002\"'“”‘’（）()《》<>—-·.~～"

_CJK_RANGES = (
    (0x3040, 0x30FF),   # kana
    (0x3400, 0x4DBF),   # CJK ext A
    (0x4E00, 0x9FFF),   # CJK unified
    (0xF900, 0xFAFF),   # compatibility ideographs
    (0xFF00, 0xFFEF),   # fullwidth forms
)


def has_cjk(text: str) -> bool:
    """True if the text contains CJK/kana/fullwidth characters."""
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            return True
    return False


def normalise_text(text: str) -> str:
    """Lowercase, drop punctuation and all whitespace — the comparison form."""
    kept = "".join(ch for ch in text if ch not in _PUNCT_CHARS)
    return _STRIP_RE.sub("", kept).lower()


@dataclass(frozen=True)
class Cue:
    """One parsed SRT cue."""

    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _hmsms_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return (
        int(h) * 3600
        + int(m) * 60
        + int(s)
        + int(ms) / 1000.0
    )


def parse_srt(text: str) -> tuple[list[Cue], list[str]]:
    """Parse SRT content into cues plus a list of structural problems.

    Never raises on malformed input: a subtitle file that cannot be parsed is a
    finding to report, not an exception to swallow higher up.  Blocks whose
    timing line does not match are recorded in ``problems`` and skipped.
    """
    problems: list[str] = []
    cues: list[Cue] = []

    # Normalise newlines and split on blank lines.  Accept both LF and CRLF.
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    for block_no, block in enumerate(blocks, start=1):
        lines = [ln for ln in block.split("\n")]
        if not any(ln.strip() for ln in lines):
            continue

        # Locate the timing line rather than assuming it is line 1: a missing or
        # non-numeric cue index is common and must not hide the cue itself.
        time_idx = next(
            (i for i, ln in enumerate(lines) if CUE_TIME_RE.search(ln)), None
        )
        if time_idx is None:
            problems.append(f"block {block_no}: no parsable timing line")
            continue

        m = CUE_TIME_RE.search(lines[time_idx])
        assert m is not None  # guaranteed by the search above
        start = _hmsms_to_seconds(*m.group(1, 2, 3, 4))
        end = _hmsms_to_seconds(*m.group(5, 6, 7, 8))

        body = "\n".join(lines[time_idx + 1:]).strip()
        if not body:
            problems.append(f"block {block_no}: empty cue text")

        index_raw = lines[time_idx - 1].strip() if time_idx > 0 else ""
        try:
            index = int(index_raw)
        except ValueError:
            index = len(cues) + 1
            if index_raw:
                problems.append(
                    f"block {block_no}: cue index {index_raw!r} is not an integer"
                )

        if end <= start:
            problems.append(
                f"block {block_no}: end {end:.3f}s is not after start {start:.3f}s"
            )

        cues.append(Cue(index=index, start=start, end=end, text=body))

    if not cues:
        problems.append("no cues parsed")
    return cues, problems


def union_span(
    cues: Sequence[Cue],
    *,
    clip_start: float = 0.0,
    clip_end: float | None = None,
) -> float:
    """Total length covered by the union of cue intervals (overlaps counted once).

    Intervals are clipped to ``[clip_start, clip_end]`` before measuring.  For
    coverage that matters: a cue sitting at 999s inside a 2s video contributes
    *zero* visible time, not its full 2s duration — measuring it unclipped
    would report coverage 1.0 for subtitles that can never be seen.
    """
    if not cues:
        return 0.0
    window_end = float("inf") if clip_end is None else clip_end
    spans: list[tuple[float, float]] = []
    for cue in cues:
        lo = max(cue.start, clip_start)
        hi = min(cue.end, window_end)
        if hi > lo:
            spans.append((lo, hi))
    if not spans:
        return 0.0

    spans.sort()
    total = 0.0
    cur_start, cur_end = spans[0]
    for lo, hi in spans[1:]:
        if lo > cur_end:
            total += cur_end - cur_start
            cur_start, cur_end = lo, hi
        else:
            cur_end = max(cur_end, hi)
    total += cur_end - cur_start
    return total


def compare_cue_grid(
    cues: Sequence[Cue],
    expected: Iterable[dict[str, Any]],
    *,
    tolerance: float = 0.5,
) -> dict[str, Any]:
    """Compare an SRT cue grid against a declared caption grid.

    ``expected`` entries follow the ``edit_decisions.metadata.captions`` shape:
    ``{"word"|"text": str, "startMs": int, "endMs": int}`` (milliseconds).

    Matching is by *normalised text*, not by index: a declared sentence-level
    caption legitimately spans several finer cues, so index alignment is
    meaningless.  For each declared caption we locate its text inside the
    concatenation of all cue text and read back the start of the cue that
    begins it.  That gives the real answer to "does the caption timeline the
    project declared agree with the subtitles that were actually produced?"
    """
    entries = list(expected or [])
    result: dict[str, Any] = {
        "expected_total": len(entries),
        "expected_matched": 0,
        "expected_unmatched": [],
        "max_delta_seconds": None,
        "mean_delta_seconds": None,
        "deltas": [],
    }
    if not entries or not cues:
        return result

    concat = "".join(normalise_text(c.text) for c in cues)
    # char position -> cue index, so a match position maps back to a cue.
    char_to_cue: list[int] = []
    for i, cue in enumerate(cues):
        char_to_cue.extend([i] * len(normalise_text(cue.text)))

    deltas: list[float] = []
    unmatched: list[str] = []
    for entry in entries:
        raw = entry.get("text") or entry.get("word") or ""
        target = normalise_text(str(raw))
        if not target:
            continue
        pos = concat.find(target)
        if pos < 0 or pos >= len(char_to_cue):
            unmatched.append(str(raw)[:60])
            continue
        actual_start = cues[char_to_cue[pos]].start
        try:
            declared_start = float(entry.get("startMs", 0)) / 1000.0
        except (TypeError, ValueError):
            unmatched.append(str(raw)[:60])
            continue
        delta = actual_start - declared_start
        deltas.append(round(delta, 3))

    if deltas:
        result["expected_matched"] = len(deltas)
        result["deltas"] = deltas
        result["max_delta_seconds"] = max(abs(d) for d in deltas)
        result["mean_delta_seconds"] = round(sum(deltas) / len(deltas), 3)
        result["tolerance_seconds"] = tolerance
        result["within_tolerance"] = result["max_delta_seconds"] <= tolerance
    result["expected_unmatched"] = unmatched
    return result


def audit_srt(
    path: str | Path,
    *,
    video_duration: float | None = None,
    narration_duration: float | None = None,
    expected_captions: Iterable[dict[str, Any]] | None = None,
    drift_tolerance: float = 0.5,
    past_end_tolerance: float = 0.05,
) -> dict[str, Any]:
    """Audit one SRT file and return measurements plus findings.

    Findings are reported at two severities, structurally rather than by
    substring-matching the message text:

    - ``critical_issues`` — the subtitle file cannot describe this render
      (unparsable, cues that can never display, a different track entirely).
      A caller must refuse to ship a render whose captions are wrong.
    - ``issues`` — every finding, critical ones included, for reporting.

    Distinguishing the two matters: a cue parked past the end of the video is
    a broken deliverable, whereas a caption track that stops a few seconds
    early is worth a human's attention but not a hard failure.

    The function never raises: an unreadable or unparsable file is itself a
    finding.
    """
    srt_path = Path(path)
    report: dict[str, Any] = {
        "path": str(srt_path),
        "exists": srt_path.is_file(),
        "cue_count": 0,
        "coverage_ratio": None,
        "coverage_seconds": None,
        "first_cue_start": None,
        "last_cue_end": None,
        "trailing_gap_seconds": None,
        "format_problems": [],
        "timing_drift_detected": False,
        "critical_issues": [],
        "issues": [],
    }

    def _record(message: str, *, critical: bool) -> None:
        report["issues"].append(message)
        if critical:
            report["critical_issues"].append(message)

    if not report["exists"]:
        _record(f"Subtitle file does not exist: {srt_path}", critical=True)
        return report

    try:
        raw = srt_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        _record(f"Subtitle file is not valid UTF-8: {exc}", critical=True)
        return report
    except OSError as exc:
        _record(f"Subtitle file could not be read: {exc}", critical=True)
        return report

    cues, problems = parse_srt(raw)
    report["format_problems"] = problems
    report["cue_count"] = len(cues)
    # A malformed cue (end before start, unparsable timing) is a broken file,
    # not a style opinion.
    for problem in problems:
        _record(f"SRT format: {problem}", critical=True)
    if not cues:
        return report

    report["first_cue_start"] = round(cues[0].start, 3)
    report["last_cue_end"] = round(max(c.end for c in cues), 3)

    if video_duration and video_duration > 0:
        # Coverage counts only the portion of each cue that actually falls
        # inside the video window (see union_span) — a cue parked past the end
        # of the render must not be credited as coverage.
        span = union_span(cues, clip_start=0.0, clip_end=video_duration)
        report["coverage_seconds"] = round(span, 3)
        report["coverage_ratio"] = round(min(1.0, max(0.0, span / video_duration)), 4)
        report["trailing_gap_seconds"] = round(
            max(0.0, video_duration - report["last_cue_end"]), 3
        )

        # Any cue starting at or after the end of the video cannot be displayed,
        # no matter how the file got there. This is the check that catches a
        # stale SRT from a different cut — critical, because such a file is not
        # this render's subtitle track at all.
        outside = [
            c for c in cues if c.start >= video_duration + past_end_tolerance
        ]
        if outside:
            _record(
                f"{len(outside)} subtitle cue(s) start at or after the end of the "
                f"video ({video_duration:.3f}s); the first is cue {outside[0].index} "
                f"at {outside[0].start:.3f}s. These can never be displayed — the "
                f"subtitle file does not belong to this render.",
                critical=True,
            )
        straddling = [
            c
            for c in cues
            if c.start < video_duration + past_end_tolerance
            and c.end > video_duration + past_end_tolerance
        ]
        if straddling:
            # A cue bleeding a little past the end is normal for the final line;
            # only scream when it is badly out of range.
            overrun = straddling[-1].end - video_duration
            _record(
                f"{len(straddling)} subtitle cue(s) extend past the end of the "
                f"video ({video_duration:.3f}s); the last ends at "
                f"{straddling[-1].end:.3f}s.",
                critical=overrun > 2.0,
            )

        # Out-of-order cues make players drop or misplace text.
        for prev, cur in zip(cues, cues[1:]):
            if cur.start < prev.start - past_end_tolerance:
                _record(
                    f"Subtitle cues are out of order: cue {cur.index} starts at "
                    f"{cur.start:.3f}s, before cue {prev.index} at {prev.start:.3f}s.",
                    critical=True,
                )
                break

        # A cue grid that stops well before the video ends usually means the
        # subtitles cover only part of the narration. Worth flagging, but not a
        # reason to reject an otherwise valid render.
        if report["trailing_gap_seconds"] > 5.0 and narration_duration:
            _record(
                f"Subtitles stop {report['trailing_gap_seconds']:.1f}s before the "
                f"end of the video — check that the tail of the narration is "
                f"captioned.",
                critical=False,
            )

    if narration_duration and narration_duration > 0:
        if report["last_cue_end"] > narration_duration + past_end_tolerance:
            _record(
                f"Last subtitle cue ends at {report['last_cue_end']:.3f}s, after the "
                f"narration ends ({narration_duration:.3f}s).",
                critical=False,
            )

    grid = compare_cue_grid(
        cues, expected_captions or [], tolerance=drift_tolerance
    )
    report["caption_grid"] = grid
    if grid.get("max_delta_seconds") is not None:
        beyond = grid["max_delta_seconds"] > drift_tolerance
        report["timing_drift_detected"] = bool(beyond)
        if beyond:
            _record(
                f"Subtitle timing drifts from the caption timeline declared in "
                f"edit_decisions.metadata.captions by up to "
                f"{grid['max_delta_seconds']:.3f}s (tolerance "
                f"{drift_tolerance:.2f}s) across {grid['expected_matched']} captions.",
                critical=False,
            )
    if grid.get("expected_unmatched"):
        # Declared captions that appear nowhere in the file mean this is a
        # different subtitle track — the delivered captions are not the
        # approved ones.
        _record(
            f"{len(grid['expected_unmatched'])} declared caption(s) could not be "
            f"located in the subtitle file at all, e.g. "
            f"{grid['expected_unmatched'][0]!r} — the file appears to be a "
            f"different subtitle track.",
            critical=True,
        )

    return report


def probe_bottom_band_ink(
    video_path: str | Path,
    duration: float | None,
    *,
    samples: int = 5,
    threshold: int = 225,
    width: int = 640,
    height: int = 100,
    band_top: float = 0.80,
    band_height: float = 0.18,
    band_left: float = 0.20,
    band_width: float = 0.60,
) -> dict[str, Any]:
    """Sample the lower-centre band and measure near-white "ink" coverage.

    Burned subtitles with a light stroke measure roughly 1-3% here; a frame
    containing no burned text measures 0.0%.  The band defaults to the
    bottom-centre 60% x 18% region where subtitle text conventionally sits.

    Returns ``{"ratio_max", "ratio_mean", "ratios", "samples_taken"}`` or, when
    ffmpeg is unavailable or the video cannot be read, ``{"error": ...}``.
    The caller decides whether a low reading is a problem — bright artwork in
    the band can legitimately produce ink, and a quiet scene produces little.
    """
    video = Path(video_path)
    if not video.is_file():
        return {"error": f"video not found: {video}"}

    if duration and duration > 0:
        times = [duration * (i + 1) / (samples + 1) for i in range(samples)]
    else:
        times = [0.0]

    crop = (
        f"crop=iw*{band_width}:ih*{band_height}:"
        f"iw*{band_left}:ih*{band_top}"
    )
    vf = (
        f"{crop},scale={width}:{height},format=gray,"
        f"geq=lum='if(gt(lum(X,Y),{threshold}),255,0)'"
    )
    ratios: list[float] = []
    frame_bytes = width * height
    for t in times:
        cmd = [
            "ffmpeg", "-v", "error",
            "-ss", f"{t:.3f}",
            "-i", str(video),
            "-vf", vf,
            "-frames:v", "1",
            "-f", "rawvideo",
            "-",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=60
            )
        except FileNotFoundError:
            return {"error": "ffmpeg not found — cannot probe subtitle visibility"}
        except subprocess.TimeoutExpired:
            return {"error": "ffmpeg timed out during subtitle visibility probe"}
        if proc.returncode != 0 or not proc.stdout:
            continue
        data = proc.stdout[:frame_bytes]
        if not data:
            continue
        bright = sum(1 for b in data if b > 0)
        ratios.append(round(bright / len(data), 5))

    if not ratios:
        return {"error": "no frames could be sampled for the visibility probe"}
    return {
        "ratio_max": max(ratios),
        "ratio_mean": round(sum(ratios) / len(ratios), 5),
        "ratios": ratios,
        "samples_taken": len(ratios),
        "threshold": threshold,
        "band": {
            "top": band_top,
            "height": band_height,
            "left": band_left,
            "width": band_width,
        },
    }


def file_sha256(path: str | Path) -> str | None:
    """SHA-256 of a file's bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None
