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
pytest tests/contracts/ -q  →  843 passed, 2 failed, 7 skipped
```

**这 2 个失败是既有回归，非本次改动引入**（本次只改 docs），且都由 `c52eb0a`（Edge TTS / Piper 本地增强）造成：

| 失败用例 | 原因 |
|---|---|
| `TestCapabilityMetadata::test_registry_catalog_views` | 断言 tts provider 集合不含 `edge_tts`，而该 provider 是本地新增的 → **期望集合需同步更新** |
| `TestPiperTTS::test_status_requires_piper_executable_even_if_python_package_imports` | 断言 `PiperTTS().get_status() == UNAVAILABLE`，但本地已修 piper 解析且 venv 装了 `piper-tts` 包 → 返回 AVAILABLE |

> 这两项应作为 **Phase 1 的附带收尾**修掉（更新契约期望），否则门禁长期带红，后续无法用测试证明修复有效。

---

## 1. 问题总览

| 组 | 问题 | 关键证据 | 严重度 |
|---|---|---|---|
| **A** | 字幕时间戳是「按字数线性插值」的**估算**，非声学对齐 | 残差中位数 **0.55 ms**（零声学信息） | 🔴 高 |
| **A** | 旁白被裁 0.616s（时长硬编码） | 音频 77.256s vs 成片 76.054s | 🔴 高 |
| **B** | `subtitle_check` **假通过** | 文件存在即判 `coverage_ratio=1.0`；该字段全仓无计算逻辑 | 🔴 高 |
| **B** | atelier 路径**不烧字幕** | 抽帧：master 无字幕、final 有字幕 → 未记录的二次烧录 | 🔴 高 |
| **C** | APIYi 技能未注册进 registry | `'apiyi' in name` → `[]` | 🟡 中 |
| **C** | 2 条**会真花钱**的缺陷（D1/D2） | 首帧 60s 超时白提交；任务孤儿不取消 | 🔴 高 |

---

## 2. Phase 1（A 组）· 字幕链路根治

**目标**：让字幕时间戳来自真实声学数据，消灭"插值估算"根因。

### A1. `tools/audio/edge_tts.py` 增加词级时间戳与字幕产出
*自有文件（commit `c52eb0a` 新增），无上游冲突*

| # | 改动 | 状态 |
|---|---|---|
| A1.1 | `Communicate(..., boundary="WordBoundary")` —— **根因**。默认 `SentenceBoundary` 使中文整句仅 1 个 cue | ☐ |
| A1.2 | `save()` → `stream()` 单次遍历，同时写 mp3 + 收集 tokens，**保证 rate/voice 与音频同源** | ☐ |
| A1.3 | 新增可选 `subtitle_path` / `word_tokens_path`；不传时行为与现状**完全一致**（向后兼容） | ☐ |
| A1.4 | `data` 回传 word tokens，供 A2 使用 | ☐ |
| A1.5 | `dependencies = ["pkg:edge-tts"]` → `["python:edge_tts"]`（实测 `pkg:` 前缀不被 `check_dependencies` 识别） | ☐ |
| A1.6 | 记录 `rate`/`volume`/`pitch`/`boundary` 到产物（当前未记，无法复算时间轴） | ☐ |

**验收**：mp3 时长与 SRT 末条时间戳一致（±50ms）；tokens 数 > 0；`edge-tts` 缺失时 `get_status()` 正确返回 UNAVAILABLE。

### A2. 新建对齐器：目标短语 → 精确时间
*本仓新文件。核心新能力。*

**关键技术约束（已实测）**：edge-tts 的 token 切分不可直接当词用 —— `它不接管方向盘` 被切成
`它/不/接/管方/向盘`（语义错误）。

**已验证解法**：把 tokens **展开为逐字符时间轴**（每 token 时长按字符数均分），再用目标短语在字符流中顺序匹配：

```
字符流: LDWS车道偏离预警系统是智能网联汽车ADAS中的一项预警功能它不接管方向盘只负责提醒
'车道偏离预警系统'  → 1.637 ~ 3.188    ✅ 绕开 tokenization 错误
'它不接管方向盘'    → 7.650 ~ 9.100
```

| # | 改动 | 状态 |
|---|---|---|
| A2.1 | 输入 word tokens + 目标短语列表 → 输出 SRT | ☐ |
| A2.2 | 字符级时间轴重建（按字符均分 token 时长） | ☐ |
| A2.3 | 顺序匹配 + 容错（去标点/空格后匹配；失败降级区间插值并在 `data` 标 `estimated: true`） | ☐ |
| A2.4 | 去标点开关（默认开），**保留拉丁词**（`LDWS`/`ADAS`/`Canny`）与词间空格 | ☐ |
| A2.5 | 中文空格拼接：**绕开**上游 `subtitle_gen` 的 `" ".join`（实测输出 `车 道 偏 离 预 警`），按 CJK 判断 | ☐ |

**断句来源（用户 2026-09-24 拍定）**：两者兼容 —— 默认从 `script.json` 自动切分；项目内可用短语文件覆盖（保留 LDWS/sync4 式人工精调能力）。

**验收**：新时间戳**不再呈现"纯字数插值"特征**（残差应从 0.55ms 量级跃升到真实声学量级）；抽帧核对 3 个时间点文字与画面一致。

### A3. 视频时长硬编码修复
*项目侧（`index.tsx`），非工具侧*

`index.tsx:17` `DURATION = 76 * FPS` 把 77.256s 旁白裁到 76.054s：末 0.616s 语音丢失、末条字幕超出画面 1.146s（silencedetect 定位最后语音止于 76.6697s）。

| # | 改动 | 状态 |
|---|---|---|
| A3.1 | 时长按音频实际时长计算（`Math.ceil(audioDuration * FPS)`） | ☐ |
| A3.2 | 渲染前断言 `视频时长 ≥ 音频时长 - 容差` | ☐ |
| A3.3 | 断言写进 compose 阶段检查清单 | ☐ |

### A4. 修复既有测试回归（Phase 1 附带收尾）
*不修则门禁长期带红，后续无法用测试证明修复有效。*

| # | 改动 | 状态 |
|---|---|---|
| A4.1 | `test_registry_catalog_views` 的 tts provider 期望集合加入 `edge_tts` | ☐ |
| A4.2 | `TestPiperTTS::test_status_...` 期望更新（本地已修 piper 解析 + 装了 `piper-tts` 包） | ☐ |
| A4.3 | 目标：`pytest tests/contracts/` 全绿（843+ passed, 0 failed） | ☐ |

---

## 3. Phase 2（D 组）· 记录与知识沉淀

| # | 产出 | 状态 |
|---|---|---|
| D1 | 追加 `docs/USAGE_NOTES_zh-CN.md`（本轮全部发现） | ☐ |
| D2 | 新建 `docs/DEV-PLAN-zh-CN.md`（本文档） | ✅ |
| D3 | 修正文档失真：`AGENTS.md` 的 `.venv` 不存在；`.env` 全空；APIYi Key 只在 `~/.bashrc` | ☐ |
| D4 | 推 `origin main` | ☐ |

> **待决**：SRT 不在版本库 → 不可复现。是否把最终采用的 SRT 纳入受控位置（或放宽 ignore）。**未决，暂不擅自改动。**

---

## 4. Phase 3（B 组）· 校验可信度修复

**修复力度（用户 2026-09-24 拍定）**：**零依赖轻量校验先做**；OCR 真核验作为后续独立项。

### B1. `subtitle_check` 假通过
`video_compose.py:2553` —— SRT 文件存在于磁盘即判 `subtitles_present=true` + `coverage_ratio=1.0`。
`coverage_ratio` / `timing_drift_detected` **全仓无任何计算逻辑**（已 grep 确认）→ LDWS 的 `final_review.json` 系手写，其"字幕通过、无漂移"不具证据效力。

**改法（轻量、零依赖）**：末条字幕是否超出视频时长（捕获 A3 这类问题）；SRT 与输出 mtime 关系；**未提供烧录证据时不再假定通过**。

### B2. atelier 路径不烧字幕
`_render_via_atelier()` 无任何字幕逻辑；抽帧证实字幕是**未记录的二次 FFmpeg 烧录**。
→ 让该路径尊重 `edit_decisions.subtitles`，或明确要求显式 `operation="burn_subtitles"` 并记入 `decision_log`。

### B3. 时长漂移阈值过宽
当前 25%，使 76.05 vs 77.26（1.6%）静默通过 → 增加"视频时长 < 音频时长"专项检查。

### B4. 连带项
`asset_manifest.subtitles.path` / `edit_decisions.subtitles.source` 与实际交付物脱钩；`remotion_caption_burn._srt_to_word_captions()` 用 `text.split()` 中文失效。

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
```

**AD 起步第一批动作**：D2（本文档 ✅）→ A1/A2 → A3 → D1/D4。

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

详细过程与命令见 `docs/USAGE_NOTES_zh-CN.md` 第 8 节。
