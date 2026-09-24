# OpenMontage 缺陷修复与优化开发计划（daomudaomu）

> 建立日期：2026-09-24
> 来源：对 LDWS 项目（`projects/ldws-teaching/`）的完整复盘调查，共确认 4 组问题、28 项缺陷。
> 用途：按序推进修复，记录每阶段状态与验收证据。**改代码前先看本文档的「当前状态」。**

---

## 0. 总原则

1. **根因优先** —— 先修产生问题的机制，不做观感补丁。
2. **验收必须可证** —— 每项改动附数字、抽帧或测试证据，不接受"看起来好了"。
3. **不引入付费路径**，除非明确批准。
4. **上游文件策略（用户 2026-09-24 拍定）**：混合 —— 能绕开的用本仓新工具/新模块解决；必须修的上游文件才直接改，并加 `# OpenMontage-local patch:` 标记，便于日后 `git merge upstream/main` 定位冲突。
5. 每阶段结束追加 `docs/USAGE_NOTES_zh-CN.md` 并推 `origin main`。

**环境事实（易踩，先记）**
- 仓库**没有 `.venv`**（`AGENTS.md` 的说明失真）。用 `/home/fxbchc/CodeSpace/pythonenv/openmontage/bin/python`（3.10.12）。
- `make test` 依赖 pytest，venv 里**未安装** → 已于 2026-09-24 `pip install pytest`（9.1.1）。`requirements-dev.txt` 里的 `httpx2` 疑似笔误（应为 `httpx`）。
- 仓库 `.env` 全为空；真实凭据只在 `~/.bashrc`（`APIYI_API_KEY` / `APIYI_API_SEEDANCE_KEY`）。
- `projects/` 与 `music_library/` 被 gitignore → **产物（含 SRT）不在版本库**。

### 测试基线（2026-09-24，装上 pytest 后首测）

```
初始（改动前）:  pytest tests/contracts/ -q  →  843 passed, 2 failed, 7 skipped
Phase 1 完成:                                →  894 passed, 0 failed, 7 skipped
Phase 3 完成（全量 tests/）:                 →  1492 passed, 0 failed, 12 skipped
```

**那 2 个失败是既有回归，非本次改动引入**，且都由 `c52eb0a`（Edge TTS / Piper 本地增强）造成 —— 已在 A4 修复（见下）。

| 失败用例 | 原因 |
|---|---|
| `TestCapabilityMetadata::test_registry_catalog_views` | 断言 tts provider 集合不含 `edge_tts`，而该 provider 是本地新增的 → **期望集合需同步更新** |
| `TestPiperTTS::test_status_requires_piper_executable_even_if_python_package_imports` | 断言 `PiperTTS().get_status() == UNAVAILABLE`，但本地已修 piper 解析且 venv 装了 `piper-tts` 包 → 返回 AVAILABLE |

> 这两项应作为 **Phase 1 的附带收尾**修掉（更新契约期望），否则门禁长期带红，后续无法用测试证明修复有效。

---

## 1. 问题总览

| 组 | 问题 | 关键证据 | 严重度 | 状态 |
|---|---|---|---|---|
| **A** | 字幕时间戳是「按字数线性插值」的**估算**，非声学对齐 | 残差中位数 **0.55 ms**（零声学信息） | 🔴 高 | ✅ 已修 |
| **A** | 旁白被裁 1.202s（时长硬编码） | 音频 77.256s vs 成片 76.054s | 🔴 高 | ✅ 已修 |
| **B** | `subtitle_check` **假通过** | 文件存在即判 `coverage_ratio=1.0`；该字段全仓无计算逻辑 | 🔴 高 | ✅ 已修 |
| **B** | atelier 路径**不烧字幕** | 抽帧：master 无字幕、final 有字幕 → 未记录的二次烧录 | 🔴 高 | ✅ 已修 |
| **B** | 时长漂移检查**从未执行**（计划外发现） | 读的 `total_duration_seconds` 非法、`metadata.target_duration_seconds` 无写入方 | 🔴 高 | ✅ 已修 |
| **B** | `subtitles.style` 字符串 → FFmpeg 烧录**必然崩溃**（计划外发现） | schema 定 `style` 为 string，代码对其调 `.items()` | 🔴 高 | ✅ 已修 |
| **C** | APIYi 技能未注册进 registry | `'apiyi' in name` → `[]` | 🟡 中 | ⬜ Phase 4 |
| **C** | 2 条**会真花钱**的缺陷（D1/D2） | 首帧 60s 超时白提交；任务孤儿不取消 | 🔴 高 | ⬜ Phase 4 |

