"""Integrity tests for the committed `examples/` reference artifacts.

`projects/` is gitignored, so anything hand-tuned and unreproducible that we
want to keep long-term is copied into `examples/<slug>/` with a hash manifest.
These tests fail loudly if such a file is changed without updating its hash —
otherwise the "this is the artifact we actually shipped" claim quietly rots.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

EXAMPLES_ROOT = PROJECT_ROOT / "examples"

# Punctuation the subtitle style removes. ASCII punctuation is handled
# structurally by `_is_punct` rather than being enumerated here.
_PUNCT = set("，。、：；！？——…·「」『』（）()《》〈〉“”‘’")


def _is_punct(ch: str) -> bool:
    if ch in _PUNCT:
        return True
    # Any ASCII character that is neither a letter nor a digit counts as
    # punctuation, which covers quotes and hyphens without listing them.
    return ch.isascii() and not ch.isalnum()


def _example_dirs() -> list[Path]:
    if not EXAMPLES_ROOT.is_dir():
        return []
    return sorted(p for p in EXAMPLES_ROOT.iterdir() if p.is_dir())


def test_examples_directory_exists():
    assert EXAMPLES_ROOT.is_dir(), (
        "examples/ is missing. It holds hand-tuned artifacts that cannot be "
        "regenerated from a script (see examples/*/README.md)."
    )


@pytest.mark.parametrize("example_dir", _example_dirs(), ids=lambda p: p.name)
class TestExampleIntegrity:
    def test_has_manifest(self, example_dir: Path):
        assert (example_dir / "manifest.json").is_file(), (
            f"{example_dir.name} has no manifest.json — hashes cannot be verified"
        )

    def test_has_readme_explaining_provenance(self, example_dir: Path):
        readme = example_dir / "README.md"
        assert readme.is_file(), f"{example_dir.name} has no README.md"
        assert len(readme.read_text(encoding="utf-8")) > 200, (
            f"{example_dir.name}/README.md is too short to explain provenance"
        )

    def test_manifest_hashes_match_files(self, example_dir: Path):
        manifest = json.loads(
            (example_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest.get("files"), "manifest declares no files"

        for name, meta in manifest["files"].items():
            path = example_dir / name
            assert path.is_file(), f"{example_dir.name}/{name} listed but missing"
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == meta["sha256"], (
                f"{example_dir.name}/{name} does not match its recorded sha256. "
                f"If the change is intentional, update manifest.json."
            )
            assert path.stat().st_size == meta["bytes"], (
                f"{example_dir.name}/{name} size differs from manifest"
            )

    def test_no_unlisted_files(self, example_dir: Path):
        """Every committed example file must be accounted for in the manifest."""
        manifest = json.loads(
            (example_dir / "manifest.json").read_text(encoding="utf-8")
        )
        listed = set(manifest["files"]) | {"manifest.json", "README.md"}
        actual = {p.name for p in example_dir.iterdir() if p.is_file()}
        assert actual <= listed, (
            f"{example_dir.name} contains files absent from manifest.json: "
            f"{sorted(actual - listed)}"
        )


class TestLdwsExample:
    """The LDWS subtitles are the regression baseline for Phase 1 alignment."""

    EXAMPLE = EXAMPLES_ROOT / "ldws-teaching"

    def test_is_committed(self):
        assert (self.EXAMPLE / "narration_sync4.srt").is_file()

    def test_srt_is_well_formed(self):
        text = (self.EXAMPLE / "narration_sync4.srt").read_text(encoding="utf-8")
        blocks = [b for b in text.strip().split("\n\n") if b.strip()]
        assert len(blocks) == 40
        previous_end = -1.0
        for i, block in enumerate(blocks, start=1):
            lines = block.split("\n")
            assert int(lines[0]) == i, "SRT indices must be 1..N in order"
            start, end = lines[1].split(" --> ")
            assert start < end, f"cue {i} has a non-positive duration"
            assert len(lines) >= 3, f"cue {i} has no text"

    def test_cues_are_contiguous(self):
        """The adopted style butt-joins cues: no gaps, no overlaps."""
        text = (self.EXAMPLE / "narration_sync4.srt").read_text(encoding="utf-8")

        def secs(stamp: str) -> float:
            h, m, rest = stamp.split(":")
            s, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        times = []
        for block in [b for b in text.strip().split("\n\n") if b.strip()]:
            start, end = block.split("\n")[1].split(" --> ")
            times.append((secs(start), secs(end)))
        for (_, prior_end), (next_start, _) in zip(times, times[1:]):
            assert prior_end == next_start

    def test_subtitles_contain_no_punctuation(self):
        """Art direction requires punctuation-free Chinese captions."""
        text = (self.EXAMPLE / "narration_sync4.srt").read_text(encoding="utf-8")
        body = "\n".join(
            line
            for line in text.split("\n")
            if line and "-->" not in line and not line.strip().isdigit()
        )
        for punct in "，。、：；！？——":
            assert punct not in body, f"punctuation {punct!r} found in subtitles"

    def test_narration_text_matches_cue_text(self):
        """narration.txt is the spoken text; the SRT is that text minus
        form must be exact (modulo the spaces the subtitle style inserts around
        Latin terms)."""

        def bare(text: str) -> str:
            # Drop all whitespace and punctuation; keep letters/digits/CJK.
            return "".join(
                ch for ch in text if not ch.isspace() and not _is_punct(ch)
            )

        narration = (self.EXAMPLE / "narration.txt").read_text(encoding="utf-8")
        text = (self.EXAMPLE / "narration_sync4.srt").read_text(encoding="utf-8")
        cue_text = "".join(
            line
            for block in text.strip().split("\n\n")
            for line in block.split("\n")[2:]
        )
        assert bare(cue_text) == bare(narration)
