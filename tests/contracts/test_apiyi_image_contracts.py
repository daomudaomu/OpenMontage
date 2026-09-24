"""Contract tests for the APIYi GPT Image 2 All image provider.

These tests never touch the network: `tests/conftest.py` blocks outbound
sockets session-wide, and the provider is exercised through a fake `requests`
module (the same pattern as tests/tools/test_atlas_video.py).  That matters
here because every real call bills a flat $0.03.

The provider has two quirks that the tests pin deliberately, because both were
observed to break a naive implementation:

1. Images arrive through the **chat completions** endpoint, embedded in the
   assistant message text -- not in an `/images` style field.
2. Signed R2 CDN URLs carry their signature in the **query string**, so a
   parsing regex that stops at the file extension silently yields a 403 URL.
"""

from __future__ import annotations

import base64
import json
import sys
import types

import pytest

from tools.graphics.apiyi_image import (
    ASPECT_RATIO_PHRASES,
    MODEL_ID,
    PRICE_PER_IMAGE_USD,
    ApiyiGptImage2All,
    apply_aspect_ratio,
    extract_image_reference,
    image_bytes_from_reference,
    mime_to_extension,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-image-payload" * 4
PNG_B64 = base64.b64encode(PNG_BYTES).decode()
PNG_DATA_URI = f"data:image/png;base64,{PNG_B64}"


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="", headers=None, content=b""):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text else (json.dumps(payload) if payload is not None else "")
        self.headers = headers or {}
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Records every POST so tests can assert on the exact request shape."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self._responses:
            raise AssertionError(f"unexpected extra POST to {url}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_requests(monkeypatch):
    """Install a fake `requests` module exposing Session/get to the provider.

    The provider calls ``requests.Session()`` itself, so queued sessions are
    handed out in order by the fake constructor rather than being injected.
    """
    created: list[FakeSession] = []
    queue: list[FakeSession] = []
    downloads: list[dict] = []

    def make_session():
        # Hand out a pre-seeded session when one is queued; otherwise an empty
        # one, which makes an unexpected call fail loudly on first POST.
        session = queue.pop(0) if queue else FakeSession([])
        created.append(session)
        return session

    def fake_get(url, **kwargs):
        downloads.append({"url": url, **kwargs})
        return FakeResponse(status_code=200, content=b"downloaded-bytes",
                            headers={"Content-Type": "image/jpeg"})

    module = types.ModuleType("requests")
    module.Session = make_session
    module.get = fake_get
    module.exceptions = types.SimpleNamespace(RequestException=Exception)
    monkeypatch.setitem(sys.modules, "requests", module)
    monkeypatch.setenv("APIYI_API_KEY", "sk-test-key")

    def install(responses):
        session = FakeSession(responses)
        queue.append(session)
        return session

    return types.SimpleNamespace(sessions=created, downloads=downloads, install=install)


def chat_response(reference: str) -> FakeResponse:
    """A realistic APIYi chat-completions response carrying one image."""
    return FakeResponse({
        "id": "chatcmpl-test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reference}}],
    })


# ---------------------------------------------------------------------------
# Extraction — the two quirks that broke naive implementations
# ---------------------------------------------------------------------------

class TestImageReferenceExtraction:

    def test_signed_cdn_url_keeps_query_string(self):
        """A truncated signed URL is a 403 that looks like a CDN fault."""
        url = "https://r2cdn.copilotbase.com/o/abc.png?X-Amz-Signature=deadbeef&X-Amz-Expires=86400"
        assert extract_image_reference(f"![image]({url})") == url

    def test_data_uri_does_not_swallow_trailing_prose(self):
        got = extract_image_reference(f"生成完成：{PNG_DATA_URI} 请查收。")
        assert got == PNG_DATA_URI
        assert " " not in got
        # The strongest proof: the extracted value actually decodes.
        raw, _ = image_bytes_from_reference(got)
        assert raw == PNG_BYTES

    def test_markdown_and_bare_url_forms(self):
        assert extract_image_reference("![i](https://x.com/a.jpeg)") == "https://x.com/a.jpeg"
        assert extract_image_reference("see https://x.com/b.webp ok") == "https://x.com/b.webp"

    def test_parts_list_and_single_part_dict(self):
        parts = [
            {"type": "text", "text": "here"},
            {"type": "image_url", "image_url": {"url": "https://x.com/c.jpg"}},
        ]
        assert extract_image_reference(parts) == "https://x.com/c.jpg"
        assert extract_image_reference({"image_url": {"url": "https://x.com/d.jpg"}}) == "https://x.com/d.jpg"

    def test_returns_none_when_no_image_present(self):
        """A refusal must not be mistaken for an image."""
        assert extract_image_reference("抱歉，我无法生成该图片。") is None
        assert extract_image_reference("") is None
        assert extract_image_reference(None) is None

    def test_mime_to_extension(self):
        assert mime_to_extension("image/png") == ".png"
        assert mime_to_extension("image/jpeg") == ".jpg"
        assert mime_to_extension("image/webp") == ".webp"
        assert mime_to_extension(None) == ".png"
        assert mime_to_extension("application/octet-stream") == ".png"


class TestAspectRatioPhrasing:
    """The provider has no `size` parameter; wording is the only control."""

    def test_prefixes_documented_phrase(self):
        assert apply_aspect_ratio("一只猫", "16:9").startswith("横版 16:9 电影画幅")

    def test_no_ratio_leaves_prompt_untouched(self):
        assert apply_aspect_ratio("一只猫", None) == "一只猫"

    def test_unknown_ratio_leaves_prompt_untouched(self):
        assert apply_aspect_ratio("一只猫", "5:4") == "一只猫"

    def test_does_not_double_specify_framing(self):
        prompt = "横版 16:9 电影画幅，一只猫"
        assert apply_aspect_ratio(prompt, "16:9") == prompt

    def test_every_enum_value_has_a_phrase(self):
        for ratio in ApiyiGptImage2All.input_schema["properties"]["aspect_ratio"]["enum"]:
            assert ratio in ASPECT_RATIO_PHRASES


# ---------------------------------------------------------------------------
# Cost — flat per-image pricing, so this must be exact
# ---------------------------------------------------------------------------

class TestCostEstimate:

    def test_is_exact_flat_price(self):
        tool = ApiyiGptImage2All()
        assert tool.estimate_cost({"n": 1}) == 0.03
        assert tool.estimate_cost({}) == 0.03
        assert tool.estimate_cost({"n": 5}) == 0.15

    def test_clamps_out_of_range_counts(self):
        tool = ApiyiGptImage2All()
        assert tool.estimate_cost({"n": 0}) == 0.03
        assert tool.estimate_cost({"n": 999}) == 0.30

    def test_survives_garbage_count(self):
        tool = ApiyiGptImage2All()
        assert tool.estimate_cost({"n": "abc"}) == 0.03

    def test_price_constant_is_the_documented_rate(self):
        assert PRICE_PER_IMAGE_USD == 0.03


# ---------------------------------------------------------------------------
# Status / dependencies
# ---------------------------------------------------------------------------

class TestStatus:

    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("APIYI_API_KEY", raising=False)
        from tools.base_tool import ToolStatus
        assert ApiyiGptImage2All().get_status() == ToolStatus.UNAVAILABLE

    def test_available_with_key(self, monkeypatch):
        monkeypatch.setenv("APIYI_API_KEY", "sk-test")
        from tools.base_tool import ToolStatus
        assert ApiyiGptImage2All().get_status() == ToolStatus.AVAILABLE

    def test_declares_env_dependency(self):
        """Registry-driven setup offers read this list."""
        assert "env:APIYI_API_KEY" in ApiyiGptImage2All.dependencies

    def test_unavailable_when_requests_missing(self, monkeypatch):
        monkeypatch.setenv("APIYI_API_KEY", "sk-test")
        monkeypatch.setitem(sys.modules, "requests", None)
        from tools.base_tool import ToolStatus
        assert ApiyiGptImage2All().get_status() == ToolStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Registry contract — this is what makes image_selector find it
# ---------------------------------------------------------------------------

class TestRegistryContract:

    def test_capability_and_provider_strings_are_exact(self):
        tool = ApiyiGptImage2All()
        assert tool.capability == "image_generation"
        assert tool.provider == "apiyi"
        assert tool.name == "apiyi_image"

    def test_discovered_by_capability(self):
        from tools.tool_registry import registry
        registry.discover()
        names = {t.name for t in registry.get_by_capability("image_generation")}
        assert "apiyi_image" in names

    def test_image_selector_lists_it_as_a_provider(self):
        from tools.graphics.image_selector import ImageSelector
        assert "apiyi_image" in ImageSelector().fallback_tools

    def test_output_schema_reports_no_size_or_seed_support(self):
        """Do not advertise capabilities the provider lacks."""
        supports = ApiyiGptImage2All.supports
        assert supports["aspect_ratio"] is False
        assert supports["seed"] is False


# ---------------------------------------------------------------------------
# Execution — no real network, no real billing
# ---------------------------------------------------------------------------

class TestExecute:

    def _tool_with_session(self, fake_requests, responses):
        fake_requests.install(responses)
        return ApiyiGptImage2All()

    def test_text_to_image_round_trip(self, fake_requests, tmp_path):
        out = tmp_path / "cat.png"
        tool = self._tool_with_session(fake_requests, [chat_response(PNG_DATA_URI)])
        result = tool.execute({"prompt": "一只橘猫", "output_path": str(out)})

        assert result.success, result.error
        assert out.is_file() and out.read_bytes() == PNG_BYTES
        assert result.cost_usd == 0.03
        assert result.model == MODEL_ID
        assert result.data["images_generated"] == 1
        assert result.artifacts == [str(out)]

    def test_uses_chat_completions_endpoint_not_images_api(self, fake_requests, tmp_path):
        tool = self._tool_with_session(fake_requests, [chat_response(PNG_DATA_URI)])
        tool.execute({"prompt": "x", "output_path": str(tmp_path / "a.png")})

        call = fake_requests.sessions[-1].calls[0]
        assert call["url"].endswith("/v1/chat/completions")
        assert "/v1/images/" not in call["url"]
        assert call["json"]["model"] == MODEL_ID
        assert call["headers"]["Authorization"] == "Bearer sk-test-key"

    def test_url_response_is_downloaded(self, fake_requests, tmp_path):
        url = "https://r2cdn.copilotbase.com/o/x.png?X-Amz-Signature=abc"
        out = tmp_path / "dl.png"
        tool = self._tool_with_session(fake_requests, [chat_response(f"![i]({url})")])
        result = tool.execute({"prompt": "x", "output_path": str(out)})

        assert result.success, result.error
        assert out.read_bytes() == b"downloaded-bytes"
        assert fake_requests.downloads[0]["url"] == url

    def test_n_images_produce_n_files_and_n_times_cost(self, fake_requests, tmp_path):
        out = tmp_path / "multi.png"
        tool = self._tool_with_session(
            fake_requests, [chat_response(PNG_DATA_URI) for _ in range(3)]
        )
        result = tool.execute({"prompt": "x", "output_path": str(out), "n": 3})

        assert result.success, result.error
        assert result.data["images_generated"] == 3
        assert result.cost_usd == pytest.approx(0.09)
        for idx in (1, 2, 3):
            assert (tmp_path / f"multi_{idx}.png").is_file()

    def test_edit_mode_encodes_local_reference(self, fake_requests, tmp_path):
        ref = tmp_path / "ref.png"
        ref.write_bytes(PNG_BYTES)
        tool = self._tool_with_session(fake_requests, [chat_response(PNG_DATA_URI)])
        result = tool.execute({
            "prompt": "改成油画风格",
            "image_path": str(ref),
            "output_path": str(tmp_path / "edited.png"),
        })

        assert result.success, result.error
        content = fake_requests.sessions[-1].calls[0]["json"]["messages"][0]["content"]
        assert isinstance(content, list)
        image_parts = [p for p in content if p["type"] == "image_url"]
        assert len(image_parts) == 1
        assert image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_local_reference_is_labeled_with_its_real_media_type(self, fake_requests, tmp_path):
        """A JPEG must not be sent as image/png.

        The vendor script hardcodes `data:image/png;base64,` for every input
        regardless of type, which mislabels non-PNG references.
        """
        ref = tmp_path / "photo.jpg"
        ref.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
        tool = self._tool_with_session(fake_requests, [chat_response(PNG_DATA_URI)])
        tool.execute({
            "prompt": "edit",
            "image_path": str(ref),
            "output_path": str(tmp_path / "o.png"),
        })

        content = fake_requests.sessions[-1].calls[0]["json"]["messages"][0]["content"]
        url = [p for p in content if p["type"] == "image_url"][0]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")

    def test_rejects_too_many_input_images(self, fake_requests, tmp_path):
        tool = self._tool_with_session(fake_requests, [])
        paths = []
        for idx in range(6):
            p = tmp_path / f"r{idx}.png"
            p.write_bytes(PNG_BYTES)
            paths.append(str(p))
        result = tool.execute({"prompt": "融合", "image_paths": paths})

        assert result.success is False
        assert "at most 5" in result.error
        # Nothing was sent -- a rejected request must not bill.
        assert fake_requests.sessions == []

    def test_missing_input_image_rejected_before_any_call(self, fake_requests):
        tool = self._tool_with_session(fake_requests, [])
        result = tool.execute({"prompt": "x", "image_path": "/nope/missing.png"})

        assert result.success is False
        assert "not found" in result.error
        assert fake_requests.sessions == []

    def test_missing_prompt_rejected(self, fake_requests):
        tool = self._tool_with_session(fake_requests, [])
        assert ApiyiGptImage2All().execute({"prompt": ""}).success is False

    def test_missing_key_rejected(self, fake_requests, monkeypatch):
        monkeypatch.delenv("APIYI_API_KEY", raising=False)
        result = ApiyiGptImage2All().execute({"prompt": "x"})
        assert result.success is False
        assert "APIYI_API_KEY" in result.error

    def test_http_error_is_reported_not_raised(self, fake_requests, tmp_path):
        tool = self._tool_with_session(
            fake_requests, [FakeResponse(status_code=429, payload={"error": "busy"})]
        )
        result = tool.execute({"prompt": "x", "output_path": str(tmp_path / "x.png")})

        assert result.success is False
        assert "429" in result.error
        assert result.cost_usd == 0.0

    def test_response_without_image_fails_loudly(self, fake_requests, tmp_path):
        """A 200 carrying only prose must not yield an empty file."""
        out = tmp_path / "never.png"
        tool = self._tool_with_session(fake_requests, [chat_response("我无法生成该图片。")])
        result = tool.execute({"prompt": "x", "output_path": str(out)})

        assert result.success is False
        assert "no image" in result.error
        assert not out.exists()

    def test_partial_failure_reports_written_files_and_charges_only_them(
        self, fake_requests, tmp_path
    ):
        """Images already delivered are real and were paid for; say so."""
        out = tmp_path / "p.png"
        tool = self._tool_with_session(
            fake_requests,
            [chat_response(PNG_DATA_URI), FakeResponse(status_code=500, payload={"e": 1})],
        )
        result = tool.execute({"prompt": "x", "output_path": str(out), "n": 2})

        assert result.success is False
        assert result.data["images_generated"] == 1
        assert result.data["requested"] == 2
        assert result.cost_usd == pytest.approx(0.03)
        assert (tmp_path / "p_1.png").is_file()

    def test_invalid_response_format_rejected(self, fake_requests, tmp_path):
        tool = self._tool_with_session(fake_requests, [])
        result = tool.execute({
            "prompt": "x", "response_format": "xml", "output_path": str(tmp_path / "x.png"),
        })
        assert result.success is False
        assert "response_format" in result.error

    def test_non_https_base_url_rejected(self, fake_requests):
        tool = self._tool_with_session(fake_requests, [])
        result = tool.execute({"prompt": "x", "base_url": "http://evil.example.com"})
        assert result.success is False
        assert "https" in result.error

    def test_aspect_ratio_reaches_the_prompt(self, fake_requests, tmp_path):
        tool = self._tool_with_session(fake_requests, [chat_response(PNG_DATA_URI)])
        tool.execute({
            "prompt": "一只猫", "aspect_ratio": "9:16",
            "output_path": str(tmp_path / "v.png"),
        })
        content = fake_requests.sessions[-1].calls[0]["json"]["messages"][0]["content"]
        assert content.startswith("竖版 9:16 手机海报")

    def test_b64_json_response_format_is_forwarded(self, fake_requests, tmp_path):
        tool = self._tool_with_session(fake_requests, [chat_response(PNG_DATA_URI)])
        tool.execute({
            "prompt": "x", "response_format": "b64_json",
            "output_path": str(tmp_path / "b.png"),
        })
        payload = fake_requests.sessions[-1].calls[0]["json"]
        assert payload["response_format"] == {"type": "b64_json"}
