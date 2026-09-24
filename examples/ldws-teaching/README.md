# LDWS 教学视频 · 参考字幕样例

本目录把 LDWS 车道偏离预警系统教学视频**最终采用的字幕**纳入版本库，作为
"人工精调后的目标产物"参考样例。

## 为什么在这里

项目产物默认写在 `projects/<slug>/`，而 `projects/` 被 `.gitignore` 忽略（生成物
可重新生成，不入库）。这样做的代价是：**一旦某个产物是人工精调、无法由工具复现
的，它就永久不可追溯**。LDWS 的字幕正是这种情况 —— 它经历了 5 轮迭代
（`narration.srt` → `sync` → `sync2` → `sync3` → `sync4`），最终版的断句、时间戳、
无标点风格都含人工判断，无法由当前工具链再生。

因此约定：**工具可复现的产物留在 `projects/`（不入库）；人工拍定、需要长期引用或
回归对比的产物，拷贝一份到 `examples/<slug>/` 入库。**

## 文件

| 文件 | 说明 |
|---|---|
| `narration_sync4.srt` | **最终采用版本**。40 条 cue，中文自然断句，无标点，贴近底部 |
| `narration.txt` | 与 `srt` 对应的旁白全文（由 `script.json` 各 section 的 `text` 顺序拼接） |
| `manifest.json` | 两个文件的 sha256 与字节数，用于校验内容未被静默改动 |

源文件（不入库，仅本机）：
`projects/ldws-teaching/export/narration_sync4.srt`（与 `projects/ldws-teaching/assets/audio/narration_sync4.srt` 逐字节相同）

## 已知缺陷（施工中）

`srt` 的时间戳是**按字数线性插值估算**出来的，不含声学信息 —— 句内残差中位数
**0.55 ms**，这是"纯插值"的指纹。根因是 `edge-tts` 默认 `boundary="SentenceBoundary"`
导致中文整句只产出 1 个 boundary 事件。

实测（同一条文本、同一 voice `zh-CN-XiaoxiaoNeural`）：

```
SentenceBoundary →   1 个 boundary 事件
WordBoundary     →  20 个 boundary 事件（含 offset/duration）
```

修复计划与验收标准见 `docs/DEV-PLAN-zh-CN.md` Phase 1（A 组）。修好后本目录的
`srt` 可作为**人工基准**与之对比，但预期二者仍不会逐字相同 —— 本版含人工断句
调整，这正是它需要入库的原因。

## 校验

```bash
# 本机实际的解释器（仓库内没有 .venv，AGENTS.md 的说法已失真）
/home/fxbchc/CodeSpace/pythonenv/openmontage/bin/python - <<'PY'
import hashlib, json, pathlib
base = pathlib.Path("examples/ldws-teaching")
man = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
for name, meta in man["files"].items():
    got = hashlib.sha256((base / name).read_bytes()).hexdigest()
    print(f"{name:24s} {'OK' if got == meta['sha256'] else 'MISMATCH'}")
PY
```

对应的契约测试：`tests/contracts/test_examples_integrity.py`。
