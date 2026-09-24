"""APIYi-hosted Seedance 2.0 video — video generation via api.apiyi.com.

Why this exists
---------------
`.agents/skills/apiyi-seedance2-video-gen/scripts/generate_video.py` can already
produce Seedance video through APIYi, but it is a CLI script: `video_selector`
cannot discover it, so the `assets` stage of every pipeline reported
`video_generation` as unavailable and AI video could only be produced by
hand-invoked subprocesses (which is what the LDWS project did — its
`asset_manifest` names a tool, `apiyi_seedance_video`, that never existed in
this codebase). This module makes that path a first-class tool so the normal
selector-driven flow can route to it.

APIYi is Ark-protocol compatible
--------------------------------
The gateway proxies Volcengine Ark, so `seedance_ark`'s payload building,
response parsing, polling, and media handling all apply unchanged:

    Ark  : {base}/contents/generations/tasks
    APIYi: {base}/seedance/api/v3/contents/generations/tasks

with identical auth (`Authorization: Bearer <key>`) and an identical body
(`{model, content[], duration, ratio, resolution, generate_audio}`) — verified
by comparing this module's payload against the vendor script byte for byte.
Subclassing is therefore reuse, not duplication.

Two provider differences are load-bearing and encoded here:
1. **The gateway lies about gzip.** Its responses carry a gzip
   `content-encoding` that does not match the body, so a stock `requests` call
   dies with `ContentDecodingError`/`IncompleteRead` *before* the real HTTP
   status can be read. The vendor script already worked around this with
   `Accept-Encoding: identity`; the upstream Ark tool does not send that header,
   which is the actual reason it cannot be pointed at APIYi. `_headers()`
   overrides it.
2. **Billing is per-request, not per-token.** APIYi charges a flat price for a
   given (model variant, resolution, duration) instead of metering completion
   tokens, so the inherited token math would understate or overstate cost.
   `estimate_cost_cny()` is replaced with the published rate card.

The gateway also has no cancel route (it answers `DELETE .../tasks/{id}` with a
200 SPA fallback page, byte-identical to a nonexistent path), so `cancel` fails
loudly rather than reporting a success that never happened.
"""

from __future__ import annotations

import math
import os
from typing import Any

from tools.video.seedance_ark import SeedanceArkVideo

# api.apiyi.com is a mainland-reachable gateway in front of Volcengine Ark.
# The `/seedance/api/v3` suffix is what makes the inherited path construction
# land on the same route the vendor script uses.
DEFAULT_BASE_URL = "https://api.apiyi.com/seedance/api/v3"

# Published rate card, CNY per finished clip, for 16:9 at 5 seconds with no
# input video. Every aspect ratio in a resolution tier has the same pixel area,
# so orientation does not change the price — only tier and duration do.
# Source: .agents/skills/apiyi-seedance2-video-gen/references/api-details.md
# (official anchors ¥1.16 / ¥2.50 ... before the gateway's ~1.1x nominal markup).
PRICE_CNY_PER_CLIP = {
    "standard": {"480p": 2.31, "720p": 4.97, "1080p": 12.39},
    "fast": {"480p": 1.86, "720p": 4.00},
    "mini": {"480p": 1.16, "720p": 2.50},
}

# Verified against GET /v1/models on 2026-09-24: this gateway sells exactly
# three Seedance models. It does NOT carry the 2.5 variant that the parent tool
# offers, so `model_variant="2.5"` must be refused locally instead of being
# turned into a request the gateway will reject (a rejected create is not
# billed, but it still costs a round trip and reads as a provider outage).
SUPPORTED_MODEL_VARIANTS = ("standard", "fast", "mini")
REFERENCE_DURATION_SECONDS = 5.0

# Duration bounds differ from Ark's: the gateway rejects 1080p outside
# `standard` and caps every variant at 15s. api-details.md documents 4-15 with
# -1 for "smart duration".
MIN_DURATION_SECONDS = 4
MAX_DURATION_SECONDS = 15
SMART_DURATION = -1

# `adaptive` lets the model choose from the prompt (or the first frame's ratio).
VALID_RESOLUTIONS = ("480p", "720p", "1080p")


