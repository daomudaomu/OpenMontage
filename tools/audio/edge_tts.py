"""Edge TTS provider tool (free Microsoft Edge neural voices)."""

from __future__ import annotations

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


class EdgeTTS(BaseTool):
    name = "edge_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "edge_tts"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = ["pkg:edge-tts"]
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
    ]
    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": False,
        "native_audio": True,
    }
    best_for = [
        "free Chinese/English video narration",
        "quick voiceover without API keys",
        "cost-sensitive production drafts",
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
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "network"])
    idempotency_key_fields = ["text", "voice", "rate", "volume", "pitch"]
    side_effects = ["writes audio file to output_path", "calls Microsoft Edge TTS online service"]
    user_visible_verification = ["Listen to generated audio for intelligibility and tone"]

    def get_status(self) -> ToolStatus:
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
        import edge_tts

        text = inputs["text"]
        voice = inputs.get("voice", "zh-CN-XiaoxiaoNeural")
        rate = inputs.get("rate", "+0%")
        volume = inputs.get("volume", "+0%")
        pitch = inputs.get("pitch", "+0Hz")
        output_path = Path(inputs.get("output_path", "edge_tts_output.mp3"))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(
            text,
            voice=voice,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )
        import asyncio

        asyncio.run(communicate.save(str(output_path)))

        if not output_path.exists():
            return ToolResult(success=False, error=f"Edge TTS output file missing: {output_path}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "model": "edge-neural-tts",
                "voice": voice,
                "rate": rate,
                "volume": volume,
                "pitch": pitch,
                "format": "mp3",
                "text_length": len(text),
                "output": str(output_path),
            },
            artifacts=[str(output_path)],
            model="edge-neural-tts",
        )