---

## 2. Phase 1（A 组）· 字幕链路根治 —— ✅ 已完成（2026-09-24）

**目标**：让字幕时间戳来自真实声学数据，消灭"插值估算"根因。

### A1. `tools/audio/edge_tts.py` 增加词级时间戳与字幕产出 ✅
*自有文件（commit `c52eb0a` 新增），无上游冲突*

| # | 改动 | 状态 |
|---|---|---|
| A1.1 | `Communicate(..., boundary="WordBoundary")` —— **根因**。默认 `SentenceBoundary` 使中文整句仅 1 个 cue | ✅ 默认值即 `WordBoundary` |
| A1.2 | `save()` → `stream()` 单次遍历，同时写 mp3 + 收集 tokens，**保证 rate/voice 与音频同源** | ✅ |
| A1.3 | 新增可选 `subtitle_path` / `word_tokens_path`；不传时行为与现状**完全一致**（向后兼容） | ✅ 实测无字幕参数时产物仅 mp3 |
| A1.4 | `data` 回传 word tokens，供 A2 使用 | ✅ `data["word_tokens"]` |
| A1.5 | `dependencies = ["pkg:edge-tts"]` → `["python:edge_tts"]`（实测 `pkg:` 前缀不被 `check_dependencies` 识别） | ✅ 新增一致性测试 |
| A1.6 | 记录 `rate`/`volume`/`pitch`/`boundary` 到产物（当前未记，无法复算时间轴） | ✅ 同时写入 mp3 旁的 tokens JSON |

**验收结果**：
- 端到端实测（整段 LDWS 旁白，单次调用）：产出 mp3 + 167 tokens + **40 条 cue**，`unmatched=0`。
- `edge-tts` 缺失时 `get_status()` 与 `check_dependencies()` **结论一致**（新增测试锁定）。
- 末条 cue 结束 **76.675s ≤ 音频 77.256s** ✅

> ⚠️ **修正一处原定验收标准**：原写"mp3 时长与 SRT 末条时间戳一致（±50ms）"，
> 这是**不可能达到**的 —— TTS 在最后一个词之后还有 0.581s 尾部静音
> （末词止于 76.675s，文件 77.256s）。正确标准应是：
> **末条 cue 结束 = 最后语音结束，且 ≤ 音频总时长**。实测正好满足。

### A2. 新建对齐器：目标短语 → 精确时间 ✅
*本仓新文件 `tools/audio/phrase_aligner.py`。核心新能力。*

**关键技术约束（已实测）**：edge-tts 的 token 切分不可直接当词用 —— `它不接管方向盘` 被切成
`它/不/接/管方/向盘`（语义错误）。

**已验证解法**：把 tokens **展开为逐字符时间轴**（每 token 时长按字符数均分），再用目标短语在字符流中顺序匹配。

| # | 改动 | 状态 |
|---|---|---|
| A2.1 | 输入 word tokens + 目标短语列表 → 输出 SRT | ✅ |
| A2.2 | 字符级时间轴重建（按字符均分 token 时长） | ✅ 实测绕开 `管方`/`向盘` 错误切分 |
| A2.3 | 顺序匹配 + 容错（去标点/空格后匹配；失败降级区间插值并在 `data` 标 `estimated: true`） | ✅ 未匹配项单独计 `unmatched_indices`，不静默出错 |
| A2.4 | 去标点开关（默认开），**保留拉丁词**（`LDWS`/`ADAS`/`Canny`）与词间空格 | ✅ `display_text()` 自动恢复 CJK↔拉丁间距 |
| A2.5 | 中文空格拼接：**绕开**上游 `subtitle_gen` 的 `" ".join`（实测输出 `车 道 偏 离 预 警`），按 CJK 判断 | ✅ 按显示宽度折行，不空格拼接 |

**断句来源（用户 2026-09-24 拍定）**：两者兼容 —— 默认从 `script.json` 自动切分；项目内可用短语文件覆盖。

**⚠️ 实施中修正了原计划的断句算法**：原计划设想的"按长度合并子句"启发式是**错的**（会把
`开车时车辆突然向车道线偏移而你却没有察觉` 并成一条）。实测发现：

- **纯标点切分** 就能 40/40 复现人工精调版的断句结构
- 仅 1 处差异（拉丁词两侧空格），已由 `display_text()` 处理

