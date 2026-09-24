"""APIYi GPT Image 2 All — image generation and editing via api.apiyi.com.

This provider is registered as a first-class OpenMontage tool instead of being
invoked as a CLI script, so `image_selector` can discover it and the asset
stage can route to it without an ad-hoc subprocess.  The logic mirrors
`.agents/skills/apiyi-gpt-image-2-all-gen/scripts/generate_image.py` but runs
in-process, which keeps failures as ToolResult errors rather than lost exit
codes and stderr.

Two provider quirks are load-bearing and encoded here rather than assumed:

1. The image is produced through the **chat completions** endpoint
   (`/v1/chat/completions`), not `/v1/images/*`.  The result arrives as a
   markdown/`data:` reference inside `choices[0].message.content` and must be
   parsed out of that text.
2. There is **no `size` parameter**.  Aspect ratio is steered only by the
   prompt, so `aspect_ratio` is translated into a leading prompt phrase using
   the wording the vendor skill documents as reliable.
"""

from __future__ import annotations

import base64
import os
import re
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

# api.apiyi.com is an APIYi-branded proxy for this model.  $0.03/image is a
# flat per-call price (not token-metered), so cost is exact rather than an
# estimate -- see references/size-guide.md and the vendor SKILL.md.
PRICE_PER_IMAGE_USD = 0.03
DEFAULT_BASE_URL = "https://api.apiyi.com"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
MODEL_ID = "gpt-image-2-all"
MAX_INPUT_IMAGES = 5
SUPPORTED_RESPONSE_FORMATS = ("url", "b64_json")

# The model has no `size` argument; these phrases are the documented way to
# request a framing, applied at the START of the prompt where adherence is
# highest (references/size-guide.md).
ASPECT_RATIO_PHRASES = {
    "1:1": "1:1 方形构图",
    "16:9": "横版 16:9 电影画幅",
    "9:16": "竖版 9:16 手机海报",
    "21:9": "横幅 21:9 超宽银幕",
    "4:3": "4:3 标准画幅",
    "3:2": "3:2 经典画幅",
}

# Extraction patterns.  Both are deliberately conservative:
#
# * The URL pattern must NOT stop at the file extension.  APIYi returns signed
#   R2 CDN links whose query string carries the signature; truncating at `.png`
#   yields a 403 and looks like a CDN fault rather than a parsing bug.
# * The data-URI pattern must NOT absorb trailing prose.  `[A-Za-z0-9+/=\s]+`
#   would happily eat the space and the words after the payload, producing a
#   "clean" match that fails to base64-decode.  Base64 has no spaces, so
#   excluding whitespace is both correct and sufficient.
_URL_RE = re.compile(
    r"https?://[^\s)\"'<>\[\]]+?\.(?:png|jpg|jpeg|webp)(?:\?[^\s)\"'<>\[\]]*)?",
    re.IGNORECASE,
)
_DATA_URI_RE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+")


def extract_image_reference(content: Any) -> str | None:
    """Pull the first image reference out of a chat-completion message body.

    Returns either an ``http(s)`` URL or a ``data:`` URI, or None when the
    response carries no recognisable image.  Kept module-level and pure so it
    is directly testable without any network access.
    """
    text = _content_to_text(content)
    if not text:
        return None
    match = _DATA_URI_RE.search(text)
    if match:
        return match.group(0)
    match = _URL_RE.search(text)
    if match:
        return match.group(0)
    return None


