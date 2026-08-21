---
name: edge-tts
description: Microsoft Edge online neural TTS — free, no API key, Chinese/English voices, mp3 output.
---

# Edge TTS

Use Microsoft Edge's online neural text-to-speech service. No API key required.

## Install

```bash
pip install edge-tts
```

## CLI examples

```bash
edge-tts --voice zh-CN-XiaoxiaoNeural --text "你好，这是测试。" --write-media out.mp3
edge-tts --list-voices | grep zh-CN
edge-tts --voice zh-CN-XiaoxiaoNeural --rate=-10% --text "慢一点" --write-media slow.mp3
```

## Python / OpenMontage tool

The OpenMontage tool `edge_tts` accepts:

```json
{
  "text": "你好，这是测试。",
  "voice": "zh-CN-XiaoxiaoNeural",
  "rate": "+0%",
  "volume": "+0%",
  "pitch": "+0Hz",
  "output_path": "projects/<project>/assets/audio/narration.mp3"
}
```

## Recommended Chinese voices

| Voice | Style |
|---|---|
| zh-CN-XiaoxiaoNeural | Warm, news/novel — general purpose |
| zh-CN-YunxiNeural | Lively male, novel — explainer friendly |
| zh-CN-YunjianNeural | Passion male, sports/news |
| zh-CN-YunyangNeural | Professional male, news |
| zh-CN-XiaoyiNeural | Lively female, cartoon/novel |
| zh-HK-HiuMaanNeural / zh-TW-HsiaoYuNeural | Cantonese / Traditional Chinese |

## Notes

- Free, but not an official commercial SLA; availability depends on Microsoft Edge service.
- Output is MP3 (48 kbps, 24 kHz mono by default via CLI).
- No API key, no billing, no quota (subject to Microsoft service limits).