因此最终实现为「标点优先切分 + 超长强制拆分」，而非长度打包。

**验收结果（对照人工精调版 `narration_sync4.srt`）**：

```
cues 40 / 40        unmatched 0
cue 文本完全一致    line-wrap 完全一致
start 偏差: 中位数 +0.050s  |均值| 0.119s  最大 0.539s
cue 间空隙: 全 0.0（butt-joined，无闪烁无重叠）
首条 0.100s / 末条 76.675s / 音频结束 76.675s
```

**"不是插值"的证明**（关键验收）：对「cue 起点 ~ 累计字数」做最小二乘拟合，取残差标准差：

| 时间轴 | 残差 stdev | 残差 max |
|---|---|---|
| `sync4`（人工精调基准） | 401.61 ms | 746.85 ms |
| **纯字数插值**（构造的对照） | **0.00 ms** | **0.00 ms** |
| `phrase_aligner`（本次产出） | **504.31 ms** | 1005.16 ms |

纯插值必然是一条直线（残差 0）；残差 504ms 证明时间戳来自音频。
另：声学时间与纯插值的差 **中位数 0.436s / 最大 1.174s**。

### A3. 视频时长硬编码修复 ✅
*项目侧（`projects/ldws-teaching/index.tsx`），非工具侧*

原 `index.tsx:17` `DURATION = 76 * FPS` 把 77.256s 旁白裁到 76.054s：末 0.616s 语音丢失、末条字幕超出画面 1.146s。

| # | 改动 | 状态 |
|---|---|---|
| A3.1 | 时长按音频实际时长计算 | ✅ `calculateMetadata` 用 `getAudioDurationInSeconds()` 探测旁白+音乐，取最大值 + 0.5s 尾部 |
| A3.2 | 渲染前断言 `视频时长 ≥ 音频时长 - 容差` | ✅ 新增 `_check_narration_truncation()` 在 `_run_final_review` 内，对**任意项目**生效 |
| A3.3 | 断言写进 compose 阶段检查清单 | ✅ 结论写入 `final_review.checks.technical_probe.narration_duration_check` |

> **Phase 3 修正**：A3.2 当时只做到「报告」——该检查把发现写入 `issues`，但 `status` 由关键词
> 子串匹配决定，`"narration truncated"` 不在词表中，所以截断仍会 `pass`。**拦截能力在 Phase 3
> 补上**（结构化 `critical_issues`），实测同一场景 `pass → fail`。

**顺带修掉的隐藏缺陷**：末场 `SignalChainScene` 原本 `end = 75 * FPS`，在时长修正后会提前
1.7s 淡出，导致收尾句「永远是最终的责任主体」落在空背景上 → 已改为 `durationInFrames`。

**验收结果（真机渲染实测）**：
```
改动前: 76.054s（旁白 77.256s，末 1.202s 被裁）
改动后: 77.824s  帧数 2333 = ceil((77.256 + 0.5) × 30)
末场画面在 76.6s 仍在（抽帧确认信号链五节点可见）
检测器对改动前的输入正确报 "Narration truncated: ... last 1.202s of speech is missing"
```

### A4. 修复既有测试回归 ✅
*不修则门禁长期带红，后续无法用测试证明修复有效。*

| # | 改动 | 状态 |
|---|---|---|
| A4.1 | `test_registry_catalog_views` 改为断言「catalog 是完整去重的汇总」+ 关键 provider 存在 | ✅ |
| A4.2 | `TestPiperTTS` 定位到 `sys.executable` 同级 `piper` 回退，并**新增**该回退的正面测试 | ✅ |
| A4.3 | 目标：`pytest tests/contracts/` 全绿 | ✅ **894 passed, 0 failed, 7 skipped** |

> 注：A4.2 的原始测试只断言「Python 包存在但无 `piper` 可执行文件 → UNAVAILABLE」，而本地补丁
> 增加了「venv 同级二进制」回退，故测试失败。修法不是删断言，而是把 `sys.executable` 指向无同级
> 二进制的路径，并补一条断言回退本身有效的测试 —— 覆盖度是**提高**而非降低。

### A5. 新增回归测试 ✅（计划外补充）

