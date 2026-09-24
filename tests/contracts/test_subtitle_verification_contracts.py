"""Contracts for subtitle verification — the checks that used to be fiction.

Before this file's subject existed, `video_compose._run_final_review` treated
"an .srt file exists on disk" as proof that subtitles were present and
correctly timed, and hard-coded `coverage_ratio = 1.0`. Neither
`coverage_ratio` nor `timing_drift_detected` was computed anywhere in the
repository. A two-second render whose only cue sat at 16:39 therefore passed
with a clean subtitle report.

These tests lock in the replacements:

- real coverage/timing maths from `tools.subtitle.srt_audit`;
- burn *evidence* before claiming subtitles reached the picture;
- truncation and missing-caption findings that actually flip the status
  (they used to be written into `issues` and then ignored, because the status
  decision only substring-matched a hardcoded keyword list);
- no fabricated per-word timings for Chinese.

Everything here is offline and deterministic: a real 2-second MP4 is produced
with ffmpeg, and the SRT files are written inline.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.subtitle.srt_audit import (  # noqa: E402
    audit_srt,
    compare_cue_grid,
    file_sha256,
    has_cjk,
    parse_srt,
    probe_bottom_band_ink,
    union_span,
)
from tools.video.video_compose import VideoCompose  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    """Keep default output paths out of the checkout (see sibling suites)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def tiny_video(tmp_path_factory) -> Path:
    """A real 2-second MP4 — ffprobe/ffmpeg must genuinely be exercised."""
    out = tmp_path_factory.mktemp("subs") / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(out),
        ],
        check=True,
    )
    return out