def _content_to_text(content: Any) -> str:
    """Flatten a message ``content`` that may be a string or a parts list."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        # Non-standard, but some OpenAI-compatible gateways return a single
        # part object instead of a list of parts.
        return _content_to_text([content])
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # Multimodal part shapes vary: {"text": ...} or {"image_url": {...}}.
                for key in ("text", "url"):
                    value = item.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                image_url = item.get("image_url")
                if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
                    parts.append(image_url["url"])
                elif isinstance(image_url, str):
                    parts.append(image_url)
        return "\n".join(parts)
    return ""


def apply_aspect_ratio(prompt: str, aspect_ratio: str | None) -> str:
    """Prefix the prompt with the documented framing phrase for a ratio.

    Only touches the prompt when a ratio is explicitly requested and the
    prompt does not already mention a framing -- rewriting a prompt that
    already specifies one would fight the caller's intent.
    """
    if not aspect_ratio:
        return prompt
    phrase = ASPECT_RATIO_PHRASES.get(str(aspect_ratio).strip())
    if not phrase:
        return prompt
    head = prompt[:120]
    if any(token in head for token in ("16:9", "9:16", "1:1", "21:9", "4:3", "3:2")):
        return prompt
    return f"{phrase}，{prompt.lstrip()}"


def mime_to_extension(mime: str | None) -> str:
    """Map a data-URI mime type to a file extension."""
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get((mime or "").lower(), ".png")


# Inverse of mime_to_extension, used when encoding a local file as a data URI.
_EXTENSION_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def extension_to_mime(suffix: str | None) -> str:
    """Map a filename suffix to a media type for a data URI."""
    return _EXTENSION_TO_MIME.get((suffix or "").lower(), "image/png")


def image_bytes_from_reference(reference: str) -> tuple[bytes, str]:
    """Decode a ``data:`` URI, or fetch an ``http(s)`` URL into bytes.

    Returns (payload, extension).  Network access happens only in the URL
    branch, so callers handling a data URI never touch the socket layer.
    """
    if reference.startswith("data:"):
        header, _, payload = reference.partition(",")
        mime = header[5:].split(";", 1)[0] if header.startswith("data:") else ""
        return base64.b64decode(payload), mime_to_extension(mime)

    import requests

    response = requests.get(reference, timeout=120)
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"download failed with HTTP {response.status_code}")
    content_type = (response.headers or {}).get("Content-Type", "")
    extension = mime_to_extension(content_type.split(";", 1)[0].strip())
    if extension == ".png":
        suffix = Path(reference.split("?")[0]).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            extension = ".jpg" if suffix == ".jpeg" else suffix
    return response.content, extension


class ApiyiGptImage2All(BaseTool):
    name = "apiyi_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "apiyi"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["env:APIYI_API_KEY"]
    install_instructions = (
        "Set APIYI_API_KEY to your APIYi token (https://api.apiyi.com).\n"
        "  export APIYI_API_KEY=...   # or add APIYI_API_KEY=... to .env\n"
        "Image generation is billed per call at a flat $0.03/image."
    )
    agent_skills = ["apiyi-gpt-image-2-all-gen"]

    capabilities = ["generate_image", "text_to_image", "image_edit", "multi_image_fusion"]
    supports = {
        "text_to_image": True,
        "image_edit": True,
        "multi_image_fusion": True,
        "native_chinese_prompt": True,
        "text_in_image": True,
        # No `size` parameter exists; framing is prompt-steered only, so this
        # is deliberately False rather than pretending exact sizes are honored.
        "aspect_ratio": False,
        "multiple_outputs": True,
        "seed": False,
    }
    best_for = [
        "cheapest per-image generation at a flat $0.03/call",
        "Chinese-language prompts used verbatim",
        "image editing and multi-image fusion from local files",
    ]
    not_good_for = [
        "exact output dimensions (no size parameter exists)",
        "reproducible results (no seed parameter)",
        "text-to-video or motion output",
    ]
    fallback_tools = ["openai_image", "flux_image", "dashscope_image"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "n": {"type": "integer", "default": 1, "minimum": 1, "maximum": 10},
            "output_path": {"type": "string"},
            "response_format": {
                "type": "string",
                "enum": list(SUPPORTED_RESPONSE_FORMATS),
                "default": "url",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": sorted(ASPECT_RATIO_PHRASES),
                "description": (
                    "Prompt-steered framing hint. The provider has no size "
                    "parameter, so this only prepends documented wording."
                ),
            },
            "generation_mode": {"type": "string", "enum": ["generate", "edit"]},
            "image_path": {"type": "string"},
            "image_paths": {"type": "array", "items": {"type": "string"}},
            "image_url": {"type": "string"},
            "image_urls": {"type": "array", "items": {"type": "string"}},
            "base_url": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 300, "minimum": 1},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, backoff_seconds=2.0, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "aspect_ratio", "generation_mode"]
    side_effects = ["writes image file(s) to output_path", "calls api.apiyi.com"]
    user_visible_verification = ["Inspect generated image for relevance and quality"]

    # ---- helpers -------------------------------------------------------

    def _base_url(self, inputs: dict[str, Any]) -> str:
        base = inputs.get("base_url") or os.environ.get("APIYI_BASE_URL") or DEFAULT_BASE_URL
        base = str(base).rstrip("/")
        if not base.startswith("https://"):
            raise ValueError("APIYi base_url must be an https:// URL")
        return base

    @staticmethod
    def _input_images(inputs: dict[str, Any]) -> list[str]:
        """Collect the caller's reference images, local paths or URLs."""
        images: list[str] = []
        for key in ("image_paths", "image_urls"):
            value = inputs.get(key)
            if isinstance(value, (list, tuple)):
                images.extend(str(item) for item in value if item)
        for key in ("image_path", "image_url"):
            value = inputs.get(key)
            if value:
                images.append(str(value))
        # De-duplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for item in images:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    @staticmethod
    def _output_paths(output_path: str | None, count: int, extension: str) -> list[Path]:
        """Derive one path per image, mirroring openai_image's convention."""
        ext = extension if extension.startswith(".") else f".{extension}"
        if not output_path:
            return [Path(f"apiyi_image_{idx + 1}{ext}") for idx in range(count)]
        path = Path(output_path)
        suffix = path.suffix or ext
        if count == 1:
            return [path if path.suffix else path.with_suffix(suffix)]
        base = path.with_suffix("") if path.suffix else path
        return [base.parent / f"{base.name}_{idx + 1}{suffix}" for idx in range(count)]

    def _build_content(self, inputs: dict[str, Any]) -> Any:
        """Build the chat `content` value: a bare string, or a parts list."""
        prompt = apply_aspect_ratio(
            str(inputs["prompt"]), inputs.get("aspect_ratio")
        )
        images = self._input_images(inputs)
        if not images:
            return prompt
        if len(images) > MAX_INPUT_IMAGES:
            raise ValueError(
                f"at most {MAX_INPUT_IMAGES} input images are supported; got {len(images)}"
            )

        parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for reference in images:
            if reference.startswith(("http://", "https://", "data:")):
                data_url = reference
            else:
                path = Path(reference)
                if not path.is_file():
                    raise FileNotFoundError(f"input image not found: {reference}")
                payload = base64.b64encode(path.read_bytes()).decode("ascii")
                # Label the real media type.  Hardcoding image/png (as the
                # vendor script does) mislabels JPEG/WebP references, which the
                # API may reject or decode incorrectly.
                data_url = f"data:{extension_to_mime(path.suffix)};base64,{payload}"
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
        return parts

    # ---- contract ------------------------------------------------------

    def get_status(self):
        """AVAILABLE only when a key is present and `requests` is importable.

        `requests` is a declared project dependency, but the vendor skill
        advertises this provider as dependency-free; checking explicitly turns
        a missing package into a clear UNAVAILABLE instead of an ImportError
        at generation time.
        """
        from tools.base_tool import ToolStatus

        if not os.environ.get("APIYI_API_KEY"):
            return ToolStatus.UNAVAILABLE
        try:
            import requests  # noqa: F401
        except ImportError:
            return ToolStatus.UNAVAILABLE
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        """Exact flat per-image price -- not a token estimate."""
        try:
            count = int(inputs.get("n", 1) or 1)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(count, 10))
        return round(PRICE_PER_IMAGE_USD * count, 4)

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        try:
            count = max(1, int(inputs.get("n", 1) or 1))
        except (TypeError, ValueError):
            count = 1
        # Vendor-reported 60-300s per image; a mid-range per-image estimate.
        return float(count * 120)

    def _generate_one(
        self, session: Any, url: str, headers: dict[str, str], payload: dict[str, Any],
        timeout: int,
    ) -> str:
        """Issue one generation call and return the image reference."""
        response = session.post(url, headers=headers, json=payload, timeout=timeout)
        if response.status_code < 200 or response.status_code >= 300:
            detail = (response.text or "")[:500]
            raise RuntimeError(f"HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"response was not JSON: {(response.text or '')[:300]}") from None

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"response contained no choices: {str(data)[:300]}")
        message = choices[0].get("message") or {}
        reference = extract_image_reference(message.get("content"))
        if not reference:
            raise RuntimeError(
                f"no image found in response content: {str(message.get('content'))[:300]}"
            )
        return reference

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = os.environ.get("APIYI_API_KEY")
        if not api_key:
            return ToolResult(success=False, error="APIYI_API_KEY not set. " + self.install_instructions)

        if not inputs.get("prompt"):
            return ToolResult(success=False, error="prompt is required")

        try:
            base_url = self._base_url(inputs)
            content = self._build_content(inputs)
        except (ValueError, FileNotFoundError) as exc:
            return ToolResult(success=False, error=str(exc))

        response_format = str(inputs.get("response_format", "url"))
        if response_format not in SUPPORTED_RESPONSE_FORMATS:
            return ToolResult(
                success=False,
                error=f"response_format must be one of {SUPPORTED_RESPONSE_FORMATS}",
            )

        try:
            count = max(1, min(int(inputs.get("n", 1) or 1), 10))
        except (TypeError, ValueError):
            count = 1

        timeout = int(inputs.get("timeout_seconds", 300) or 300)
        url = base_url + CHAT_COMPLETIONS_PATH
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": content}],
        }
        if response_format == "b64_json":
            payload["response_format"] = {"type": "b64_json"}

        import requests

        session = requests.Session()
        started = time.time()
        outputs: list[str] = []
        references: list[str] = []
        try:
            for index in range(count):
                reference = self._generate_one(session, url, headers, payload, timeout)
                references.append(reference)
                raw, extension = image_bytes_from_reference(reference)
                if not raw:
                    raise RuntimeError("decoded image payload was empty")
                if count == 1:
                    out_path = self._output_paths(
                        inputs.get("output_path"), 1, extension
                    )[0]
                else:
                    # Decide paths once, from the first image's real extension.
                    targets = self._output_paths(inputs.get("output_path"), count, extension)
                    out_path = targets[index]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(raw)
                outputs.append(str(out_path))
        except Exception as exc:
            # Report partial success honestly: images already written are real,
            # and the caller paid for them.
            return ToolResult(
                success=False,
                data={
                    "provider": self.provider,
                    "model": MODEL_ID,
                    "partial_outputs": outputs,
                    "images_generated": len(outputs),
                    "requested": count,
                },
                artifacts=outputs,
                error=f"APIYi image generation failed: {exc}",
                cost_usd=round(PRICE_PER_IMAGE_USD * len(outputs), 4),
                duration_seconds=round(time.time() - started, 2),
                model=MODEL_ID,
            )

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": MODEL_ID,
                "prompt": inputs["prompt"],
                "output": outputs[0],
                "outputs": outputs,
                "images_generated": len(outputs),
                "response_format": response_format,
                "references": references,
                "cost_usd_per_image": PRICE_PER_IMAGE_USD,
            },
            artifacts=outputs,
            cost_usd=self.estimate_cost({"n": len(outputs)}),
            duration_seconds=round(time.time() - started, 2),
            model=MODEL_ID,
        )
