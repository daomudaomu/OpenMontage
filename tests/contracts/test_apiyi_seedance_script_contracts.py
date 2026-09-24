"""Contract tests for the APIYi Seedance 2.0 video script's paid-path guards.

The script lives outside the `tools/` package (it is a vendor skill script), so
it is loaded by path -- the same approach as
tests/contracts/test_kling_official_e2e_script.py.

These tests exist because creating a Seedance task is the **billable** step and
the failure modes are expensive:

* C0.1 -- the create request's read timeout was hardcoded to 60s. A create call
  uploads base64 media and may queue, so a slow-but-successful submission timed
  out client-side *after* the task was created and charged.
* C0.2 -- the task id was only printed to stderr. Any later poll/download
  failure lost the only handle on an already-paid task. There is no cancel
  endpoint on this gateway, so recovery means persisting the id and being able
  to query it again.

No network access: every transport function is monkeypatched, and the session
guard in tests/conftest.py blocks sockets anyway.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = (
    PROJECT_ROOT / ".agents" / "skills" / "apiyi-seedance2-video-gen"
    / "scripts" / "generate_video.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("apiyi_generate_video", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    module = _load_script()
    # Never really sleep between polls; tests drive the state machine directly.
    module.time.sleep = lambda _seconds: None
    return module


@pytest.fixture
def no_network(script, monkeypatch):
    """Fail loudly if any test reaches a real transport function."""
    def boom(*args, **kwargs):
        raise AssertionError("network function called during test")
    for name in ("http_json", "fetch_task", "download_video"):
        monkeypatch.setattr(script, name, boom)
    return boom


def run_script(script, monkeypatch, argv, **patches):
    """Invoke main() with argv, patching the given module functions.

    A low `--timeout` is injected unless the caller sets one, so that a fake
    which never reports a terminal status fails in seconds instead of burning
    the script's 1200s default.  Tests that exercise timeout behaviour pass
    their own value.
    """
    argv = list(argv)
    if "--timeout" not in argv:
        argv += ["--timeout", "10"]
    for name, value in patches.items():
        monkeypatch.setattr(script, name, value)
    monkeypatch.setattr(script.sys, "argv", ["generate_video.py", *argv])
    return script.main()


def create_then_succeed(script, monkeypatch, *, status="succeeded",
                        video_url="https://cdn/v.mp4", timeout_flag="0"):
    """Patch transport so create returns an id and the first poll is terminal.

    A fake that answers *every* call with a create-shaped response would leave
    the poll loop running to its 1200s deadline, hanging the suite. Returning a
    terminal status on the second call keeps every create-path test fast.
    """
    calls = {"n": 0}
    seen = {}

    def fake_http_json(req, timeout):
        calls["n"] += 1
        seen.setdefault("create_timeout", timeout)
        if calls["n"] == 1:
            return {"id": "cgt-test-1"}
        return {
            "status": status,
            "content": {"video_url": video_url} if status == "succeeded" else {},
            "usage": {"completion_tokens": 7},
            "duration": 5, "ratio": "16:9", "resolution": "480p", "seed": 1,
        }

    monkeypatch.setattr(script, "http_json", fake_http_json)
    monkeypatch.setattr(script, "download_video",
                        lambda url, path, timeout: path.write_bytes(b"V"))
    seen["calls"] = calls
    return seen


# ---------------------------------------------------------------------------
# C0.1 -- create timeout is configurable and generous by default
# ---------------------------------------------------------------------------

class TestCreateTimeout:

    def test_default_is_not_the_old_hardcoded_60(self, script):
        assert script.DEFAULT_CREATE_TIMEOUT >= 300

    def test_create_timeout_flag_accepted(self, script, monkeypatch, no_network, tmp_path):
        seen = create_then_succeed(script, monkeypatch)
        rc = run_script(
            script, monkeypatch,
            ["-p", "x", "--api-key", "sk-t", "--create-timeout", "777",
             "--poll-interval", "0", "-f", str(tmp_path / "v.mp4")],
            fetch_task=no_network,
        )
        # The create call must receive the configured timeout, and the poll
        # request must not reuse it.
        assert seen["create_timeout"] == 777
        assert rc == 0

    def test_poll_timeout_is_separate_from_create_timeout(self, script, monkeypatch, tmp_path):
        """A short poll timeout is correct; a short create timeout is not."""
        assert script.DEFAULT_POLL_REQUEST_TIMEOUT <= 60
        assert script.DEFAULT_POLL_REQUEST_TIMEOUT < script.DEFAULT_CREATE_TIMEOUT

    def test_create_failure_does_not_silently_retry(
        self, script, monkeypatch, no_network, tmp_path
    ):
        """Retrying a billable create could pay twice."""
        calls = {"n": 0}

        def failing(req, timeout):
            calls["n"] += 1
            raise RuntimeError("HTTP 504: gateway timeout")

        rc = run_script(
            script, monkeypatch,
            ["-p", "x", "--api-key", "sk-t", "-f", str(tmp_path / "v.mp4")],
            http_json=failing, download_video=no_network, fetch_task=no_network,
        )
        assert rc == 1
        assert calls["n"] == 1, "create must be attempted exactly once"

    def test_create_timeout_message_points_at_recovery(
        self, script, monkeypatch, no_network, tmp_path, capsys
    ):
        def failing(req, timeout):
            raise RuntimeError("请求超时（300s）")

        rc = run_script(
            script, monkeypatch,
            ["-p", "x", "--api-key", "sk-t", "-f", str(tmp_path / "v.mp4")],
            http_json=failing, download_video=no_network, fetch_task=no_network,
        )
        err = capsys.readouterr().err
        assert rc == 1
        assert "--query" in err


# ---------------------------------------------------------------------------
# C0.2 -- the paid task id is persisted before polling
# ---------------------------------------------------------------------------

class TestTaskRecord:

    def test_record_written_before_polling_starts(self, script, monkeypatch, tmp_path):
        """The sidecar must exist even if polling then fails."""
        out = tmp_path / "v.mp4"
        seen = {}
        calls = {"n": 0}

        def fake_http(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"id": "cgt-x"}
            record = out.with_suffix(out.suffix + ".task.json")
            seen["record_at_first_poll"] = record.is_file()
            return {"status": "failed", "error": {"message": "boom"}}

        rc = run_script(
            script, monkeypatch,
            ["-p", "x", "--api-key", "sk-t", "--poll-interval", "0",
             "-f", str(out)],
            http_json=fake_http, download_video=lambda *a: None,
            fetch_task=lambda *a, **k: {},
        )
        assert rc == 1
        assert seen["record_at_first_poll"] is True

    def test_record_contains_task_id_and_request_body(self, script, monkeypatch, tmp_path):
        out = tmp_path / "v.mp4"
        record = script.write_task_record(
            out, task_id="cgt-abc", base_url="https://x/tasks",
            body={"model": "m", "duration": 5}, out_path_final=out,
        )
        data = json.loads(record.read_text(encoding="utf-8"))
        assert data["task_id"] == "cgt-abc"
        assert data["base_url"] == "https://x/tasks"
        assert data["request_body"] == {"model": "m", "duration": 5}
        assert data["status"] == "submitted"

    def test_record_write_is_atomic(self, script, tmp_path):
        """A half-written record is worse than none; write-then-rename."""
        out = tmp_path / "v.mp4"
        script.write_task_record(
            out, task_id="cgt-1", base_url="b", body={}, out_path_final=out,
        )
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
        assert leftovers == []

    def test_record_marks_success_after_download(self, script, monkeypatch, tmp_path):
        out = tmp_path / "v.mp4"
        script.write_task_record(
            out, task_id="cgt-ok", base_url="b", body={}, out_path_final=out,
        )
        monkeypatch.setattr(script, "download_video",
                            lambda url, path, timeout: path.write_bytes(b"V"))
        rc = script.finish_task(
            {"status": "succeeded", "content": {"video_url": "https://cdn/v.mp4"},
             "usage": {}, "duration": 5, "ratio": "16:9", "resolution": "480p", "seed": 1},
            out_path=out, task_id="cgt-ok", base_url="b", api_key="k",
            download_timeout=10,
        )
        data = json.loads(script.task_record_path(out).read_text(encoding="utf-8"))
        assert rc == 0
        assert data["status"] == "succeeded"
        assert "completed_at" in data


class TestRecoveryPaths:
    """Recovery must never create a task, so it can never bill again."""

    def test_query_succeeded_downloads_without_creating(self, script, monkeypatch, tmp_path):
        out = tmp_path / "r.mp4"
        monkeypatch.setattr(script, "fetch_task", lambda *a, **k: {
            "status": "succeeded", "content": {"video_url": "https://cdn/r.mp4"},
            "usage": {"completion_tokens": 5}, "duration": 5,
            "ratio": "16:9", "resolution": "480p", "seed": 2,
        })
        monkeypatch.setattr(script, "download_video",
                            lambda url, path, timeout: path.write_bytes(b"V"))

        def must_not_create(*a, **k):
            raise AssertionError("create called during recovery")

        monkeypatch.setattr(script, "http_json", must_not_create)
        rc = run_script(script, monkeypatch,
                        ["--api-key", "sk-t", "--query", "cgt-r", "-f", str(out)])
        assert rc == 0
        assert out.read_bytes() == b"V"

    def test_query_running_task_enters_poll_loop(self, script, monkeypatch, tmp_path):
        out = tmp_path / "q.mp4"
        monkeypatch.setattr(script, "fetch_task",
                            lambda *a, **k: {"status": "running"})
        polls = {"n": 0}

        def fake_http(req, timeout):
            polls["n"] += 1
            if polls["n"] < 2:
                return {"status": "running"}
            return {"status": "succeeded", "content": {"video_url": "https://cdn/q.mp4"},
                    "usage": {}, "duration": 5, "ratio": "16:9",
                    "resolution": "480p", "seed": 3}

        monkeypatch.setattr(script, "http_json", fake_http)
        monkeypatch.setattr(script, "download_video",
                            lambda url, path, timeout: path.write_bytes(b"V"))
        rc = run_script(script, monkeypatch,
                        ["--api-key", "sk-t", "--query", "cgt-q",
                         "--poll-interval", "0", "-f", str(out)])
        assert rc == 0
        assert polls["n"] >= 2

    def test_resume_reads_task_id_and_base_url_from_record(self, script, monkeypatch, tmp_path):
        out = tmp_path / "s.mp4"
        record = script.write_task_record(
            out, task_id="cgt-resume", base_url="https://custom/tasks",
            body={}, out_path_final=out,
        )
        seen = {}

        def fake_fetch(base, task_id, key, timeout=30):
            seen["base"] = base
            seen["task_id"] = task_id
            return {"status": "succeeded", "content": {"video_url": "https://cdn/s.mp4"},
                    "usage": {}, "duration": 5, "ratio": "16:9",
                    "resolution": "480p", "seed": 4}

        monkeypatch.setattr(script, "fetch_task", fake_fetch)
        monkeypatch.setattr(script, "download_video",
                            lambda url, path, timeout: path.write_bytes(b"V"))
        rc = run_script(script, monkeypatch,
                        ["--api-key", "sk-t", "--resume", str(record)])
        assert rc == 0
        assert seen["task_id"] == "cgt-resume"
        assert seen["base"] == "https://custom/tasks"

    def test_resume_missing_file_fails_cleanly(self, script, monkeypatch, no_network, tmp_path):
        rc = run_script(script, monkeypatch,
                        ["--api-key", "sk-t", "--resume", str(tmp_path / "nope.json")])
        assert rc == 1

    def test_query_and_resume_are_mutually_exclusive(self, script, monkeypatch, no_network):
        rc = run_script(script, monkeypatch,
                        ["--api-key", "sk-t", "--query", "a", "--resume", "b"])
        assert rc == 1

    def test_query_failure_reports_the_id_for_later_retry(
        self, script, monkeypatch, tmp_path, capsys
    ):
        def failing(base, task_id, key, timeout=30):
            raise RuntimeError("HTTP 401: AuthenticationError")

        monkeypatch.setattr(script, "fetch_task", failing)
        rc = run_script(script, monkeypatch,
                        ["--api-key", "sk-t", "--query", "cgt-lost",
                         "-f", str(tmp_path / "l.mp4")])
        err = capsys.readouterr().err
        assert rc == 1
        # The id must survive the failure so it can be retried.
        assert "cgt-lost" in err


class TestPromptIsOptionalForRecovery:
    """Recovery cannot supply a prompt; requiring one would block it."""

    def test_prompt_not_required_for_query(self, script, monkeypatch, tmp_path):
        monkeypatch.setattr(script, "fetch_task",
                            lambda *a, **k: {"status": "failed"})
        rc = run_script(script, monkeypatch,
                        ["--api-key", "sk-t", "--query", "cgt-1",
                         "-f", str(tmp_path / "x.mp4")])
        # Actually reached the query path (exit 1 is the task's own failure),
        # rather than the "prompt required" guard.
        assert rc == 1

    def test_fresh_create_still_requires_a_prompt(self, script, monkeypatch, no_network):
        rc = run_script(script, monkeypatch, ["--api-key", "sk-t"])
        assert rc == 1


# ---------------------------------------------------------------------------
# C0.3 -- upload validation happens BEFORE base64 encoding
# ---------------------------------------------------------------------------

class TestUploadValidation:

    def _png(self, path: Path, width: int, height: int) -> Path:
        from PIL import Image
        Image.new("RGB", (width, height), (1, 2, 3)).save(path)
        return path

    def test_valid_image_passes(self, script, tmp_path):
        assert script.validate_image_file(str(self._png(tmp_path / "ok.png", 1024, 1024))) == []

    def test_side_too_small_is_reported(self, script, tmp_path):
        problems = script.validate_image_file(str(self._png(tmp_path / "s.png", 200, 200)))
        assert any("超出范围" in p for p in problems)

    def test_side_too_large_is_reported(self, script, tmp_path):
        problems = script.validate_image_file(str(self._png(tmp_path / "b.png", 7000, 1000)))
        assert any("超出范围" in p for p in problems)

    def test_extreme_aspect_ratio_is_reported(self, script, tmp_path):
        problems = script.validate_image_file(str(self._png(tmp_path / "w.png", 3000, 300)))
        assert any("宽高比" in p for p in problems)

    def test_unsupported_extension_is_reported(self, script, tmp_path):
        bad = tmp_path / "note.txt"
        bad.write_text("hi", encoding="utf-8")
        assert any("不支持的图片格式" in p for p in script.validate_image_file(str(bad)))

    def test_empty_file_is_reported(self, script, tmp_path):
        empty = tmp_path / "empty.png"
        empty.write_bytes(b"")
        problems = script.validate_image_file(str(empty))
        assert any("空" in p for p in problems)

    def test_oversized_file_is_reported_without_reading_it(self, script, tmp_path):
        big = tmp_path / "big.png"
        big.write_bytes(b"\x00" * 16)
        # Lower the cap rather than allocate 30MB in a test.
        original = script.MAX_IMAGE_BYTES
        script.MAX_IMAGE_BYTES = 8
        try:
            problems = script.validate_image_file(str(big))
        finally:
            script.MAX_IMAGE_BYTES = original
        assert any("超过上限" in p for p in problems)

    def test_media_to_url_rejects_before_encoding(self, script, tmp_path):
        """A rejected upload must raise, not return a data URL."""
        bad = self._png(tmp_path / "small.png", 200, 200)
        with pytest.raises(ValueError) as excinfo:
            script.media_to_url(str(bad), "image")
        assert "未通过上传校验" in str(excinfo.value)

    def test_media_to_url_encodes_valid_image(self, script, tmp_path):
        good = self._png(tmp_path / "ok.png", 512, 512)
        url = script.media_to_url(str(good), "image")
        assert url.startswith("data:image/png;base64,")

    def test_remote_urls_pass_through_unvalidated(self, script):
        """Only local files are ours to validate."""
        for spec in ("https://x.com/a.png", "http://x.com/b.jpg", "asset://abc"):
            assert script.media_to_url(spec, "image") == spec

    def test_local_video_still_rejected_with_clear_message(self, script, tmp_path):
        vid = tmp_path / "v.mp4"
        vid.write_bytes(b"x")
        with pytest.raises(ValueError) as excinfo:
            script.media_to_url(str(vid), "video")
        assert "asset://" in str(excinfo.value)

    def test_missing_pillow_degrades_instead_of_failing(self, script, monkeypatch, tmp_path):
        """Pillow is optional; size/format checks must still run."""
        good = self._png(tmp_path / "ok.png", 512, 512)
        import builtins
        real_import = builtins.__import__

        def no_pil(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("no PIL")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_pil)
        # No dimensions available -> no problems reported, and no crash.
        assert script.validate_image_file(str(good)) == []

    def test_build_body_rejects_bad_first_frame(self, script, tmp_path):
        """Validation must fire on the real code path, not just the helper."""
        class Args:
            prompt = "x"
            model = "mini"
            resolution = "720p"
            ratio = "16:9"
            duration = "5"
            no_audio = False
            watermark = False
            seed = None
            first_frame = str(self._png(tmp_path / "tiny.png", 100, 100))
            last_frame = None
            reference_image = None
            reference_video = None
            reference_audio = None
            return_last_frame = False
            execution_expires_after = None

        with pytest.raises(ValueError) as excinfo:
            script.build_body(Args())
        assert "未通过上传校验" in str(excinfo.value)


# ---------------------------------------------------------------------------
# C4 -- the Python script is the supported entry point, not the Node one
# ---------------------------------------------------------------------------

class TestPythonIsTheSupportedScript:
    """Documented features that the Node sibling cannot express."""

    def test_smart_duration_is_accepted(self, script, monkeypatch, no_network, tmp_path):
        """`--duration -1` is documented; argparse must not treat it as a flag."""
        captured = {}
        calls = {"n": 0}

        def fake_http(req, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                captured["body"] = json.loads(req.data.decode("utf-8"))
                return {"id": "cgt-d"}
            return {"status": "failed", "error": {"message": "stop"}}

        rc = run_script(
            script, monkeypatch,
            ["-p", "x", "--api-key", "sk-t", "--duration", "-1",
             "--poll-interval", "0", "-f", str(tmp_path / "d.mp4")],
            http_json=fake_http, fetch_task=no_network,
            download_video=lambda *a: None,
        )
        assert captured["body"]["duration"] == -1

    def test_create_timeout_flag_exists(self, script):
        """Guards the C0.1 fix against being dropped in a refactor."""
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "--create-timeout" in source
        assert "--query" in source
        assert "--resume" in source