| 文件 | 内容 |
|---|---|
| `tests/contracts/test_subtitle_alignment_contracts.py` | 31 项：依赖前缀一致性、标点处理、断句结构复现、tick/秒双单位、未匹配标记、手工覆盖、butt 连续性、**非插值证明**、注册表发现 |
| `tests/contracts/test_examples_integrity.py` | 10 项：`examples/` 哈希清单校验 + LDWS SRT 规范性（连续、无标点、文本一致） |
| `tests/contracts/test_phase3_contracts.py::TestNarrationTruncationCheck` | 7 项：真 ffmpeg 生成音频实测时长，覆盖截断/相等/更长/容差/各类跳过 |
| `tests/fixtures/ldws_tokens.json` | 167 个真实 edge-tts token（离线测试用，不联网） |

---

## 3. Phase 2（D 组）· 记录与知识沉淀

| # | 产出 | 状态 |
|---|---|---|
| D1 | 追加 `docs/USAGE_NOTES_zh-CN.md`（本轮全部发现） | ✅ 第 8 节 |
| D2 | 新建 `docs/DEV-PLAN-zh-CN.md`（本文档） | ✅ |
| D3 | 修正文档失真：`AGENTS.md` 的 `.venv` 不存在；`.env` 全空；APIYi Key 只在 `~/.bashrc` | ✅ 见 §8.13 |
| D4 | 推 `origin main` | ✅ |
| D5 | **最终采用的 SRT 纳入受控位置** | ✅ **`examples/ldws-teaching/`** |

### D5 决策（用户 2026-09-24 拍定）

**问题**：`projects/` 被 gitignore → LDWS 手工精调的 SRT 永久不可追溯。

**选定方案**：把最终采用的 SRT 纳入受控位置 —— 新建 `examples/<slug>/`。

**为什么不放宽 `.gitignore`**：`projects/` 下还有数百 MB 生成媒体与渲染中间件，放宽会把这些
一并纳入版本库；`examples/` 是白名单式收口，只放**人工拍定且工具无法复现**的产物。

**落地内容**：
```
examples/ldws-teaching/
├── narration_sync4.srt   最终采用字幕（40 cue）
├── narration.txt         对应旁白全文
├── manifest.json         sha256 + 字节数（防静默改动）
└── README.md             来源、为何入库、已知缺陷、校验方法
```
由 `tests/contracts/test_examples_integrity.py` 强制校验哈希与 SRT 规范性。

**约定（写进 README，供后续复用）**：工具可复现的产物留 `projects/`（不入库）；人工拍定、
需长期引用或作回归基准的产物，拷一份到 `examples/<slug>/` 入库。

---

## 4. Phase 3（B 组）· 校验可信度修复 —— ✅ 已完成（2026-09-24）

**修复力度（用户 2026-09-24 拍定）**：**零依赖轻量校验先做**；OCR 真核验作为后续独立项。
**四项决策（用户同日拍板）**：① B2 用「工具内记录式烧录」；② 启用像素可见性探针但**只作告警**；
③ 校验不通过**判 fail 并拒绝交付**；④ LDWS 历史产物**只追加 decision_log 条目**。

### 复现证据（改动前实测）

| 缺陷 | 复现 | 改动前结果 |
|---|---|---|
| B1 | 2 秒视频 + 唯一 cue 在 16:39 的 SRT | `subtitles_present=true, coverage_ratio=1.0, issues=[]`，`status=pass` |
| B2 | master vs final 底部条带近白像素（7 个时间点） | master 全为 **0.000%**；final 为 **0.983~3.069%** |
| B3 | 5 秒成片 vs 20 秒旁白 | 检查已记录 `truncated / shortfall=15.064s`，但 `status=pass` |
| B4 | CJK SRT → `_srt_to_word_captions()` | 40 条 cue → **44 个**伪"词"（整行当一个词，逐词时间系按行等分） |

### B1. `subtitle_check` 假通过 ✅
新建 `tools/subtitle/srt_audit.py`（纯标准库，本仓新文件）：真实解析 SRT，产出**计算得出**的
`coverage_ratio`（cue 并集时长 ÷ 视频时长，**裁剪到视频窗口内**）、真实 `timing_drift_detected`
（对 `metadata.captions` 做文本定位比对）、越界/乱序检查。
**关键纠正**：覆盖率必须裁剪——未裁剪时那条 999s 的 cue 会算出 `coverage_ratio=1.0`，
正是原缺陷的算术根源；裁剪后为 `0.0`。
**"文件存在即 present" 已删除**：改为要求烧录证据（见 B2），无证据即 **critical**。