def _write_srt(path: Path, cues: list[tuple[float, float, str]]) -> Path:
    blocks = []
    for i, (start, end, text) in enumerate(cues, start=1):
        def ts(sec: float) -> str:
            ms = int(round(sec * 1000))
            h, rem = divmod(ms, 3_600_000)
            m, rem = divmod(rem, 60_000)
            s, ms = divmod(rem, 1_000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        blocks.append(f"{i}\n{ts(start)} --> {ts(end)}\n{text}")
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def _base_edit(**extra) -> dict:
    return dict(
        {
            "version": "1.0",
            "render_runtime": "remotion",
            "cuts": [{"id": "c1", "source": "x", "in_seconds": 0, "out_seconds": 2}],
        },
        **extra,
    )


# --------------------------------------------------------------------------- #
#  srt_audit primitives
# --------------------------------------------------------------------------- #


class TestSrtParsing:
    def test_parses_cues_with_real_bounds(self):
        cues, problems = parse_srt(
            "1\n00:00:01,500 --> 00:00:03,250\n你好世界\n\n"
            "2\n00:00:03,250 --> 00:00:04,000\n第二句\n"
        )
        assert problems == []
        assert [c.text for c in cues] == ["你好世界", "第二句"]
        assert cues[0].start == pytest.approx(1.5)
        assert cues[0].end == pytest.approx(3.25)

    def test_rejects_four_digit_milliseconds(self):
        """`,1000` is malformed and strict parsers reject it — so must we."""
        cues, problems = parse_srt("1\n00:00:00,1000 --> 00:00:01,000\nbad\n")
        assert cues == []
        assert any("timing line" in p for p in problems)

    def test_reports_end_before_start(self):
        _, problems = parse_srt("1\n00:00:05,000 --> 00:00:02,000\nbackwards\n")
        assert any("not after start" in p for p in problems)

    def test_reports_missing_index_without_losing_the_cue(self):
        """A non-numeric index must not hide an otherwise valid cue."""
        cues, problems = parse_srt("intro\n00:00:00,500 --> 00:00:01,000\nhello\n")
        assert len(cues) == 1
        assert any("not an integer" in p for p in problems)

    def test_handles_crlf(self):
        cues, problems = parse_srt("1\r\n00:00:00,500 --> 00:00:01,000\r\nhi\r\n")
        assert len(cues) == 1 and problems == []

    def test_empty_input_is_a_problem_not_a_crash(self):
        cues, problems = parse_srt("")
        assert cues == []
        assert any("no cues" in p for p in problems)


class TestCoverageMaths:
    def test_union_does_not_double_count_overlaps(self):
        cues, _ = parse_srt(
            "1\n00:00:00,000 --> 00:00:02,000\na\n\n"
            "2\n00:00:01,000 --> 00:00:03,000\nb\n"
        )
        # Sum would be 4.0s; the union is 3.0s.
        assert union_span(cues) == pytest.approx(3.0)

    def test_coverage_clips_to_the_video_window(self):
        """A cue parked past the end of the render contributes zero coverage.

        This is the arithmetic that made the original defect invisible: before
        clipping, an impossible SRT reported coverage_ratio 1.0.
        """
        cues, _ = parse_srt("1\n00:16:39,000 --> 00:16:41,000\nfar away\n")
        assert union_span(cues, clip_start=0.0, clip_end=2.0) == 0.0

    def test_coverage_is_computed_not_hardcoded(self):
        cues, _ = parse_srt("1\n00:00:00,500 --> 00:00:01,500\nhalf\n")
        assert union_span(cues, clip_start=0.0, clip_end=2.0) / 2.0 == pytest.approx(0.5)

    def test_partial_overlap_counts_only_the_visible_part(self):
        cues, _ = parse_srt("1\n00:00:01,000 --> 00:00:03,000\nspill\n")
        assert union_span(cues, clip_start=0.0, clip_end=2.0) == pytest.approx(1.0)


class TestAuditFindings:
    def test_flags_cues_that_can_never_display(self, tmp_path):
        srt = _write_srt(tmp_path / "late.srt", [(999.0, 1001.0, "不在视频里")])
        report = audit_srt(srt, video_duration=2.0, narration_duration=2.0)
        assert report["coverage_ratio"] == 0.0
        assert any("at or after the end of the video" in i for i in report["issues"])
        assert any("after the narration ends" in i for i in report["issues"])

    def test_flags_cue_straddling_the_end(self, tmp_path):
        srt = _write_srt(tmp_path / "straddle.srt", [(1.0, 3.0, "溢出")])
        report = audit_srt(srt, video_duration=2.0)
        assert any("extend past the end of the video" in i for i in report["issues"])

    def test_flags_out_of_order_cues(self, tmp_path):
        srt = _write_srt(
            tmp_path / "order.srt", [(1.0, 1.5, "first"), (0.2, 0.8, "second")]
        )
        report = audit_srt(srt, video_duration=5.0)
        assert any("out of order" in i for i in report["issues"])

    def test_clean_srt_against_matching_video_has_no_issues(self, tmp_path):
        srt = _write_srt(tmp_path / "ok.srt", [(0.1, 1.0, "一"), (1.0, 1.9, "二")])
        report = audit_srt(srt, video_duration=2.0, narration_duration=2.0)
        assert report["cue_count"] == 2
        assert report["issues"] == []
        assert report["critical_issues"] == []
        # 0.1-1.0 plus 1.0-1.9 is 1.8s of the 2.0s video.
        assert report["coverage_ratio"] == pytest.approx(0.9, abs=0.01)

    def test_missing_file_is_a_finding_not_an_exception(self, tmp_path):
        report = audit_srt(tmp_path / "absent.srt", video_duration=2.0)
        assert report["exists"] is False
        assert any("does not exist" in i for i in report["issues"])


class TestCaptionGridComparison:
    def test_matches_sentence_captions_across_finer_cues(self):
        """A declared sentence legitimately spans several cues."""
        cues, _ = parse_srt(
            "1\n00:00:00,000 --> 00:00:01,000\n开车时\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\n车辆偏移\n"
        )
        grid = compare_cue_grid(
            cues,
            [
                {"word": "开车时车辆偏移", "startMs": 0, "endMs": 2000},
            ],
        )
        assert grid["expected_matched"] == 1
        assert grid["expected_unmatched"] == []

    def test_detects_a_different_track(self):
        cues, _ = parse_srt("1\n00:00:00,000 --> 00:00:01,000\n完全不同的内容\n")
        grid = compare_cue_grid(
            cues, [{"word": "字幕根本不在文件里", "startMs": 0, "endMs": 1000}]
        )
        assert grid["expected_unmatched"]

    def test_flags_timing_drift_beyond_tolerance(self):
        cues, _ = parse_srt("1\n00:00:05,000 --> 00:00:06,000\n漂移\n")
        grid = compare_cue_grid(
            cues, [{"word": "漂移", "startMs": 0, "endMs": 1000}], tolerance=0.5
        )
        assert grid["max_delta_seconds"] == pytest.approx(5.0)
        assert grid["within_tolerance"] is False


class TestCjkDetection:
    @pytest.mark.parametrize("text", ["开车时", "ひらがな", "カタカナ", "全角Ａ"])
    def test_detects_cjk(self, text):
        assert has_cjk(text)

    @pytest.mark.parametrize("text", ["hello world", "café", "12345"])
    def test_rejects_non_cjk(self, text):
        assert not has_cjk(text)


# --------------------------------------------------------------------------- #
#  Subtitle check inside the final review
# --------------------------------------------------------------------------- #


class TestSubtitleCheckRequiresEvidence:
    """The core contract: a file on disk is not proof of burned subtitles."""

    def test_impossible_srt_no_longer_passes(self, tiny_video, tmp_path):
        """The original B1 repro: the file exists, so it used to pass."""
        srt = _write_srt(tmp_path / "impossible.srt", [(999.0, 1001.0, "不在视频里")])
        review = VideoCompose()._run_final_review(
            tiny_video, _base_edit(subtitles={"enabled": True, "source": str(srt)})
        )
        sc = review["checks"]["subtitle_check"]
        assert sc["subtitles_present"] is False, (
            "an .srt on disk with no burn evidence must not be reported as present"
        )
        assert sc["coverage_ratio"] == 0.0
        assert review["status"] == "fail"
        assert review["metadata"]["critical_issues"]

    def test_burn_record_with_matching_hash_is_accepted(self, tiny_video, tmp_path):
        srt = _write_srt(tmp_path / "ok.srt", [(0.1, 1.9, "测试字幕")])
        review = VideoCompose()._run_final_review(
            tiny_video,
            _base_edit(subtitles={"enabled": True, "source": str(srt)}),
            subtitles_burned={"source": str(srt), "source_sha256": file_sha256(srt)},
        )
        sc = review["checks"]["subtitle_check"]
        assert sc["subtitles_present"] is True
        assert sc["delivery"] == "burned_in"
        assert sc["coverage_ratio"] > 0.5
        assert not review["metadata"]["critical_issues"]

    def test_burned_source_disagreeing_with_declared_source_fails(
        self, tiny_video, tmp_path
    ):
        """B4: what was burned must be what edit_decisions declared."""
        declared = _write_srt(tmp_path / "declared.srt", [(0.1, 1.9, "声明的")])
        actually = _write_srt(tmp_path / "actually.srt", [(0.1, 1.9, "实际烧的")])
        review = VideoCompose()._run_final_review(
            tiny_video,
            _base_edit(subtitles={"enabled": True, "source": str(declared)}),
            subtitles_burned={
                "source": str(actually),
                "source_sha256": file_sha256(actually),
            },
        )
        assert review["status"] == "fail"
        assert any(
            "NOT the file declared" in i for i in review["metadata"]["critical_issues"]
        )

    def test_disabled_subtitles_are_not_checked(self, tiny_video):
        review = VideoCompose()._run_final_review(
            tiny_video, _base_edit(subtitles={"enabled": False})
        )
        sc = review["checks"]["subtitle_check"]
        assert sc["subtitles_expected"] is False
        assert sc["issues"] == []

    def test_enabled_without_source_is_reported(self, tiny_video):
        review = VideoCompose()._run_final_review(
            tiny_video, _base_edit(subtitles={"enabled": True})
        )
        assert any(
            "no" in i.lower() and "source" in i.lower()
            for i in review["checks"]["subtitle_check"]["issues"]
        )

    def test_stale_subtitle_file_is_flagged(self, tiny_video, tmp_path):
        """An SRT touched after the render may describe a different cut."""
        import os
        import time

        srt = _write_srt(tmp_path / "stale.srt", [(0.1, 1.9, "字幕")])
        future = time.time() + 600
        os.utime(srt, (future, future))
        review = VideoCompose()._run_final_review(
            tiny_video, _base_edit(subtitles={"enabled": True, "source": str(srt)})
        )
        assert review["checks"]["subtitle_check"]["newer_than_render"] is True
        assert any(
            "modified after the render" in i
            for i in review["checks"]["subtitle_check"]["issues"]
        )


class TestStatusEscalation:
    """Findings that must block used to be reported and then ignored."""

    @staticmethod
    def _video_with_narration(tmp_path: Path, seconds: float) -> tuple[Path, Path]:
        nar = tmp_path / "narration.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds), str(nar)],
            check=True,
        )
        vid = tmp_path / "short.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=black:s=320x240:d=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", str(vid)],
            check=True,
        )
        return vid, nar

    def test_narration_truncation_fails_the_render(self, tmp_path):
        """The regression this suite exists for: truncation used to pass.

        `_check_narration_truncation` wrote its finding into `issues`, but the
        status decision only substring-matched a keyword list that did not
        contain "narration truncated" — so a render missing the end of its own
        speech still returned status "pass".
        """
        vid, nar = self._video_with_narration(tmp_path, 30.0)
        review = VideoCompose()._run_final_review(
            vid, _base_edit(audio={"narration": {"src": str(nar)}})
        )
        assert (
            review["checks"]["technical_probe"]["narration_duration_check"]["status"]
            == "truncated"
        )
        assert review["status"] == "fail"
        assert review["recommended_action"] == "re_render"
        assert any(
            "Narration truncated" in i for i in review["metadata"]["critical_issues"]
        )

    def test_matching_narration_length_is_not_critical(self, tmp_path):
        vid, nar = self._video_with_narration(tmp_path, 2.0)
        review = VideoCompose()._run_final_review(
            vid, _base_edit(audio={"narration": {"src": str(nar)}})
        )
        assert (
            review["checks"]["technical_probe"]["narration_duration_check"]["status"]
            == "ok"
        )
        assert not any(
            "Narration truncated" in i for i in review["metadata"]["critical_issues"]
        )

    def test_critical_issues_are_recorded_structurally(self, tiny_video, tmp_path):
        srt = _write_srt(tmp_path / "late.srt", [(999.0, 1001.0, "太远")])
        review = VideoCompose()._run_final_review(
            tiny_video, _base_edit(subtitles={"enabled": True, "source": str(srt)})
        )
        assert "critical_issues" in review["metadata"]
        # Every critical finding must also appear in the human-readable list.
        for finding in review["metadata"]["critical_issues"]:
            assert any(finding in i or i in finding for i in review["issues_found"])

    def test_final_review_still_satisfies_its_schema(self, tiny_video, tmp_path):
        from schemas.artifacts import validate_artifact

        srt = _write_srt(tmp_path / "ok.srt", [(0.1, 1.9, "测试")])
        review = VideoCompose()._run_final_review(
            tiny_video, _base_edit(subtitles={"enabled": True, "source": str(srt)})
        )
        validate_artifact("final_review", review)