class ApiyiSeedanceVideo(SeedanceArkVideo):
    """Seedance 2.0 video through the APIYi gateway (Ark-compatible)."""

    name = "apiyi_seedance_video"
    version = "0.1.0"
    provider = "apiyi"

    # Names this vendor in every inherited error message instead of "Ark".
    # The inherited strings already read "<LABEL> Seedance ...", so this must be
    # just the vendor ("APIYi"), not "APIYi Seedance".
    PROVIDER_LABEL = "APIYi"

    BASE_URL = DEFAULT_BASE_URL

    dependencies = ["env:APIYI_API_SEEDANCE_KEY"]
    install_instructions = (
        "Set APIYI_API_SEEDANCE_KEY to your APIYi token (from api.apiyi.com). "
        "It is a separate key from APIYI_API_KEY, which is scoped to image "
        "generation. Optional: APIYI_SEEDANCE_BASE_URL to point at another "
        "Ark-compatible gateway."
    )
    agent_skills = ["apiyi-seedance2-video-gen", "seedance-2-0", "ai-video-gen"]

    best_for = [
        "mainland-reachable Seedance 2.0 generation without a VPN",
        "the cheapest Seedance tier (mini 480p is about CNY 1.16 per clip)",
        "flat per-clip billing that is known before the paid create",
    ]
    not_good_for = [
        "task cancellation (this gateway exposes no cancel route)",
        "offline generation",
        "unapproved paid generation",
    ]
    fallback_tools = ["seedance_ark", "seedance_video", "seedance_replicate"]

    # ------------------------------------------------------------------
    # OpenMontage-local patch (C1b): APIYi-specific overrides.
    #
    # `video_generation` is unavailable on this machine because the only
    # Seedance routes are Ark/FAL/Replicate keys we do not hold. We DO hold an
    # APIYi key, and this gateway speaks Ark's protocol, so the upstream tool
    # becomes usable once these four differences are handled. Each one is
    # verified against a live (non-billable) request or the vendor reference;
    # none is speculative.
    # ------------------------------------------------------------------

    def _get_api_key(self) -> str | None:
        """Read APIYi's video-scoped token, not Ark's."""
        return os.environ.get("APIYI_API_SEEDANCE_KEY")

    def _get_base_url(self) -> str:
        base_url = os.environ.get("APIYI_SEEDANCE_BASE_URL", self.BASE_URL).rstrip("/")
        if not base_url.startswith("https://"):
            raise ValueError("APIYI_SEEDANCE_BASE_URL must be an https:// URL")
        return base_url

    def _headers(self, api_key: str) -> dict[str, str]:
        """Add the header that makes this gateway's responses decodable.

        Verified 2026-09-24: without `Accept-Encoding: identity` a request to
        this gateway raises `ChunkedEncodingError` / `ContentDecodingError`
        instead of returning a status code, because the gzip header does not
        match the body. The vendor script documents the same workaround.
        """
        return {
            **super()._headers(api_key),
            "Accept-Encoding": "identity",
        }

    def estimate_cost_cny(self, inputs: dict[str, Any]) -> float:
        """Flat per-clip price scaled by duration.

        Deliberately does NOT reuse the parent's token formula: this gateway
        bills per request, so token metering would report a price the user will
        never be charged. Unknown combinations return 0.0 rather than a
        fabricated number, matching the parent's convention for custom models.
        """
        _, variant = self._resolve_model(inputs)
        if variant is None:
            return 0.0
        resolution = str(inputs.get("resolution", "720p")).lower()
        rates = PRICE_CNY_PER_CLIP.get(variant)
        if not rates or resolution not in rates:
            return 0.0
        duration = self._normalize_duration(
            inputs.get("duration", 5), MAX_DURATION_SECONDS
        )
        # Smart duration is resolved server-side; assume the 5s reference so the
        # estimate is never quoted as cheaper than it can turn out to be.
        effective = (
            REFERENCE_DURATION_SECONDS if duration == SMART_DURATION else float(duration)
        )
        return round(rates[resolution] * effective / REFERENCE_DURATION_SECONDS, 4)

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        cny_per_usd = self._get_cny_per_usd()
        return round(self.estimate_cost_cny(inputs) / cny_per_usd, 4)

    def _normalize_duration(self, value: Any, max_seconds: int = 15) -> int:
        """Clamp to the gateway's documented 4-15s window.

        The parent allows up to 30s for variant 2.5; this gateway caps at 15 and
        its API rejects the rest with HTTP 400.
        """
        if value == "auto":
            return SMART_DURATION
        duration = super()._normalize_duration(value, MAX_DURATION_SECONDS)
        if duration == SMART_DURATION:
            return duration
        if duration < MIN_DURATION_SECONDS:
            raise ValueError(
                f"duration must be between {MIN_DURATION_SECONDS} and "
                f"{MAX_DURATION_SECONDS} seconds, or -1/auto for smart duration"
            )
        return duration

    def _resolve_model(self, inputs: dict[str, Any]) -> tuple[str, str | None]:
        """Reject the parent's 2.5 variant, which this gateway does not sell.

        Verified 2026-09-24 against GET /v1/models: only the 2.0 standard, fast,
        and mini models exist here. Letting 2.5 through would send a request for
        a model the gateway answers with 403 — and because the parent prices an
        unknown custom model at 0.0 unless a manual rate is supplied, the user
        would see a "free" estimate for a call that cannot succeed.

        1080p needs no extra guard here: the parent already refuses it for
        fast/mini, and an out-of-family custom endpoint id is the caller's
        explicit choice.
        """
        variant = str(inputs.get("model_variant", "standard")).lower()
        if variant not in SUPPORTED_MODEL_VARIANTS and not inputs.get("model"):
            raise ValueError(
                "model_variant must be one of "
                f"{', '.join(SUPPORTED_MODEL_VARIANTS)} on this gateway "
                "(the 2.5 variant is not offered by APIYi; pass an explicit "
                "`model` only if you have an account-specific endpoint id)"
            )
        return super()._resolve_model(inputs)

    def _build_payload(self, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = super()._build_payload(inputs)
        # The parent always sends `return_last_frame: false`; the vendor script
        # for this gateway omits the key unless it is requested. Matching the
        # vendor body exactly keeps us on the request shape that is already
        # known to work here, rather than assuming this proxy tolerates extra
        # fields (an untested assumption the request-shape comparison flagged).
        if payload.get("return_last_frame") is False:
            payload.pop("return_last_frame", None)
        return payload

    def _cost_from_task_cny(
        self, task: dict[str, Any], inputs: dict[str, Any]
    ) -> float | None:
        """Reuse the pre-create flat estimate as the post-create actual.

        This gateway does not return billable `usage.completion_tokens`, so the
        inherited reader returns None (cost unknown). The flat price is exact
        for the accepted request, so report that instead of "unknown".
        """
        flat = self.estimate_cost_cny(
            {**inputs, "resolution": task.get("resolution") or inputs.get("resolution")}
        )
        return flat if flat > 0 else None

    def _cancel_task(self, task_id: str, api_key: str) -> None:
        """Refuse to claim a cancellation this gateway cannot perform.

        Verified: `DELETE .../tasks/{id}` returns HTTP 200 with the front-end
        SPA page — byte-identical to a path that does not exist — so the
        inherited implementation (which only checks for a 2xx) would report
        `status: cancel_requested` for a task that keeps running and keeps
        billing. Failing loudly is the honest behaviour.
        """
        raise RuntimeError(
            "APIYi has no task-cancel route (DELETE returns the SPA fallback "
            "page, not an API response). Let the task finish and use "
            "task_action='query' with the task_id, or simply stop polling — "
            "the task is already pre-charged and will not be refunded."
        )

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["apiyi_notes"] = {
            "billing": "flat per clip (not token-metered); pre-charged at create",
            "cancel_supported": False,
            "price_cny_per_clip": {
                variant: dict(rates) for variant, rates in PRICE_CNY_PER_CLIP.items()
            },
            "reference_price_note": (
                f"Reference prices are 16:9 at {REFERENCE_DURATION_SECONDS:g}s with "
                "no input video; orientation does not change price."
            ),
            "duration_range_seconds": [MIN_DURATION_SECONDS, MAX_DURATION_SECONDS],
            "smart_duration": SMART_DURATION,
            "gzip_workaround": "Accept-Encoding: identity (gateway header/body mismatch)",
        }
        return info

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        # Observed: mini clips land in roughly 1.5-2.5 minutes.
        return 150.0
