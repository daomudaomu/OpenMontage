"""Contract tests for the APIYi-hosted Seedance 2.0 video provider.

These tests never touch the network. `tests/conftest.py` blocks outbound
sockets session-wide, and anything that would perform a real request is
exercised through a fake `requests` module -- which matters more here than
anywhere else in the suite, because a successful create is **pre-charged and
non-refundable** (~CNY 1.16 for the cheapest tier).

The module exists to make an already-working CLI path first-class, so several
tests pin the *differences* from the upstream Ark tool that it subclasses.
Each difference was observed on the live gateway rather than assumed:

1. The gateway's gzip `content-encoding` does not match its body, so a stock
   `requests` call raises a decoding error instead of returning a status. The
   fix is `Accept-Encoding: identity`, which the upstream tool does not send --
   that omission is the whole reason it cannot be pointed at APIYi.
2. Billing is flat per clip, not per completion token, so the inherited token
   math would quote a price the user is never charged.
3. There is no cancel route: `DELETE .../tasks/{id}` returns a 200 SPA
   fallback page, byte-identical to a nonexistent path, so the inherited
   implementation would report a cancellation that never happened.
4. The request body must match the vendor script exactly. The parent sends
   `return_last_frame: false`; the vendor omits the key, and the proxy's
   tolerance for extra fields is untested.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from tools.video.apiyi_seedance_video import (
    DEFAULT_BASE_URL,
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    PRICE_CNY_PER_CLIP,
    SMART_DURATION,
    SUPPORTED_MODEL_VARIANTS,
    ApiyiSeedanceVideo,
)
from tools.video.seedance_ark import SeedanceArkVideo

APIYI_KEY = "apiyi-seedance-test-key"


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("APIYI_API_SEEDANCE_KEY", APIYI_KEY)
    monkeypatch.delenv("APIYI_SEEDANCE_BASE_URL", raising=False)
    return ApiyiSeedanceVideo()


def _fake_requests(monkeypatch, handler):
    """Install a fake `requests` module whose session method calls handler."""
    calls = []

    class _Response:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text or (json.dumps(payload) if payload else "")
            self.headers: dict[str, str] = {}
            self.content = self.text.encode()

        def json(self):
            if self._payload is None:
                raise ValueError("no json body")
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"{self.status_code} Client Error")

    def _request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return handler(method, url, kwargs)

    module = types.ModuleType("requests")
    module.post = lambda url, **kw: _request("POST", url, **kw)
    module.get = lambda url, **kw: _request("GET", url, **kw)
    module.delete = lambda url, **kw: _request("DELETE", url, **kw)
    module.RequestException = RuntimeError
    monkeypatch.setitem(sys.modules, "requests", module)
    return calls


# ------------------------------------------------------------------
# Identity, registration, provider routing
# ------------------------------------------------------------------


def test_identity_differs_from_the_ark_tool():
    assert ApiyiSeedanceVideo.name == "apiyi_seedance_video"
    assert SeedanceArkVideo.name == "seedance_ark"
    assert ApiyiSeedanceVideo.provider == "apiyi"
    assert SeedanceArkVideo.provider == "ark"
    # Subclassing is the point: same protocol, so reuse the Ark implementation.
    assert issubclass(ApiyiSeedanceVideo, SeedanceArkVideo)


def test_requires_its_own_key_not_the_image_key(monkeypatch):
    """APIYi scopes keys per product; the image key cannot create video."""
    monkeypatch.delenv("APIYI_API_SEEDANCE_KEY", raising=False)
    monkeypatch.setenv("APIYI_API_KEY", "image-key-only")
    assert ApiyiSeedanceVideo()._get_api_key() is None
    assert "APIYI_API_SEEDANCE_KEY" in ApiyiSeedanceVideo.dependencies[0]

    monkeypatch.setenv("APIYI_API_SEEDANCE_KEY", APIYI_KEY)
    assert ApiyiSeedanceVideo()._get_api_key() == APIYI_KEY


def test_registered_as_a_video_generation_provider():
    """The entire point of the module: `video_selector` must find it.

    Before this existed, `video_generation` reported 0 usable providers on a
    machine that holds a working APIYi key, and the LDWS project had to call
    the vendor CLI by hand.
    """
    from tools.tool_registry import registry

    registry.discover()
    tool = registry._tools.get("apiyi_seedance_video")
    assert tool is not None, "apiyi_seedance_video was not discovered"
    assert tool.capability == "video_generation"
    assert "apiyi" in {
        t.provider
        for t in registry.get_by_capability("video_generation")
        if t.get_status().value == "available"
    }


def test_provider_label_names_the_real_vendor():
    """Errors must not send the reader to Volcengine for an APIYi call."""
    assert ApiyiSeedanceVideo.PROVIDER_LABEL == "APIYi"
    assert SeedanceArkVideo.PROVIDER_LABEL == "Ark"
    # The inherited messages read "<LABEL> Seedance ...", so the label must be
    # the vendor alone or the text reads "APIYi Seedance Seedance ...".
    assert not ApiyiSeedanceVideo.PROVIDER_LABEL.endswith("Seedance")


# ------------------------------------------------------------------
# The gzip workaround -- the actual reason the Ark tool cannot reach APIYi
# ------------------------------------------------------------------


def test_headers_request_identity_encoding(provider):
    headers = provider._headers(APIYI_KEY)
    assert headers["Accept-Encoding"] == "identity"
    assert headers["Authorization"] == f"Bearer {APIYI_KEY}"
    assert headers["Content-Type"] == "application/json"


def test_headers_fix_is_the_difference_from_upstream(provider):
    """Upstream omits the header, which is why it fails on this gateway."""
    assert "Accept-Encoding" not in SeedanceArkVideo()._headers(APIYI_KEY)


def test_create_sends_identity_encoding(provider, monkeypatch):
    calls = _fake_requests(
        monkeypatch,
        lambda m, u, k: type(
            "R", (), {
                "status_code": 200,
                "text": json.dumps({"id": "cgt-abc123"}),
                "headers": {},
                "json": lambda self: {"id": "cgt-abc123"},
                "raise_for_status": lambda self: None,
            },
        )(),
    )
    result = provider.execute(
        {
            "task_action": "create",
            "prompt": "a city skyline at dusk",
            "model_variant": "mini",
            "resolution": "480p",
            "duration": 4,
        }
    )
    assert result.success, result.error
    assert calls and calls[0]["method"] == "POST"
    assert calls[0]["kwargs"]["headers"]["Accept-Encoding"] == "identity"


# ------------------------------------------------------------------
# Endpoint shape: the Ark protocol on a gateway prefix
# ------------------------------------------------------------------


def test_base_url_targets_the_gateway_prefix(provider):
    assert provider._get_base_url() == DEFAULT_BASE_URL
    assert DEFAULT_BASE_URL.startswith("https://api.apiyi.com/")


def test_create_url_places_the_gateway_suffix_before_ark_route(provider):
    payload = provider.dry_run(
        {"operation": "text_to_video", "prompt": "x", "duration": 4}
    )
    assert payload["api_contract"]["create"] == (
        f"POST {DEFAULT_BASE_URL}/contents/generations/tasks"
    )


def test_base_url_override_must_be_https(provider, monkeypatch):
    monkeypatch.setenv("APIYI_SEEDANCE_BASE_URL", "http://insecure.example")
    with pytest.raises(ValueError, match="https://"):
        provider._get_base_url()
    monkeypatch.setenv("APIYI_SEEDANCE_BASE_URL", "https://other.example/api/v3/")
    assert provider._get_base_url() == "https://other.example/api/v3"


# ------------------------------------------------------------------
# Flat per-clip pricing (NOT the inherited token formula)
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant,resolution,duration,expected",
    [
        ("mini", "480p", 5, 1.16),
        ("mini", "720p", 5, 2.50),
        ("fast", "480p", 5, 1.86),
        ("fast", "720p", 5, 4.00),
        ("standard", "480p", 5, 2.31),
        ("standard", "720p", 5, 4.97),
        ("standard", "1080p", 5, 12.39),
        # Scaled linearly by duration off the 5s anchor.
        ("mini", "480p", 4, 0.928),
        ("mini", "480p", 10, 2.32),
    ],
)
def test_flat_price_matches_the_published_rate_card(
    provider, variant, resolution, duration, expected
):
    got = provider.estimate_cost_cny(
        {"model_variant": variant, "resolution": resolution, "duration": duration}
    )
    assert got == pytest.approx(expected, abs=1e-4)


def test_price_does_not_use_the_token_formula(provider):
    """A regression guard: the parent's token math gives a different number.

    If this ever matches, someone reverted to the inherited implementation and
    the quoted cost no longer reflects what the gateway charges.
    """
    inputs = {"model_variant": "mini", "resolution": "480p", "duration": 4}
    assert provider.estimate_cost_cny(inputs) == pytest.approx(0.928, abs=1e-4)
    assert SeedanceArkVideo().estimate_cost_cny(inputs) != pytest.approx(
        0.928, abs=1e-4
    )


def test_smart_duration_is_priced_at_the_reference_not_free(provider):
    """-1 means 'model decides'; quoting it as 0 would understate the cost."""
    assert provider.estimate_cost_cny(
        {"model_variant": "mini", "resolution": "480p", "duration": SMART_DURATION}
    ) == pytest.approx(1.16, abs=1e-4)


def test_unknown_combination_returns_zero_not_a_fabricated_price(provider):
    # 1080p is not sold with mini.
    assert provider.estimate_cost_cny(
        {"model_variant": "mini", "resolution": "1080p", "duration": 5}
    ) == 0.0


def test_cost_is_reported_in_usd_too(provider):
    usd = provider.estimate_cost(
        {"model_variant": "mini", "resolution": "480p", "duration": 5}
    )
    assert usd > 0


def test_actual_cost_falls_back_to_the_flat_price(provider):
    """This gateway returns no token usage, so 'unknown' would be wrong."""
    cny = provider._cost_from_task_cny(
        {"resolution": "480p"},
        {"model_variant": "mini", "resolution": "480p", "duration": 5},
    )
    assert cny == pytest.approx(1.16, abs=1e-4)


# ------------------------------------------------------------------
# Duration and resolution constraints
# ------------------------------------------------------------------


def test_duration_window_is_4_to_15(provider):
    assert MIN_DURATION_SECONDS == 4
    assert MAX_DURATION_SECONDS == 15
    for bad in (3, 16, 30, 0):
        with pytest.raises(ValueError):
            provider._normalize_duration(bad, MAX_DURATION_SECONDS)
    assert provider._normalize_duration(15, MAX_DURATION_SECONDS) == 15
    assert provider._normalize_duration("auto", MAX_DURATION_SECONDS) == SMART_DURATION
    assert provider._normalize_duration(-1, MAX_DURATION_SECONDS) == SMART_DURATION


def test_1080p_is_rejected_for_fast_and_mini_before_the_paid_post(provider):
    """The parent refuses 1080p for fast/mini; nothing should reach the gateway."""
    for variant in ("mini", "fast"):
        with pytest.raises(ValueError):
            provider._build_payload(
                {
                    "operation": "text_to_video",
                    "prompt": "x",
                    "model_variant": variant,
                    "resolution": "1080p",
                    "duration": 5,
                }
            )
    # standard is allowed.
    payload = provider._build_payload(
        {
            "operation": "text_to_video",
            "prompt": "x",
            "model_variant": "standard",
            "resolution": "1080p",
            "duration": 5,
        }
    )
    assert payload["resolution"] == "1080p"


def test_2_5_variant_is_refused_locally(provider):
    """APIYi sells only the 2.0 standard/fast/mini models.

    Verified against GET /v1/models. Inheriting the parent's 2.5 variant would
    request a model this gateway answers with 403, while the parent's cost
    estimator reports an unknown custom model as 0.0 -- so the user would be
    shown a "free" estimate for a request that cannot succeed.
    """
    with pytest.raises(ValueError, match="model_variant must be one of"):
        provider._build_payload(
            {
                "operation": "text_to_video",
                "prompt": "x",
                "model_variant": "2.5",
                "resolution": "720p",
                "duration": 5,
            }
        )


def test_supported_variants_match_the_gateway_catalogue(provider):
    assert set(SUPPORTED_MODEL_VARIANTS) == {"standard", "fast", "mini"}
    assert "2.5" not in SUPPORTED_MODEL_VARIANTS
    for variant in SUPPORTED_MODEL_VARIANTS:
        payload = provider._build_payload(
            {
                "operation": "text_to_video",
                "prompt": "x",
                "model_variant": variant,
                "resolution": "720p",
                "duration": 5,
            }
        )
        assert payload["model"] == ApiyiSeedanceVideo.MODEL_IDS[variant]


def test_explicit_model_id_still_allows_a_custom_endpoint(provider):
    """An account-specific endpoint id is the caller's explicit choice."""
    payload = provider._build_payload(
        {
            "operation": "text_to_video",
            "prompt": "x",
            "model": "ep-20250101-abc123",
            "model_variant": "2.5",
            "resolution": "720p",
            "duration": 5,
        }
    )
    assert payload["model"] == "ep-20250101-abc123"