# --------------------------------------------------------------------------- #
#  Style resolution (schema vs implementation mismatch)
# --------------------------------------------------------------------------- #


class TestSubtitleStyleResolution:
    def test_schema_style_string_does_not_crash(self):
        """`subtitles.style` is a STRING in the schema ("sentence"). Calling
        .items() on it raised AttributeError, so every schema-conformant
        project crashed the FFmpeg burn path."""
        resolved = VideoCompose._resolve_subtitle_style(
            None, {"subtitles": {"enabled": True, "style": "sentence"}}, None
        )
        assert resolved["font"] == "Inter"

    def test_flat_schema_keys_are_applied(self):
        resolved = VideoCompose._resolve_subtitle_style(
            None,
            {
                "subtitles": {
                    "enabled": True,
                    "style": "sentence",
                    "font": "Noto Sans SC",
                    "font_size": 26,
                    "color": "&H00FFFFFF",
                    "margin_v": 55,
                    "position": "bottom-center",
                }
            },
            None,
        )
        assert resolved["font"] == "Noto Sans SC"
        assert resolved["font_size"] == 26
        assert resolved["primary_color"] == "&H00FFFFFF"
        assert resolved["margin_v"] == 55
        assert resolved["alignment"] == 2

    def test_explicit_style_still_wins(self):
        resolved = VideoCompose._resolve_subtitle_style(
            {"font": "Explicit"},
            {"subtitles": {"enabled": True, "style": "sentence", "font": "FromEdit"}},
            None,
        )
        assert resolved["font"] == "Explicit"


