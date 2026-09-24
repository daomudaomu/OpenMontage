"""Contract tests for acoustically-grounded subtitle generation.

Covers `tools.audio.edge_tts` (word-level timing) and
`tools.audio.phrase_aligner` (phrase -> precise time). All tests are offline:
they feed recorded token data rather than calling the network.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.audio.edge_tts import EdgeTTS  # noqa: E402
from tools.audio.phrase_aligner import (  # noqa: E402
    PhraseAligner,
    display_text,
    normalise,
)
from tools.base_tool import ToolStatus  # noqa: E402
from tools.tool_registry import ToolRegistry  # noqa: E402


EXAMPLES = PROJECT_ROOT / "examples" / "ldws-teaching"
REFERENCE_SRT = EXAMPLES / "narration_sync4.srt"


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """Never let a default `output_path` land in the repo root.

    `PhraseAligner` (like every tool here) defaults `output_path` to the current
    directory. Tests that pass `output_path: None` to mean "don't care" would
    otherwise drop a `subtitles.json` into the checkout.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


# Real edge-tts output for the LDWS opening, captured once. Note the broken
# Chinese tokenisation (`管方` / `向盘`) — exactly what the char timeline fixes.
RECORDED_TOKENS = [
    {"text": "开车", "start": 0.100, "end": 0.500},
    {"text": "时", "start": 0.500, "end": 0.725},
    {"text": "车辆", "start": 0.725, "end": 1.075},
    {"text": "突然", "start": 1.075, "end": 1.400},
    {"text": "向", "start": 1.400, "end": 1.562},
    {"text": "车道", "start": 1.562, "end": 1.887},
    {"text": "线", "start": 1.887, "end": 2.087},
    {"text": "偏移", "start": 2.087, "end": 2.512},
    {"text": "而", "start": 2.900, "end": 3.050},
    {"text": "你", "start": 3.050, "end": 3.188},
    {"text": "却", "start": 3.188, "end": 3.350},
    {"text": "没有", "start": 3.350, "end": 3.600},
    {"text": "察觉", "start": 3.600, "end": 3.975},
    {"text": "它", "start": 5.000, "end": 5.150},
    {"text": "不", "start": 5.150, "end": 5.288},
    {"text": "接", "start": 5.288, "end": 5.475},
    {"text": "管方", "start": 5.475, "end": 5.825},
    {"text": "向盘", "start": 5.825, "end": 6.350},
]


def _parse_srt(text: str) -> list[dict]:
    cues = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        if len(lines) < 3:
            continue
        start, end = lines[1].split(" --> ")

        def secs(stamp: str) -> float:
            h, m, rest = stamp.split(":")
            s, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        cues.append(
            {
                "index": int(lines[0]),
                "start": secs(start),
                "end": secs(end),
                "text": "\n".join(lines[2:]),
            }
        )
    return cues


# ---- edge_tts: dependency declaration ----


class TestEdgeTTSDependencies:
    def test_dependency_uses_a_prefix_base_tool_understands(self):
        """`pkg:` is not a prefix `check_dependencies()` implements, so it was
        silently inert. Guard against a regression to that form."""
        tool = EdgeTTS()
        assert tool.dependencies == ["python:edge_tts"]
        assert not any(d.startswith("pkg:") for d in tool.dependencies)

    def test_check_dependencies_agrees_with_get_status(self):
        tool = EdgeTTS()
        try:
            tool.check_dependencies()
            declared_ok = True
        except Exception:
            declared_ok = False
        expected = tool.get_status() == ToolStatus.AVAILABLE
        assert declared_ok == expected, (
            "declared dependencies and reported status disagree — one of them "
            "is not telling the truth"
        )

    def test_missing_dependency_is_detected(self):
        tool = EdgeTTS()
        tool.dependencies = ["python:definitely_not_a_real_module_xyz"]
        with pytest.raises(Exception):
            tool.check_dependencies()

    def test_declares_word_timestamp_support(self):
        tool = EdgeTTS()
        assert tool.supports.get("word_timestamps") is True
        assert "word_level_timestamps" in tool.capabilities


# ---- phrase_aligner: text handling ----


class TestTextNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("开车时，", "开车时"),
            ("车道偏离预警系统。", "车道偏离预警系统"),
            ("是智能网联汽车 ADAS 中的一项预警功能", "是智能网联汽车ADAS中的一项预警功能"),
            ("它不接管方向盘——", "它不接管方向盘"),
            ("“注意”", "注意"),
        ],
    )
    def test_normalise_strips_punctuation_and_spaces(self, raw, expected):
        assert normalise(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("开车时", "开车时"),
            ("是智能网联汽车 ADAS 中的一项预警功能", "是智能网联汽车 ADAS 中的一项预警功能"),
            ("所以LDWS的本质", "所以 LDWS 的本质"),
            ("ADAS中的一项", "ADAS 中的一项"),
            ("是智能网联汽车ADAS中的一项预警功能", "是智能网联汽车 ADAS 中的一项预警功能"),
        ],
    )
    def test_display_text_restores_cjk_latin_spacing(self, raw, expected):
        assert display_text(raw) == expected

    def test_display_text_never_emits_punctuation(self):
        out = display_text("它不接管方向盘，只负责提醒。")
        assert out == "它不接管方向盘只负责提醒"
        assert "，" not in out and "。" not in out


# ---- phrase_aligner: segmentation ----


class TestSegmentation:
    def test_splits_on_punctuation_not_on_length(self):
        """A length-based packer would merge these into one 21-char cue."""
        text = "开车时，车辆突然向车道线偏移，而你却没有察觉。"
        assert PhraseAligner.segment_text(text) == [
            "开车时",
            "车辆突然向车道线偏移",
            "而你却没有察觉",
        ]

    def test_does_not_merge_across_sentence_boundaries(self):
        cues = PhraseAligner.segment_text("它的第一步是感知。安装在挡风玻璃后的前视摄像头。")
        assert cues == ["它的第一步是感知", "安装在挡风玻璃后的前视摄像头"]

    def test_splits_overlong_clause(self):
        text = "一" * 60
        cues = PhraseAligner.segment_text(text, max_chars=20)
        assert len(cues) > 1
        assert all(len(c) <= 20 for c in cues)
        assert "".join(cues) == text

    def test_drops_punctuation_from_cues(self):
        cues = PhraseAligner.segment_text("注意，它只是提醒，不会主动把车拉回车道。")
        assert all("，" not in c and "。" not in c for c in cues)

    def test_keeps_latin_terms_intact(self):
        cues = PhraseAligner.segment_text("所以 LDWS 的本质，是一条感知、决策。")
        assert any("LDWS" in c for c in cues)

    def test_real_narration_reproduces_reference_structure(self):
        """The hand-tuned reference's cue splits are exactly what punctuation
        segmentation produces — verified against the committed example."""
        narration = (EXAMPLES / "narration.txt").read_text(encoding="utf-8")
        auto = PhraseAligner.segment_text(narration, max_chars=24)
        reference = [c["text"] for c in _parse_srt(REFERENCE_SRT.read_text(encoding="utf-8"))]
        assert len(auto) == len(reference) == 40
        assert auto == [t.replace("\n", "") for t in reference]


# ---- phrase_aligner: alignment ----


class TestAlignment:
    def test_matches_phrases_to_acoustic_time(self):
        result = PhraseAligner().execute(
            {
                "tokens": RECORDED_TOKENS,
                "phrases": ["开车时", "它不接管方向盘"],
                "boundary_mode": "onset",
                "output_path": None,
                "format": "json",
            }
        )
        assert result.success, result.error
        cues = result.data and json.loads(
            result.artifacts and Path(result.artifacts[0]).read_text(encoding="utf-8")
        )["cues"]
        assert result.data["unmatched_count"] == 0
        first, second = cues[0], cues[1]
        assert first["start"] == pytest.approx(0.100, abs=0.01)
        # `管方`/`向盘` are bogus tokens; the character timeline must still land
        # the phrase end at the real audio end.
        assert second["start"] == pytest.approx(5.000, abs=0.01)
        assert second["end"] == pytest.approx(6.350, abs=0.01)

    def test_rejects_empty_tokens_with_actionable_message(self):
        result = PhraseAligner().execute(
            {"tokens": [], "phrases": ["开车时"], "output_path": None}
        )
        assert not result.success
        assert "WordBoundary" in result.error

    def test_accepts_tick_encoded_offsets(self):
        ticks = [
            {"text": "开车", "offset": 1_000_000, "duration": 4_000_000},
            {"text": "时", "offset": 5_000_000, "duration": 2_250_000},
        ]
        result = PhraseAligner().execute(
            {"tokens": ticks, "phrases": ["开车时"], "output_path": None, "format": "json"}
        )
        assert result.success, result.error
        assert result.data["unmatched_count"] == 0

    def test_unmatched_phrase_is_flagged_not_silently_wrong(self):
        result = PhraseAligner().execute(
            {
                "tokens": RECORDED_TOKENS,
                "phrases": ["开车时", "这段文字根本不在音频里"],
                "output_path": None,
                "format": "json",
            }
        )
        assert result.success, result.error
        assert result.data["unmatched_count"] == 1
        assert result.data["unmatched_indices"] == [2]

    def test_manual_override_beats_acoustic_match(self):
        result = PhraseAligner().execute(
            {
                "tokens": RECORDED_TOKENS,
                "phrases": [{"text": "开车时", "start": 2.0, "end": 3.0}],
                "output_path": None,
                "format": "json",
            }
        )
        assert result.success, result.error
        cue = json.loads(Path(result.artifacts[0]).read_text(encoding="utf-8"))["cues"][0]
        assert (cue["start"], cue["end"]) == (2.0, 3.0)

    def test_butt_mode_leaves_no_gaps_or_overlaps(self):
        narration = (EXAMPLES / "narration.txt").read_text(encoding="utf-8")
        phrases = PhraseAligner.segment_text(narration, max_chars=24)
        tokens = json.loads(
            (PROJECT_ROOT / "tests" / "fixtures" / "ldws_tokens.json").read_text(
                encoding="utf-8"
            )
        )
        result = PhraseAligner().execute(
            {
                "tokens": tokens,
                "phrases": phrases,
                "boundary_mode": "butt",
                "output_path": None,
                "format": "json",
                "audio_end": tokens[-1]["end"],
            }
        )
        assert result.success, result.error
        cues = json.loads(Path(result.artifacts[0]).read_text(encoding="utf-8"))["cues"]
        for earlier, later in zip(cues, cues[1:]):
            assert earlier["end"] == later["start"]

    def test_final_cue_never_outlives_the_audio(self):
        tokens = json.loads(
            (PROJECT_ROOT / "tests" / "fixtures" / "ldws_tokens.json").read_text(
                encoding="utf-8"
            )
        )
        audio_end = tokens[-1]["end"]
        result = PhraseAligner().execute(
            {
                "tokens": tokens,
                "phrases": ["永远是最终的责任主体"],
                "output_path": None,
                "format": "json",
                "audio_end": audio_end,
            }
        )
        cue = json.loads(Path(result.artifacts[0]).read_text(encoding="utf-8"))["cues"][0]
        assert cue["end"] <= audio_end