### B2. atelier 路径烧字幕 ✅
**原缺陷的实质是顺序错误**：`final_review` 在烧录**之前**运行，结构上不可能看见字幕。
`_render_via_atelier()` 现在在审查**之前**调用新增的 `_burn_subtitles_with_record()`
（烧到临时文件再原子替换，避免 ffmpeg 读写同一路径、也避免中断毁掉已渲染的 master），
并把 `source / source_sha256 / 字节数` 作为 burn record 传给审查器。
尊重 `edit_decisions.subtitles.burn_in`（新增 schema 字段，默认 `true`）。
实测：burn 前 ink `0.0%` → burn 后 `3.064%`，record 正确回填，无残留临时文件。

### B3. 时长漂移 ✅（根因比计划所写更彻底）
计划写的是"25% 阈值过宽"，实测发现**该分支从未执行**：
`total_duration_seconds` 不是合法 `edit_decisions` 字段（`additionalProperties: false`），
`metadata.target_duration_seconds` 合法但**全仓无任何写入方** —— LDWS 的
`final_review.json` 里 `duration_drift_pct: None` 即为证据。
**真正的修复是让致命项结构化**：`_run_final_review` 不再用关键词子串猜 `status`，
改由各检查登记 `critical_issues`（旁白截断、字幕越界、声明烧录却无证据…），
`status` 由它派生。`_check_narration_truncation()` 现在**返回**其发现，由调用方升级为 critical。
实测：同一 5s vs 20s 场景 → `status=fail, action=re_render`。

### B4. 连带项 ✅
- **声明源 vs 实际烧录源**：比对两者 sha256，不一致判 fail。已实测捕获（声明 `narration.srt` /
  实烧 `sync4` 正是 LDWS 的真实情形）。
- **中文切分**：`_srt_to_word_captions()` 检测 CJK 时**不再 `split()`**，每 cue 输出一条、
  保留真实起止时间（不伪造词时间）；英文仍逐词。实测 40 cue → **40** 条。

### 计划外发现（均已修）
1. **`_resolve_subtitle_style` 对 schema 合法输入必然崩溃**：schema 定 `subtitles.style` 为
   **字符串**，代码却调 `.items()` → `AttributeError`。LDWS 自己就写了 `"style": "sentence"`，
   即任何走 FFmpeg 烧录的路径都会崩。已按 schema 改为读平铺字段（`font`/`font_size`/`color`/
   `position`…），同时保留对旧嵌套 dict 的兼容。
2. **A3 的修复此前只做到"报告"**：`_check_narration_truncation` 只写 `issues`，从未影响
   `status`。现已接入 critical 通道。（修正 Phase 1 中"已修"的表述范围。）

### 上游标记
`tools/video/video_compose.py`（4 处）、`tools/video/remotion_caption_burn.py`（1 处）、
`schemas/artifacts/edit_decisions.schema.json`（1 处）均为 upstream 跟踪文件，已加
`# OpenMontage-local patch:` / description 标记。`tools/subtitle/srt_audit.py` 与测试为本仓新增。

### 新增测试
`tests/contracts/test_subtitle_verification_contracts.py`（**51 项**）：SRT 解析（含 `,1000`
畸形时间戳、乱序、非数字序号）、覆盖率裁剪算术、越界/漂移检出、可见性探针、CJK 不分裂、
以及**门禁行为**（越界 SRT 必须 fail、截断必须 fail、声明≠实烧必须 fail）。
另含 **atelier 烧录顺序**测试（stub Remotion 渲染，断言 `render → burn → review` 顺序、
burn record 送达、`burn_in:false` 跳过、烧录失败即整体 fail）。
`tests/` 全量：**1492 passed, 0 failed, 12 skipped**（Phase 1 基线 1441 passed）。

### LDWS 历史产物
按 Re-log 约定**只追加** `decision_log` 条目 `d-007`（`category: fallback_decision`，
`subject: 交付字幕来源`），记录"官方 WhisperX 路径不可用 → 改走 WordBoundary + phrase_aligner、
实际交付 `narration_sync4.srt`"，未改动既有 6 条、未改动 `edit_decisions` 本身。

### 未做（明确遗留）
- **未重渲 LDWS 成片**：交付物仍是旧版（76.054s、烧的是 `sync4`）。要出新版需完整重渲。
- **未做 OCR 真核验**：按决策，像素探针仅告警，不判 fail。
- 因未重渲，`projects/ldws-teaching/artifacts/final_review.json` **仍是旧的手写产物**；
  新的审查器在下次渲染时才会重写它。

---

## 5. Phase 4（C 组）· APIYi 注册进 registry