# --------------------------------------------------------------------------- #
#  Visibility probe and CJK caption splitting
# --------------------------------------------------------------------------- #


class TestVisibilityProbe:
    def test_probe_reports_a_ratio_for_a_real_video(self, tiny_video):
        probe = probe_bottom_band_ink(tiny_video, 2.0, samples=3)
        assert "error" not in probe, probe
        assert probe["samples_taken"] == 3
        assert 0.0 <= probe["ratio_max"] <= 1.0

    def test_probe_is_advisory_not_a_gate(self, tiny_video, tmp_path):
        """A low ink reading must never, by itself, fail a conforming render."""
        srt = _write_srt(tmp_path / "ok.srt", [(0.1, 1.9, "测试")])
        review = VideoCompose()._run_final_review(
            tiny_video,
            _base_edit(subtitles={"enabled": True, "source": str(srt)}),
            subtitles_burned={"source": str(srt), "source_sha256": file_sha256(srt)},
        )
        assert review["checks"]["subtitle_check"]["delivery"] == "burned_in"
        assert "visibility_probe" in review["checks"]["subtitle_check"]

    def test_missing_video_reports_error_not_raises(self, tmp_path):
        probe = probe_bottom_band_ink(tmp_path / "absent.mp4", 2.0)
        assert "error" in probe


