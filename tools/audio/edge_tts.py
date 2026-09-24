"""Edge TTS provider tool (free Microsoft Edge neural voices).

Also the project's only TTS provider that can emit **word-level timing**, which
is what makes acoustically-aligned subtitles possible without a second ASR pass.
See `docs/DEV-PLAN-zh-CN.md` Phase 1 (A).
"""

from __future__ import annotations

import asyncio
import json
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
    ToolStatus,
    ToolTier,
)


# edge-tts reports offset/duration in 100-nanosecond ticks.
_TICKS_PER_SECOND = 10_000_000


class EdgeTTS(BaseTool):
    name = "edge_tts"
    version = "0.2.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "edge_tts"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    # Was "pkg:edge-tts". BaseTool.check_dependencies() only understands the
    # cmd:/binary:/env:/python: prefixes, so "pkg:" was silently inert — it
    # never validated anything. The tool masked it by overriding get_status().
    # "python:" is the recognised form (module name, not distribution name).
    dependencies = ["python:edge_tts"]
    install_instructions = (
        "Install Edge TTS:\n"
        "  pip install edge-tts\n"
        "No API key required. Uses Microsoft Edge online neural voices."
    )
    fallback = "piper_tts"
    fallback_tools = ["piper_tts"]
    agent_skills = ["edge-tts"]

    capabilities = [
        "text_to_speech",
        "voice_selection",
        "free_online_tts",
        "word_level_timestamps",
    ]
    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": False,
        "native_audio": True,
        "word_timestamps": True,
    }
    best_for = [
        "free Chinese/English video narration",
        "quick voiceover without API keys",
        "cost-sensitive production drafts",
        "narration that needs acoustically-aligned subtitles",
    ]
    not_good_for = [
        "fully offline production",
        "commercial SLA / guaranteed availability",
        "custom voice cloning",
    ]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string", "description": "Text to synthesize."},
            "voice": {
                "type": "string",
                "default": "zh-CN-XiaoxiaoNeural",
                "description": "Edge TTS voice name, e.g. zh-CN-XiaoxiaoNeural, zh-CN-YunxiNeural.",
            },
            "rate": {
                "type": "string",
                "default": "+0%",
                "description": "Speaking rate, e.g. +0%, -20%, +30%.",
            },
            "volume": {
                "type": "string",
                "default": "+0%",
                "description": "Volume adjustment, e.g. +0%, -10%, +20%.",
            },
            "pitch": {
                "type": "string",
                "default": "+0Hz",
                "description": "Pitch adjustment, e.g. +0Hz, -10Hz, +20Hz.",
            },
            "output_path": {
                "type": "string",
                "description": "Output mp3 path. Defaults to edge_tts_output.mp3 in cwd.",
            },
            "boundary": {
                "type": "string",
                "enum": ["WordBoundary", "SentenceBoundary"],
                "default": "WordBoundary",
                "description": (
                    "Timing-event granularity. WordBoundary emits one event per "
                    "token (~per word); SentenceBoundary emits one per sentence, "
                    "which for Chinese yields a single event for a whole sentence "
                    "and is useless for subtitles. WordBoundary matches the "
                    "edge-tts CLI default."
                ),
            },
            "subtitle_path": {
                "type": "string",
                "description": (
                    "Optional. When set, also write an SRT built from these "
                    "timings via the phrase_aligner tool. Phrases are segmented "
                    "from the input text."
                ),
            },
            "word_tokens_path": {
                "type": "string",
                "description": (
                    "Optional. When set, write the raw boundary tokens as JSON "
                    "so a later phrase alignment stays reproducible without "
                    "re-synthesising (and re-billing) the audio."
                ),
            },
            "max_chars_per_cue": {
                "type": "integer",
                "default": 24,
                "description": (
                    "Clause-length cap (in CJK chars) used when segmenting "
                    "subtitle_path. Punctuation always breaks a cue first."
                ),
            },
            "max_chars_per_line": {
                "type": "integer",
                "default": 20,
                "description": "Per-line wrap budget used when building subtitle_path.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "network"])
    idempotency_key_fields = ["text", "voice", "rate", "volume", "pitch", "boundary"]
    side_effects = [
        "writes audio file to output_path",
        "optionally writes subtitle and/or word-token files",
        "calls Microsoft Edge TTS online service",
    ]
    user_visible_verification = ["Listen to generated audio for intelligibility and tone"]

    def get_status(self) -> ToolStatus:
        # NOTE: deliberately not delegating to check_dependencies() yet. This
        # override is what previously hid the inert "pkg:" dependency; now that
        # the dependency string is correct, both paths agree. Kept as-is so
        # status reporting stays stable for the registry.
        try:
            import edge_tts  # noqa: F401
            return ToolStatus.AVAILABLE
        except Exception:
            return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(
                success=False,
                error="Edge TTS is not installed. " + self.install_instructions,
            )

        start = time.time()
        try:
            result = self._generate(inputs)
        except Exception as exc:
            return ToolResult(success=False, error=f"Edge TTS generation failed: {exc}")

        result.duration_seconds = round(time.time() - start, 2)
        result.cost_usd = 0.0
        return result

    def _generate(self, inputs: dict[str, Any]) -> ToolResult:
        text = inputs["text"]
        voice = inputs.get("voice", "zh-CN-XiaoxiaoNeural")
        rate = inputs.get("rate", "+0%")
        volume = inputs.get("volume", "+0%")
        pitch = inputs.get("pitch", "+0Hz")
        boundary = inputs.get("boundary", "WordBoundary")
        output_path = Path(inputs.get("output_path", "edge_tts_output.mp3"))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        audio, tokens = self._synthesize(
            text=text,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
            boundary=boundary,
        )

        if not audio:
            return ToolResult(success=False, error="Edge TTS returned no audio data")
        output_path.write_bytes(audio)

        if not output_path.exists():
            return ToolResult(success=False, error=f"Edge TTS output file missing: {output_path}")

        artifacts = [str(output_path)]
        data: dict[str, Any] = {
            "provider": self.provider,
            "model": "edge-neural-tts",
            "voice": voice,
            "rate": rate,
            "volume": volume,
            "pitch": pitch,
            "boundary": boundary,
            "format": "mp3",
            "text_length": len(text),
            "output": str(output_path),
            "audio_bytes": len(audio),
            "word_token_count": len(tokens),
            "word_tokens": tokens,
        }

        # Raw tokens on disk: lets a later alignment run without paying for a
        # second synthesis, and makes the time axis auditable after the fact.
        tokens_path = inputs.get("word_tokens_path")
        if tokens_path:
            tp = Path(tokens_path)
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(
                json.dumps(
                    {
                        "provider": self.provider,
                        "voice": voice,
                        "rate": rate,
                        "volume": volume,
                        "pitch": pitch,
                        "boundary": boundary,
                        "ticks_per_second": _TICKS_PER_SECOND,
                        "text": text,
                        "tokens": tokens,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            artifacts.append(str(tp))
            data["word_tokens_path"] = str(tp)

        subtitle_path = inputs.get("subtitle_path")
        if subtitle_path:
            from tools.audio.phrase_aligner import PhraseAligner

            phrases = PhraseAligner.segment_text(
                text,
                max_chars=int(inputs.get("max_chars_per_cue", 24)),
            )
            align = PhraseAligner().execute(
                {
                    "tokens": tokens,
                    "phrases": phrases,
                    "output_path": str(subtitle_path),
                    "max_chars_per_line": int(inputs.get("max_chars_per_line", 20)),
                    "boundary_mode": "onset",
                }
            )
            if not align.success:
                return ToolResult(
                    success=False,
                    error=f"Edge TTS produced audio but subtitle alignment failed: {align.error}",
                    artifacts=artifacts,
                )
            artifacts.append(str(subtitle_path))
            data["subtitle_path"] = str(subtitle_path)
            data["subtitle_cue_count"] = align.data.get("cue_count")
            data["subtitle_unmatched"] = align.data.get("unmatched_count")
            data["subtitle_phrase_source"] = "auto:punctuation"

        return ToolResult(
            success=True,
            data=data,
            artifacts=artifacts,
            model="edge-neural-tts",
        )

    @staticmethod
    def _synthesize(
        text: str,
        voice: str,
        rate: str,
        volume: str,
        pitch: str,
        boundary: str,
    ) -> tuple[bytes, list[dict[str, Any]]]:
        """Single streaming pass: collect the mp3 and the boundary events.

        Using `stream()` instead of `Communicate.save()` guarantees the audio
        and the timestamps come from the *same* synthesis — a separate pass
        could return different prosody and silently desync every timestamp.
        """
        import edge_tts

        async def _run() -> tuple[bytes, list[dict[str, Any]]]:
            communicate = edge_tts.Communicate(
                text,
                voice=voice,
                rate=rate,
                volume=volume,
                pitch=pitch,
                boundary=boundary,
            )
            audio = bytearray()
            tokens: list[dict[str, Any]] = []
            async for chunk in communicate.stream():
                chunk_type = chunk.get("type")
                if chunk_type == "audio":
                    audio.extend(chunk["data"])
                elif chunk_type == "WordBoundary":
                    tokens.append(
                        {
                            "text": chunk["text"],
                            "start": chunk["offset"] / _TICKS_PER_SECOND,
                            "end": (chunk["offset"] + chunk["duration"]) / _TICKS_PER_SECOND,
                            "duration": chunk["duration"] / _TICKS_PER_SECOND,
                        }
                    )
            return bytes(audio), tokens

        return asyncio.run(_run())