**前置硬条件：先修 3 项会真花钱的缺陷**，否则等于把烧钱路径接进流水线。

| # | 改动 | 状态 |
|---|---|---|
| C0.1 | `generate_video.py:242` `timeout=60` 参数化（**D1**） | ☐ |
| C0.2 | 提交失败不取消任务（**D2**）→ 加 `task_id` 回捞/取消入口 | ☐ |
| C0.3 | 上传前校验格式/大小/边长（**D9**） | ☐ |
| C1 | 包装 `ApiyiGptImage2All` / `ApiyiSeedanceVideo` 两个 `BaseTool` 子类（复用脚本逻辑，**不走 subprocess**） | ☐ |
| C2 | `.env` / `.env.example` 增 `APIYI_*`；`docs/PROVIDERS.md` 登记（注意 `test_env_example.py` 要求注释不得被解析成凭据） | ☐ |
| C3 | 契约测试 + `estimate_cost`（图片精确 $0.03×n） | ☐ |
| C4 | 裁定 Node vs Python 版（文档说 Node 优先，但 Node 缺 `-k`、`--duration -1` 崩溃；实测记录说 Python 更稳 —— D8 已从代码证实） | ☐ |

**命名约定**：`capability` 必须用精确串 `image_generation` / `video_generation`，否则 selector 发现不到；`provider` 统一 `apiyi`。
**无需改动** `pipeline_defs/*.yaml`（selector 自动发现）与 `Makefile`。

---

## 6. 顺序与依赖

```
Phase 1 (A) ──→ Phase 2 (D1/D3/D4) ──→ Phase 3 (B) ──→ Phase 4 (C)
  字幕根因        记录 + 推送            可信度          注册(需先修 C0)
  ✅ 完成          ✅ 完成               ✅ 完成         ⬜ 下一步
```

**AD 起步第一批动作**：D2（本文档 ✅）→ A1/A2 → A3 → D1/D4。**Phase 1~3 均已落地并推送。**

**Phase 4 的硬前置未变**：先修 C0.1/C0.2/C0.3 三项会真花钱的缺陷，再把 APIYi 接进 registry。

---

## 7. 附：支撑本计划的调查证据

| 结论 | 证据 |
|---|---|
| 字幕是插值估算 | 句内残差中位数：`sync` 0.65ms / `sync3` 0.55ms（sync4 46ms 系插值+人工微调） |
| edge-tts 支持词级 | 显式 `boundary="WordBoundary"` → 中文 24 个 token（默认 0 个） |
| token 切分不可靠 | `它不接管方向盘` → `它/不/接/管方/向盘` |
| 字符级对齐可行 | 5 个目标短语全部匹配成功，时间精确到 0.001s |
| 旁白被裁 | 音频 77.256s / 成片 76.054s / 最后语音止于 76.6697s |
| 审查器假通过 | `coverage_ratio` 仅在 `video_compose.py:2560` 被赋 `1.0`，无计算逻辑 |
| atelier 不烧字幕 | `_render_via_atelier()` 零字幕代码；master 抽帧无字幕、final 有字幕 |
| `pkg:` 前缀无效 | 不存在的包不报错；`python:` 前缀正确返回 unavailable |
| registry 不扫 skills | `walk_packages(tools.__path__)` 仅覆盖 `tools/` 包树 |
| **漂移检查从未执行** | `total_duration_seconds` 非法（schema `additionalProperties:false`）；`metadata.target_duration_seconds` 全仓无写入方；LDWS `duration_drift_pct: None` |
| **拦截靠关键词子串** | 旧 `critical_issues` 是对 `issues` 做关键词匹配；`"narration truncated"` 不在词表 → 截断仍 `pass` |
| **style 字符串必崩** | schema 定 `subtitles.style` 为 string；`_resolve_subtitle_style` 调 `.items()` → `AttributeError` |
| **B2 烧录实测** | `_burn_subtitles_with_record`：burn 前 ink 0.0% → burn 后 3.064%，record 正确、无残留临时文件 |
| **中文切分实测** | 40 cue → 修复前 44 个伪词 / 修复后 40 条真实区间；英文仍逐词（`hello brave new world` → 4 词） |
| **门禁实测** | 越界 SRT：`pass` → `fail`；旁白截断：`pass` → `fail`；声明≠实烧：`fail`（sha256 比对） |

详细过程与命令见 `docs/USAGE_NOTES_zh-CN.md` 第 8、9 节。