class TestChineseCaptionSplitting:
    def test_cjk_cue_is_not_split_into_fake_words(self, tmp_path):
        """`text.split()` returns a whole Chinese cue as one "word", so the
        per-word timing degenerated into an even split — fabricated timings."""
        from tools.video.remotion_caption_burn import RemotionCaptionBurn

        srt = _write_srt(
            tmp_path / "zh.srt",
            [(0.1, 0.954, "开车时"), (0.954, 3.304, "车辆突然向车道线偏移")],
        )
        captions = RemotionCaptionBurn()._srt_to_word_captions(str(srt))
        assert len(captions) == 2, "one caption per Chinese cue, not per character"
        assert captions[0]["word"] == "开车时"
        # The cue's own acoustic bounds are preserved exactly.
        assert captions[0]["startMs"] == 100
        assert captions[0]["endMs"] == 954

    def test_english_captions_still_split_per_word(self, tmp_path):
        from tools.video.remotion_caption_burn import RemotionCaptionBurn

        srt = _write_srt(tmp_path / "en.srt", [(1.0, 3.0, "hello brave new world")])
        captions = RemotionCaptionBurn()._srt_to_word_captions(str(srt))
        assert [c["word"] for c in captions] == ["hello", "brave", "new", "world"]


# --------------------------------------------------------------------------- #
#  The committed reference SRT
# --------------------------------------------------------------------------- #


class TestReferenceSrtAgainstRealRender:
    """The committed LDWS baseline must audit cleanly against its own render.

    This pins the end-to-end story: the SRT in `examples/` is the 40-cue
    acoustic alignment, and it is consistent with the audio-derived render
    duration (77.824s) rather than the truncated 76.054s predecessor.
    """

    SRT = PROJECT_ROOT / "examples" / "ldws-teaching" / "narration_sync4.srt"

    def test_audits_cleanly_against_the_audio_derived_render(self):
        if not self.SRT.is_file():
            pytest.skip("reference SRT not present")
        report = audit_srt(
            self.SRT, video_duration=77.824, narration_duration=77.256
        )
        assert report["cue_count"] == 40
        assert report["format_problems"] == []
        assert report["issues"] == []
        assert report["coverage_ratio"] > 0.98

    def test_the_truncated_render_would_have_been_caught(self):
        """Against the old 76.054s render the SRT overruns the picture."""
        if not self.SRT.is_file():
            pytest.skip("reference SRT not present")
        report = audit_srt(
            self.SRT, video_duration=76.054, narration_duration=77.256
        )
        assert any(
            "extend past the end of the video" in i for i in report["issues"]
        ), "the new audit must flag the truncation A3 fixed"

    def test_reference_sha_is_stable(self):
        if not self.SRT.is_file():
            pytest.skip("reference SRT not present")
        digest = hashlib.sha256(self.SRT.read_bytes()).hexdigest()
        assert digest == (
            "bdb62d8e2dffcb3f6dc5d66971f904946a6c2aaf9f7e6cba1ebf0d6fb59db0a0"
        )


# --------------------------------------------------------------------------- #
#  Atelier burn/review ordering (B2)
# --------------------------------------------------------------------------- #