class TestAcousticProvenance:
    """The whole point of Phase 1: timestamps must come from audio, not maths."""

    @staticmethod
    def _residual_ms(cues: list[dict]) -> float:
        """Stdev of residuals after fitting start ~ cumulative character count.

        A timeline derived by interpolating on character count fits that line
        almost exactly (residual ~0 ms). Real acoustic timing does not.
        """
        n = len(cues)
        xs = [0.0]
        for cue in cues:
            xs.append(xs[-1] + len(cue["text"].replace("\n", "")))
        xs = xs[:-1]
        ys = [c["start"] for c in cues]
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs) or 1.0
        slope = num / den
        intercept = my - slope * mx
        var = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys)) / n
        return var ** 0.5 * 1000

    def test_aligned_output_is_not_character_count_interpolation(self):
        tokens = json.loads(
            (PROJECT_ROOT / "tests" / "fixtures" / "ldws_tokens.json").read_text(
                encoding="utf-8"
            )
        )
        phrases = [c["text"] for c in _parse_srt(REFERENCE_SRT.read_text(encoding="utf-8"))]
        phrases = [p.replace("\n", "") for p in phrases]

        result = PhraseAligner().execute(
            {
                "tokens": tokens,
                "phrases": phrases,
                "boundary_mode": "butt",
                "output_path": None,
                "format": "json",
                "audio_end": tokens[-1]["end"],
            }
        )
        assert result.success, result.error
        cues = json.loads(Path(result.artifacts[0]).read_text(encoding="utf-8"))["cues"]

        # Same phrase list, but timed by pure proportional interpolation.
        span = tokens[-1]["end"] - tokens[0]["start"]
        total = sum(len(c["text"]) for c in cues) or 1
        cursor = tokens[0]["start"]
        interp = []
        for cue in cues:
            dur = span * len(cue["text"]) / total
            interp.append({"start": cursor, "text": cue["text"]})
            cursor += dur

        acoustic_residual = self._residual_ms(cues)
        interp_residual = self._residual_ms(interp)
        assert interp_residual < 1.0, "the interpolation baseline should be ~0 ms"
        assert acoustic_residual > 100.0, (
            f"acoustic residual {acoustic_residual:.1f} ms is too close to the "
            f"interpolation baseline ({interp_residual:.1f} ms) — the timestamps "
            f"look estimated rather than measured"
        )


# ---- registry integration ----


class TestRegistry:
    def test_both_tools_are_discovered(self):
        reg = ToolRegistry()
        discovered = reg.discover("tools")
        assert "edge_tts" in discovered
        assert "phrase_aligner" in discovered

    def test_phrase_aligner_needs_no_dependencies(self):
        reg = ToolRegistry()
        reg.discover("tools")
        assert reg.get("phrase_aligner").get_status() == ToolStatus.AVAILABLE