# ------------------------------------------------------------------
# Request body must match the verified vendor script
# ------------------------------------------------------------------


def test_payload_omits_return_last_frame_when_false(provider):
    payload = provider._build_payload(
        {
            "operation": "text_to_video",
            "prompt": "x",
            "model_variant": "mini",
            "resolution": "480p",
            "duration": 4,
        }
    )
    assert "return_last_frame" not in payload
    # ...but an explicit request is still honoured.
    requested = provider._build_payload(
        {
            "operation": "text_to_video",
            "prompt": "x",
            "model_variant": "mini",
            "resolution": "480p",
            "duration": 4,
            "return_last_frame": True,
        }
    )
    assert requested["return_last_frame"] is True


def test_payload_matches_the_vendor_script_exactly(provider):
    """Byte-level parity with the script whose requests are known to succeed."""
    import importlib.util
    from pathlib import Path

    script_path = (
        Path(__file__).resolve().parents[2]
        / ".agents/skills/apiyi-seedance2-video-gen/scripts/generate_video.py"
    )
    if not script_path.is_file():
        pytest.skip("vendor script not present")

    spec = importlib.util.spec_from_file_location("_gv", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class _Args:
        prompt = "a city skyline at dusk"
        model = "mini"
        resolution = "480p"
        duration = "4"
        ratio = "16:9"
        no_audio = False
        watermark = False
        seed = None
        first_frame = None
        last_frame = None
        reference_image = None
        reference_video = None
        reference_audio = None
        return_last_frame = False
        execution_expires_after = None

    vendor = module.build_body(_Args())
    ours = provider._build_payload(
        {
            "operation": "text_to_video",
            "prompt": _Args.prompt,
            "model_variant": "mini",
            "resolution": "480p",
            "duration": 4,
            "aspect_ratio": "16:9",
        }
    )
    assert ours == vendor


# ------------------------------------------------------------------
# Cancel is impossible on this gateway
# ------------------------------------------------------------------


def test_cancel_fails_loudly_instead_of_claiming_success(provider):
    """The inherited code checks only for 2xx, and this route returns 200 HTML.

    Reporting `cancel_requested` would leave the user believing a task stopped
    while it keeps running and its charge stands.
    """
    with pytest.raises(RuntimeError, match="no task-cancel route"):
        provider._cancel_task("cgt-abc", APIYI_KEY)


def test_cancel_never_sends_a_request(provider, monkeypatch):
    calls = _fake_requests(monkeypatch, lambda m, u, k: None)
    result = provider.execute({"task_action": "cancel", "task_id": "cgt-abc"})
    assert result.success is False
    assert not calls, "cancel must not issue a DELETE on this gateway"


def test_cancel_limitation_is_advertised(provider):
    info = provider.get_info()
    assert info["apiyi_notes"]["cancel_supported"] is False
    assert "task_cancel" in (ApiyiSeedanceVideo.capabilities or [])


# ------------------------------------------------------------------
# dry_run must never submit
# ------------------------------------------------------------------


def test_dry_run_never_posts(provider, monkeypatch):
    calls = _fake_requests(monkeypatch, lambda m, u, k: pytest.fail("network call"))
    payload = provider.dry_run(
        {
            "operation": "text_to_video",
            "prompt": "x",
            "model_variant": "mini",
            "resolution": "480p",
            "duration": 4,
        }
    )
    assert payload["valid"] is True
    assert payload["would_execute"] is False
    assert payload["paid_submission"] is False
    assert calls == []


def test_dry_run_reports_the_flat_price_and_gateway_url(provider):
    payload = provider.dry_run(
        {
            "operation": "text_to_video",
            "prompt": "x",
            "model_variant": "mini",
            "resolution": "480p",
            "duration": 4,
        }
    )
    assert payload["estimated_cost_cny"] == pytest.approx(0.928, abs=1e-4)
    assert "api.apiyi.com" in payload["api_contract"]["create"]
    assert payload["model"] == "doubao-seedance-2-0-mini-260615"


def test_get_info_documents_the_gateway_quirks(provider):
    notes = provider.get_info()["apiyi_notes"]
    assert "identity" in notes["gzip_workaround"]
    assert notes["duration_range_seconds"] == [4, 15]
    assert notes["smart_duration"] == -1
    assert "pre-charged" in notes["billing"]
    assert notes["price_cny_per_clip"]["mini"]["480p"] == 1.16