class TestAtelierBurnOrdering:
    """B2's real defect was an ordering bug: the review ran BEFORE the burn.

    The captioned final of ldws-teaching carried 1.0-3.1% bottom-band ink while
    the master carried 0.0%, and yet the review — which runs inside the tool —
    reported no subtitles. It could not do otherwise: the burn happened later,
    outside the tool. These tests stub the Remotion render (a real one needs a
    full composer project) and assert the *order* of the two side effects, plus
    that the burn record reaches the review.
    """

    @staticmethod
    def _prepare(tmp_path, monkeypatch):
        from tools.video.video_compose import VideoCompose

        tool = VideoCompose()
        entry = tmp_path / "proj" / "index.tsx"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("export const x = 1;\n", encoding="utf-8")
        out = tmp_path / "renders" / "out.mp4"
        srt = _write_srt(tmp_path / "n.srt", [(0.1, 1.9, "字幕内容")])

        calls: list[str] = []

        def fake_run_command(cmd, **kwargs):
            """Stand in for the Remotion render only.

            `_burn_subtitles` also goes through run_command, so this must not
            swallow it — a blanket fake made the burn silently produce nothing
            and the failure looked like a burn bug rather than a test artifact.
            """
            if "remotion" not in " ".join(str(c) for c in cmd):
                return VideoCompose.run_command(tool, cmd, **kwargs)
            calls.append("render")
            out.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", "color=c=black:s=320x240:d=2",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-shortest", str(out)],
                check=True,
            )
            import subprocess as sp
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(tool, "run_command", fake_run_command)

        # Record when the burn happens relative to the review.
        real_burn = tool._burn_subtitles_with_record
        real_review = tool._run_final_review

        def spy_burn(*a, **kw):
            calls.append("burn")
            return real_burn(*a, **kw)

        captured: dict = {}

        def spy_review(*a, **kw):
            calls.append("review")
            captured["subtitles_burned"] = kw.get("subtitles_burned")
            return real_review(*a, **kw)

        monkeypatch.setattr(tool, "_burn_subtitles_with_record", spy_burn)
        monkeypatch.setattr(tool, "_run_final_review", spy_review)

        edit = {
            "version": "1.0",
            "render_runtime": "remotion",
            "composition_mode": "atelier",
            "renderer_family": "bespoke",
            "cuts": [],
            "subtitles": {"enabled": True, "source": str(srt)},
            "bespoke": {
                "entry": str(entry),
                "composition_id": "TestComp",
                "art_direction": "test",
            },
        }
        inputs = {"output_path": str(out), "edit_decisions": edit}
        return tool, inputs, edit, calls, captured

    def test_burn_happens_before_the_review(self, tmp_path, monkeypatch):
        tool, inputs, edit, calls, captured = self._prepare(tmp_path, monkeypatch)
        result = tool._render_via_atelier(inputs, edit)
        assert result.success, result.error
        assert calls == ["render", "burn", "review"], (
            f"the burn must happen before the review so the review can see the "
            f"subtitles; got {calls}"
        )

    def test_burn_record_reaches_the_review(self, tmp_path, monkeypatch):
        tool, inputs, edit, calls, captured = self._prepare(tmp_path, monkeypatch)
        result = tool._render_via_atelier(inputs, edit)
        assert result.success, result.error
        record = captured.get("subtitles_burned")
        assert record, "the review must receive the burn record"
        assert record["source_sha256"] == file_sha256(edit["subtitles"]["source"])
        # And the result reports what was burned.
        assert result.data["subtitles_burned"]["source_sha256"] == record["source_sha256"]

    def test_burn_in_false_skips_the_burn(self, tmp_path, monkeypatch):
        """A composition that draws its own captions can opt out."""
        tool, inputs, edit, calls, captured = self._prepare(tmp_path, monkeypatch)
        edit["subtitles"]["burn_in"] = False
        result = tool._render_via_atelier(inputs, edit)
        assert result.success, result.error
        assert "burn" not in calls
        assert result.data["subtitles_burned"] is None

    def test_disabled_subtitles_skip_the_burn(self, tmp_path, monkeypatch):
        tool, inputs, edit, calls, captured = self._prepare(tmp_path, monkeypatch)
        edit["subtitles"]["enabled"] = False
        result = tool._render_via_atelier(inputs, edit)
        assert result.success, result.error
        assert "burn" not in calls

    def test_failed_burn_fails_the_render(self, tmp_path, monkeypatch):
        """Never ship a master whose declared subtitles could not be applied."""
        tool, inputs, edit, calls, captured = self._prepare(tmp_path, monkeypatch)
        from tools.base_tool import ToolResult

        monkeypatch.setattr(
            tool,
            "_burn_subtitles_with_record",
            lambda *a, **kw: ToolResult(success=False, error="ffmpeg exploded"),
        )
        result = tool._render_via_atelier(inputs, edit)
        assert not result.success
        assert "burning the declared subtitles failed" in result.error
