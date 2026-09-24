# OpenMontage 个人使用记录（daomudaomu）

> 本文件用于记录我使用 OpenMontage 时的环境、已完成配置、踩坑记录、改进建议和下次继续入口。
> 目的：下次继续尝试时能快速恢复现场，不重复踩坑。

---

## 1. 仓库与远程绑定

- `origin`：`git@github.com:daomudaomu/OpenMontage.git`（我的仓库，可推送）
- `upstream`：`https://github.com/calesthio/OpenMontage.git`（官方上游，只读）
- 当前分支：`main`

常用命令：

```bash
# 拉取官方上游更新
git fetch upstream
git merge upstream/main

# 推送到自己的仓库
git push origin main
```

---

## 2. 本地环境

| 项目 | 值 |
|---|---|
| 项目路径 | `/home/fxbchc/CodeSpace/AiVideoGeneration/OpenMontage` |
| Python 虚拟环境 | `/home/fxbchc/CodeSpace/pythonenv/openmontage`（Python 3.10.12） |
| FFmpeg | 已安装（`ffmpeg` / `ffprobe`，7:4.4.2） |
| Remotion | `remotion-composer/node_modules` 已安装 |
| `.env` | 已从 `.env.example` 创建，尚未填任何官方 API Key |
| 系统播放器 | VLC 3.0.16，已设为默认 |

### 网络情况

- GitHub HTTPS / HuggingFace 下载需要代理：`http://127.0.0.1:7890`
- APIYi 接口：直连可用
- Edge TTS：直连可用
- SSH 到 GitHub：已认证（`daomudaomu`）

---

## 3. 已完成的自定义与增强

### 3.1 Edge TTS —— 免费在线 TTS

- 新增工具：`tools/audio/edge_tts.py`（provider：`edge_tts`）
- 新增技能：`.agents/skills/edge-tts/SKILL.md`
- `requirements.txt` 已加入 `edge-tts>=7.2.8`
- 支持输出 MP3 和 SRT 字幕
- 推荐中文音色：`zh-CN-XiaoxiaoNeural`、`Yunxi`、`Yunjian`、`Yunyang`、`Xiaoyi`

示例：

```bash
edge-tts --voice zh-CN-XiaoxiaoNeural --text "你好" --write-media out.mp3 --write-subtitles out.srt
```

### 3.2 Piper —— 离线 TTS 兜底

- 已修改：`tools/audio/piper_tts.py`
  - 修复 piper 可执行文件解析
  - 支持 `--data-dir` 指定模型目录
- 模型目录：`~/.piper/models/`
  - `en_US-lessac-medium`
  - `zh_CN-huayan-medium`
- 注意：Piper 只输出 WAV，没有时间戳字幕；需要字幕时用 ffmpeg 转换 + 另行生成。

### 3.3 同事 APIYi 技能整合

- `.agents/skills/apiyi-gpt-image-2-all-gen/`：图片生成（Python + Node 脚本）
- `.agents/skills/apiyi-seedance2-video-gen/`：视频生成（Python + Node 脚本）
- 这两个技能是同事提供的独立脚本，尚未注册进官方 `tool_registry`

### 3.4 Pixabay Music —— 免费背景音乐

- 官方自带工具：`pixabay_music`（无需 API Key，实验性爬取）
- 已下载一首用于测试：`music_library/calm-nature-ambient.mp3`
- 备选：`freesound_music` 需要免费 key；`music_gen` 需要 ElevenLabs

### 3.5 最小成本实验（已完成）

主题：**日落山谷**

产物在 `projects/colleague-test/assets/`：

| 步骤 | 工具 | 产物 |
|---|---|---|
| 图片 | APIYi GPT Image | `images/sunset_valley.png` |
| 视频 | APIYi Seedance mini 480p 5s | `video/sunset_valley.mp4` |
| 旁白 | Edge TTS 中文 Xiaoxiao | `audio/narration.mp3` + `.srt` |
| 背景音乐 | Pixabay Music | `music_library/calm-nature-ambient.mp3` |
| 合成 | FFmpeg | `final_test.mp4` / `final_test_compatible.mp4` |

成本参考：

- APIYi 图片：约 $0.03/张
- Seedance mini 480p 5s：约 ¥1.16/次
- Edge TTS / Pixabay Music：免费

---

## 4. 问题与踩坑记录

1. **SSH 克隆超时**
   - 原因：当前网络访问 GitHub SSH/HTTPS 不稳定
   - 解决：走代理用 HTTPS 浅克隆，之后再绑定自己的 SSH 远程

2. **`python3.10 -m venv` 失败（ensurepip 不可用）**
   - 解决：用 `virtualenv` 创建虚拟环境

3. **Edge TTS 协程不输出**
   - 原因：工具里 coroutine 未 await
   - 解决：用 `asyncio.run(...)` 包住 `communicate.save`

4. **Piper 安装后没有模型**
   - 原因：pip 包不负责下载模型
   - 解决：手动下载模型到 `~/.piper/models/`（下载需要代理）

5. **mmx 配额耗尽**
   - mmx CLI 已安装，key 区域为 `cn`，但提示“已达到 Token Plan 用量上限”
   - 结论：当前阶段用 Edge TTS / Piper / Pixabay 替代，不依赖 mmx

6. **Seedance 视频请求超时**
   - 原因：APIYi 脚本里硬编码 `timeout=60`，首帧 2MB PNG 上传超时
   - 解决：先用 ffmpeg 把首帧压成 166KB 的 JPG（`scale=1280:720 -q:v 4`），重试成功
   - 建议：把脚本超时改大，或先压缩输入图

7. **视频文件打不开**
   - 系统自带播放器打不开 `final_test.mp4`
   - 解决：转出 H.264 Constrained Baseline + AAC + `faststart` 的兼容版；并安装 VLC 作为默认播放器

8. **`.env` 未填 key**
   - 官方流程需要按需填 `OPENAI_API_KEY` / `FAL_KEY` / `PEXELS_API_KEY` 等
   - 免费替代：Pexels/Pixabay 免费 key 或继续用同事 APIYi 脚本

---

## 5. 改进建议

### 对上游/仓库的建议

- APIYi 脚本硬编码 60 秒超时，建议改成可配置或自动重试
- 建议把 `timeout`、代理地址、`data-dir` 等做成环境变量/配置文件
- 建议增加 Edge TTS / Piper 的官方文档说明（免费 TTS 入门路径）
- 建议在 `tool_registry` 里为第三方脚本提供“注册但不内置 key”的扩展方式

### 对我自己的后续计划

- 体验官方流水线 B（如 animated-explainer / cinematic）
- 体验混合路线 C：APIYi 生成素材 → 官方 Edge TTS / Pixabay / Remotion / FFmpeg 合成
- 若需要更多 AI 视频生成，再考虑配置 FAL_KEY / Pexels 免费 key 等
- mmx 若后续要跑同事方案，需要充值或换 key

---

## 6. 下次继续入口

1. 激活环境：

```bash
source /home/fxbchc/CodeSpace/pythonenv/openmontage/bin/activate
cd /home/fxbchc/CodeSpace/AiVideoGeneration/OpenMontage
```

2. 先确认远程：

```bash
git remote -v
```

3. 体验官方流水线 B，例如：

```bash
python -m pipeline.run --pipeline animated-explainer --project my-demo --topic "光合作用"
```

（具体命令以仓库实际入口为准，先查 `README_zh-CN.md` / `AGENT_GUIDE.md`）

4. 体验混合路线 C：先用 APIYi 技能生成素材，再走官方工具合成。

5. 把新问题、新结果追加到本文件，再 `git add docs/USAGE_NOTES_zh-CN.md && git commit -m "docs: update usage notes" && git push origin main`。

---

## 7. LDWS 混合路线 C 实战记录（2026-08-23）

### 项目

- 项目目录：`projects/ldws-teaching/`
- 主题：智能网联汽车 · 车道偏离预警系统（LDWS）教学解说
- 受众：高职本科智能网联汽车技术专业学生
- 时长：76 秒，中文配音 + BGM
- 路线：官方 animated-explainer 立项/脚本/分镜 → 混合 C 素材 → Remotion atelier 动画合成

### 素材与成本

- APIYi GPT Image × 5（教学示意图）
- APIYi Seedance mini × 8（每章动态视频，480p 5s）
- Edge TTS 中文旁白 + 字幕
- Pixabay BGM
- 总素材成本约 **$1.46**

### 关键经验

1. **用户明确否定了“静态图 + Ken Burns”的模板化做法**：
   - 初版用 templated Explainer，AI 图整屏 + 缩放，用户反馈“像对着几张图说话”。
   - 重做为 `composition_mode: "atelier"`，手写 Remotion 动画：车道线扫描、判断流程图、HUD 脉冲、信号链点亮。

2. **字幕要求很具体**：
   - 位置要贴近底部，不能中间偏下。
   - 断句要符合中文习惯：按逗号/顿号等自然停顿，不要按字数硬切。
   - 字幕里不要标点符号，观感更干净。
   - 最终使用 `narration_sync4.srt`（40 条无标点自然短语）。

3. **Remotion atelier 渲染注意**：
   - 若入口在 `projects/<slug>/index.tsx`，`video_compose` 会自动 staging 到 `remotion-composer/projects/<slug>/`。
   - 媒体必须放项目 `public/` 并通过 `staticFile()` 引用，且 `bespoke.public_dir` 指向该目录。
   - `npx remotion compositions <absolute entry>` 可单独验证入口。
   - Google Fonts 下载需要代理：`HTTP_PROXY=http://127.0.0.1:7890 HTTPS_PROXY=http://127.0.0.1:7890`。

4. **Sequence 与全局帧的坑**：
   - 场景组件放在 `<Sequence>` 内时，`useCurrentFrame()` 是相对 Sequence 的帧；若组件内部再用“全局秒数”算 opacity，会导致场景透明/不可见。
   - 修复：不包 Sequence，直接用全局帧区间控制每个场景显隐。

### 产物

- 推荐播放：`projects/ldws-teaching/renders/ldws_teaching_animated_final.mp4`（720p，字幕已烧录）
- 1080p 母版：`projects/ldws-teaching/renders/ldws_teaching_animated.mp4`
- 导出包：`projects/ldws-teaching/export/`
- 字幕文件：`projects/ldws-teaching/assets/audio/narration_sync4.srt`

### 状态

- 用户已确认 v4 成片，已更新本文档并推送到 `origin main`。

---

## 8. 深度复盘调查（2026-09-24）

对 LDWS 项目做了一次完整复盘，确认 4 组问题、28 项缺陷。**修复计划另见 `docs/DEV-PLAN-zh-CN.md`。**
本节只记录**证据与结论**（全部为只读调查，未改任何代码）。

### 8.1 环境与文档失真（先记，避免重复踩坑）

| 出处 | 声明 | 现实 |
|---|---|---|
| `AGENTS.md` | 用「当前目录下的虚拟环境 `.venv`」 | 🔴 **`.venv` 不存在**；实际是 `/home/fxbchc/CodeSpace/pythonenv/openmontage`（3.10.12） |
| `AGENTS.md` | mmx 可用 | 配额已耗尽，当前用 Edge TTS 替代 |
| `.env` | 应有 API Key | **逐字节等于 `.env.example`，全为空** |
| — | — | 官方 `image_generation` **0/16**、`video_generation` **0/26** 可用；真实凭据只在 `~/.bashrc` |
| — | — | venv 里**没有 pytest**，`make test` 跑不了；`requirements-dev.txt` 的 `httpx2` 疑似应为 `httpx` |
| — | — | 合成运行时 ffmpeg / remotion / hyperframes **三者均可用** |

### 8.2 🔴 字幕错位的真正根因（本次最重要发现）

**不是转录对齐失败，而是「按字数线性插值」的估算。**

根因链条：

1. `tools/audio/edge_tts.py`（173 行）**完全不生成字幕** —— 无任何 SRT/SubMaker 代码，只写 mp3。
   `narration.srt` 是 CLI `--write-subtitles` 的产物。
2. 该 CLI 的 `boundary` 参数**默认 `SentenceBoundary`** → 中文整句 40 字只有 **1 个 cue（约 9 秒）**。
3. 于是出现 `narration_word.srt` —— **0 字节空文件**（词级尝试失败）。
4. `sync` / `sync2` / `sync3` / `sync4` 全部是**手写脚本按「累计字数 ÷ 总字数」线性插值**切句。

**决定性证据**：以原始 14 个句级时间戳为锚点，检验句内是否符合纯字数插值公式：

| 文件 | 条数 | 残差中位数 | 残差最大 |
|---|---|---|---|
| `narration_sync.srt` | 47 | **0.65 ms** | 3.78 ms |
| `narration_sync3.srt` | 40 | **0.55 ms** | 3.78 ms |
| `narration_sync4.srt` | 40 | 46.21 ms | 233.86 ms |

**亚毫秒残差不可能是巧合** → 时间轴 100% 由字数插值生成，**零声学信息**；sync4 是同一套插值 + 人工按帧微调。
**这就是为什么返工 4 次都没解决** —— 每次改断句就要重算全部时间戳，而插值永远不等于真实发音时刻，是死循环。

**各版真正在解决的是"粒度"与"断点质量"**（不是漂移）：14 句级 → 47（劈词"车道偏/离预警系统"）→ 62（更碎）→ 40（断点干净）→ 去标点 = sync4。`sync3 → sync4` 的**时间戳集合完全相同**，纯文本去标点。

**修复只需一行参数**。实测 5 个中文音色默认下 `WordBoundary=0`，显式传 `boundary="WordBoundary"` 后：

```
中文+WordBoundary: WordBoundary 事件数 = 11
  ('车道', 0.100s) ('偏离', 0.4875s) ('预警', 0.8875s) ('系统', 1.2375s)
--- SubMaker.get_srt() 条数: 11   ✅ 真正的逐词时间戳
```

### 8.3 ⚠️ 但 token 切分不可直接当词用

实测 `它不接管方向盘` 被切成 `它/不/接/管方/向盘`（**语义错误**）。
**已验证的解法**：把 tokens 展开为**逐字符时间轴**（每 token 时长按字符数均分），再用目标短语顺序匹配：

```
字符流: LDWS车道偏离预警系统是智能网联汽车ADAS中的一项预警功能它不接管方向盘只负责提醒
'车道偏离预警系统'  → 1.637 ~ 3.188   ✅ 绕开 tokenization 错误
'它不接管方向盘'    → 7.650 ~ 9.100
```

### 8.4 🔴 旁白被裁 0.616 秒（独立缺陷）

| 量 | 值 |
|---|---|
| `index.tsx:17` 硬编码 | `DURATION = 76 * FPS` = **76.000s** |
| 旁白真实时长 | **77.256s** |
| 旁白最后语音结束（silencedetect） | 76.6697s |
| 成片实际时长 | **76.054s** |
| → 末尾语音被切 | **0.616s** |
| → 末条字幕（74.642→77.200）超出成片 | **1.146s**（字幕挂在已无声音的画面上） |

这是观感上"错位"的另一半来源。而 `final_review` 的漂移阈值是 **25%**，1.6% 静默通过。

### 8.5 🔴 审查器会「假通过」（最需警惕）

`tools/video/video_compose.py:2553`：

```python
if subtitle_check["subtitles_expected"] and not subtitle_check["subtitles_present"]:
    if sub_source and Path(sub_source).exists():
        subtitle_check["subtitles_present"] = True   # ← 文件存在就假定已烧录
        subtitle_check["coverage_ratio"] = 1.0       # ← 覆盖率直接写死
```

**只要 SRT 文件在磁盘上，无论有没有烧进视频、是不是最新版，都判"字幕已存在、覆盖率 100%"。**

进一步核实：`coverage_ratio` 与 `timing_drift_detected` **全仓无任何计算逻辑**（只在上述一行被赋 `1.0`）
→ **LDWS 的 `final_review.json` 是手写的**，其"字幕通过、无漂移"不具证据效力。

### 8.6 🔴 atelier 路径根本不烧字幕（已视觉验证）

`_render_via_atelier()` 内 grep 不到任何 `subtitle`/`srt`/`captions`/`burn`。抽帧对照：

| 文件 | 20s 帧 | 结论 |
|---|---|---|
| `ldws_teaching_animated_master.mp4`（1080p 母版） | **底部无字幕** | 纯 TSX 渲染产物 |
| `ldws_teaching_animated_final.mp4`（720p） | **底部有字幕**（无标点，与 sync4 一致） | 二次烧录 |

→ **字幕是渲染后用一次未被记录的 FFmpeg `burn_subtitles` 补上的**，而
`edit_decisions.subtitles.source` 至今仍指向最粗的 `narration.srt`。

### 8.7 工具层与 registry 机制

- **发现机制**：`pkgutil.walk_packages(tools.__path__)` —— **只递归 `tools/` 这一棵树**。
  注册条件：`BaseTool` 子类 + `cls.__module__ == 被测模块` + 非抽象 + `name` 非空。
- **加工具极简**：`tools/<capability>/` 放一个子类文件即可，**不用改清单、不用改 selector**。
- ⚠️ **`pkg:` 依赖前缀无效**（实测）：`check_dependencies` 只认 `cmd:`/`binary:`/`env:`/`python:`。
  `edge_tts.py:34` 写的 `pkg:edge-tts` 依赖检查**形同虚设**，只因它自己覆盖了 `get_status()` 才没暴露。
- `explainer/idea-director.md` 是**死文件**：`animated-explainer.yaml` 里没有 `idea` 阶段
  （LDWS 也确实直接从 research 起跑）。另有 EP 技能写"墙钟 15 分钟"、清单写 20 分钟的不一致。

### 8.8 中文相关缺陷

- `subtitle_gen` 用 `" ".join` 拼接词 → 中文实测输出 **`车 道 偏 离 预 警`**（已复现）。
- `remotion_caption_burn._srt_to_word_captions()` 用 `text.split()` → 中文整体失效，需改传词级 `segments`。
- 官方词级路径在本机**不可用**：`transcriber` 依赖 `python:faster_whisper`，而
  `faster_whisper` / `whisperx` / `torch` **全部未安装**，且不在任何 requirements 里。
  `skills/core/subtitle-sync.md` 也完全没提 edge-tts。

### 8.9 APIYi 两个技能（17 项缺陷，2 项会真花钱）

- **为何 registry 发现不到**（三重原因缺一不可）：位置在 `tools/` 包树外 + 是纯 CLI 脚本
  （无 `BaseTool` 子类）+ 无模块导入。实测 `['apiyi' in n] → []`。
- 图片走**对话式端点** `/v1/chat/completions`（非 `/v1/images/*`）、无 `size` 参数、**$0.03/张固定**。
  视频是**提交+轮询**（20s 间隔、1200s 上限），成功状态是 `succeeded`。两脚本 stdout 吐单行 JSON、日志走 stderr。

**两项会真花钱的缺陷：**

| # | 缺陷 | 影响 |
|---|---|---|
| **D1** | `generate_video.py:242` 创建任务硬编码 `timeout=60`，**未修复** | 2MB 首帧必超时（已踩过）→ **任务已提交、钱已花** |
| **D2** | 提交成功后轮询/下载失败**从不取消任务** | 任务孤儿，**白付钱** |

**其他要点**：Node 版 `--duration -1` 直接崩（`ERR_PARSE_ARGS_INVALID_OPTION_VALUE`），官方主推的
"智能时长"在 Node 版用不了（Python 正常）；Node 的 `AggregateError` 的 `message` 是**空串**
→ 你记录的"CDN 瞬断"得到代码级解释，**"Python 版更稳定"被证实为真**；
`.env` 里**没有任何 APIYI 变量**（Key 只在 `~/.bashrc`），而 `BaseTool._load_dotenv()` 只读 `.env`
→ 注册后不写 `.env` 会恒 UNAVAILABLE；图片脚本**依赖 `requests`**（并非"纯标准库"），视频脚本才是。

### 8.10 系统性判断

> **官方流水线管流程，但真正干活的工具在 registry 之外。**
> 于是流程产物（`asset_manifest` / `edit_decisions` / `final_review`）与实际交付物**逐渐脱钩**，
> 而且**没有任何机制会发现这个脱钩** —— 审查器还会主动"假通过"。

LDWS 里这个脱钩已具体化为 4 处：字幕路径停在 `narration.srt`、`final_review` 手写、
字幕二次烧录未入日志、SRT 不在版本库（`projects/` 被 gitignore，**不可复现**）。

### 8.11 下次稳定产出对齐字幕的推荐做法

1. `boundary="WordBoundary"` + `stream()` 一遍同时产 mp3 与 tokens（**保证 rate 同源**）。
2. tokens → **逐字符时间轴** → 用目标短语顺序匹配（绕开 tokenization 错误）。
3. 默认断句从 `script.json` 自动切分，项目内可用短语文件覆盖（保留人工精调能力）。
4. 视频时长改为 `Math.ceil(audioDuration * FPS)`，并断言 `视频 ≥ 音频`。
5. 走 atelier 时**必须显式** `video_compose(operation="burn_subtitles", ...)` 并记入 `decision_log`。
6. **不要相信 `final_review.subtitle_check`**，自己抽帧核对。
7. 备选（最稳）：装 `faster-whisper`（**无需 API key**，`HF_TOKEN` 仅用于 diarization）走官方转录链路。

### 8.12 本次调查结论

- 修复计划：`docs/DEV-PLAN-zh-CN.md`（A 字幕后端根治 → D 记录 → B 可信度 → C APIYi 注册）。
- 用户决定从 **A + D 起步**；上游文件采用**混合策略**（能绕开就绕开，必须改的加上游补丁标记）。
- **本次调查全程只读，未修改任何代码**，所有验证脚本写在 `/tmp/` 并已清理。

---

## 9. Phase 1（A 组）实施记录（2026-09-24）

> 计划见 `docs/DEV-PLAN-zh-CN.md` §2。本节记录**实际做了什么、实测数字、以及与原计划的偏差**。

### 9.1 文档失真修正（D3）

| 文档 | 原文 | 实际 |
|---|---|---|
| `AGENTS.md`（仓库内） | 只说"读 AGENT_GUIDE.md" | ✅ 正确，无需改 |
| 工作区 `AGENTS.md`（`AiVideoGeneration/AGENTS.md`，**不在 git 内**） | "本项目使用当前目录下的虚拟环境 `.venv`" | ❌ **不存在**。实际解释器：`/home/fxbchc/CodeSpace/pythonenv/openmontage/bin/python`（3.10.12） |
| 同上 | "所有 Python 命令必须使用 `.venv/bin/python`" | ❌ 该路径不存在，照抄必失败 |
| `requirements-dev.txt:5` | `httpx2>=2.0` | ⚠️ 疑似笔误，应为 `httpx`；未擅自改 |

> **注**：那段 `.venv` 说明在**工作区根目录**的 `AGENTS.md`，不在 OpenMontage 仓库里
> （仓库内的 `AGENTS.md` 只有 9 行，仅指向 `AGENT_GUIDE.md`）。它每次会话以"工作区指令"
> 形式注入，**照做会直接失败**，故记在此处。因不属于仓库文件，未修改它。

### 9.2 A1 —— `edge_tts.py` 词级时间戳

`tools/audio/edge_tts.py`（173 → 约 380 行）：

- `boundary` 参数默认 `WordBoundary`（原为硬编码走 `Communicate.save()` = `SentenceBoundary`）
- `save()` → `stream()` **单遍**同时收集音频字节与 boundary 事件
- 新增可选 `subtitle_path` / `word_tokens_path` / `max_chars_per_cue` / `max_chars_per_line`
- `dependencies`：`pkg:edge-tts` → `python:edge_tts`
- `data` 回传 `word_tokens`、`boundary`、`audio_bytes`、`word_token_count`

**实测（同一条文本，voice `zh-CN-XiaoxiaoNeural`）**：

```
SentenceBoundary →   1 个 boundary 事件
WordBoundary     →  20 个 boundary 事件（含 offset/duration）
```

> ⚠️ **顺带解开的旧谜**：`narration_word.srt` 为什么是 0 字节？
> 因为当时用 **CLI** `edge-tts --write-subtitles`，而 CLI 默认 `WordBoundary`
> （`Communicate` 默认才是 `SentenceBoundary`）—— 两种模式产出的**字节流不同**。
> 实测 LDWS 在用的 `narration.mp3` 与 `WordBoundary` 模式**逐字节相同**，
> 证实它就是 CLI 生成的。这也说明脚本与 CLI 的默认值不一致是个真实陷阱。

**向后兼容实测**：只传 `text` + `output_path` 时，产物仍只有 mp3，`artifacts` 长度 1。

### 9.3 A2 —— 新建 `tools/audio/phrase_aligner.py`

纯标准库（无新依赖）。核心：tokens → 逐字符时间轴 → 短语顺序匹配 → SRT。

**⚠️ 与原计划的重要偏差（计划里的断句算法是错的）**

原计划写的是"标点切子句后**按长度合并**到 ~20 字"。实测这个启发式**会毁掉断句**：

```
[错] 按长度合并 → '开车时车辆突然向车道线偏移而你却没有察觉'（21字，把3句并成1条）
[对] 纯标点切分 → '开车时' / '车辆突然向车道线偏移' / '而你却没有察觉'
```

实测**纯标点切分对人工精调版 40/40 完全命中**结构，仅 1 处差异（拉丁词两侧空格）。
故最终实现为「**标点优先切分 + 超长强制拆分**」，不做长度打包。`display_text()`
负责去掉标点并恢复 CJK↔拉丁间距（`是智能网联汽车ADAS中…` → `是智能网联汽车 ADAS 中…`）。

**验收实测（对照入库基准 `examples/ldws-teaching/narration_sync4.srt`）**：

```
cues 40/40              unmatched 0
cue 文本完全一致 ✅      line-wrap 完全一致 ✅
start 偏差: 中位数 +0.050s   |均值| 0.119s   最大 0.539s
cue 间空隙: 全 0.0（butt-joined）
首条 0.100s / 末条 76.675s / 音频结束 76.675s
```

**"不是插值"的证明**（关键验收，已固化为契约测试）：对「cue 起点 ~ 累计字数」
做最小二乘拟合，取残差标准差：

| 时间轴 | 残差 stdev | 残差 max |
|---|---|---|
| `sync4`（人工精调基准） | 401.61 ms | 746.85 ms |
| **纯字数插值**（构造对照） | **0.00 ms** | **0.00 ms** |
| `phrase_aligner` 产出 | **504.31 ms** | 1005.16 ms |

纯插值必然落在一条直线上（残差 0）；残差 504ms 即证明时间戳来自音频。
声学时间与纯插值的**绝对差：中位数 0.436s / 最大 1.174s**。

**折行按显示宽度**：`是智能网联汽车 ADAS 中的一项预警功能` 是 21 字符但仅 36 列宽
（CJK 计 2），按"20 汉字"预算应留在一行 —— 按字符数算会无故拆行。

### 9.4 A3 —— 时长硬编码修复

**工具侧**（`tools/video/video_compose.py`，对**所有项目**生效）：

新增 `_check_narration_truncation()`，在 `_run_final_review()` 内被调用。从
`edit_decisions.audio.narration.src` 读旁白真实时长（ffprobe），与成片比较：

```
改动前输入 76.054s → "Narration truncated: rendered 76.054s but the narration is
                      77.256s — the last 1.202s of speech is missing."
正确输入 77.256s   → ok
更长（尾部音乐）   → ok（只惩罚"短于旁白"，不惩罚更长）
```

结论写入 `final_review.checks.technical_probe.narration_duration_check`，可审计。

> 原 25% 漂移阈值看不见这个缺陷：76.054 vs 77.256 只有 **1.6%** 漂移。

**项目侧**（`projects/ldws-teaching/index.tsx`）：

- `const DURATION = 76 * FPS` → `calculateMetadata` 用 `getAudioDurationInSeconds()`
  探测旁白与音乐，取 `max + 0.5s` 尾部；探测失败才回退 `NOMINAL_DURATION`
- `VideoLayer` / `SceneTitle` 的默认 `end` 改用 `useVideoConfig().durationInFrames`
- **顺带修掉**：末场 `SignalChainScene` 原 `end = 75 * FPS`，时长修正后会提前 1.7s
  淡出，收尾句「永远是最终的责任主体」会落在空背景上 → 改为 `durationInFrames`

**真机渲染实测**：

```
改动前: 76.054s（旁白 77.256s，末 1.202s 丢失）
改动后: 77.824s  帧数 2333 = ceil((77.256 + 0.5) × 30)
76.6s 抽帧确认末场信号链五节点仍在画面内
```

### 9.5 A4 —— 既有测试回归修复（覆盖度是提高，不是降低）

| 用例 | 修法 |
|---|---|
| `test_registry_catalog_views` | 原来硬编码 10 个 provider 的**精确集合**（必然随新增 provider 失效）。改为断言"catalog 是完整去重的汇总" + 关键 provider 存在 + 不含 selector |
| `TestPiperTTS::test_status_requires_piper_executable...` | 失败原因是本地补丁新增了"venv 同级 `piper` 二进制"回退。**没有删断言**，而是把 `sys.executable` 指向无同级二进制的路径；并**新增** `test_status_finds_piper_next_to_running_interpreter` 断言回退本身有效 |

### 9.6 A5 —— 新增回归测试（计划外）

| 文件 | 项数 | 内容 |
|---|---|---|
| `tests/contracts/test_subtitle_alignment_contracts.py` | 31 | 依赖前缀一致性、标点处理、断句结构复现、tick/秒双单位、未匹配标记、手工覆盖、butt 连续性、**非插值证明**、注册表发现 |
| `tests/contracts/test_examples_integrity.py` | 10 | `examples/` 哈希清单 + LDWS SRT 规范性（连续、无标点、文本一致） |
| `TestNarrationTruncationCheck`（并入 phase3） | 7 | 用真 ffmpeg 生成音频实测时长；覆盖截断/相等/更长/容差/各类跳过 |
| `tests/fixtures/ldws_tokens.json` | — | 167 个真实 edge-tts token，供离线测试（不联网） |

### 9.7 D5 —— 最终采用的 SRT 纳入受控位置

**问题**：`projects/` 被 gitignore → LDWS 手工精调字幕不可追溯。
**决策（用户拍定）**：纳入受控位置 → 新建 `examples/<slug>/`，**不放宽 `.gitignore`**
（`projects/` 下还有数百 MB 生成媒体，放宽会一并入库；`examples/` 是白名单收口）。

```
examples/ldws-teaching/
├── narration_sync4.srt   最终采用字幕（40 cue）
├── narration.txt         对应旁白全文
├── manifest.json         sha256 + 字节数
└── README.md             来源 / 为何入库 / 已知缺陷 / 校验方法
```

**形成约定**：工具可复现的产物留 `projects/`（不入库）；**人工拍定、需长期引用或作回归
基准**的产物，拷一份到 `examples/<slug>/` 入库，并由 `test_examples_integrity.py` 校验哈希。

### 9.8 测试基线变化

```
改动前: 843 passed,  2 failed, 7 skipped
改动后: 894 passed,  0 failed, 7 skipped
```

### 9.9 本次遗留 / 未做

- **未提交** `projects/ldws-teaching/index.tsx` 的 A3 改动所产出的新成片
  （A3 验证用的是 `--scale=0.25` 低清测试渲染，写在 `/tmp`，未覆盖交付物）。
  如需交付新版成片，需按完整参数重渲 + 重新烧字幕（属 Phase 3 的 B2 范围）。
- `projects/ldws-teaching` 内留了一个备份 `index.tsx.bak-preA3`（该目录不入库）。
- **仍待办**：Phase 4（C 组：APIYi 注册，**须先修 3 项会花钱的缺陷**）。
  ~~Phase 3（B 组）~~ 已于同日完成，见第 10 节。

---

## 10. Phase 3（B 组）实施记录（2026-09-24）

目标：让「字幕/时长」这类校验**具备证据效力**，而不是假通过。

### 10.1 改动前的复现（先立证据，再动手）

| 缺陷 | 复现方法 | 改动前实测结果 |
|---|---|---|
| B1 | 2 秒视频 + 唯一 cue 在 `00:16:39` 的 SRT | `subtitles_present=true`、`coverage_ratio=1.0`、`issues=[]`、`status=pass` |
| B2 | `crop` 底部条带 + `geq` 统计近白像素，取 7 个时间点 | master **全 0.000%**；final **0.983~3.069%** |
| B3 | 5 秒成片 + 20 秒旁白 | 已记录 `status=truncated / shortfall=15.064`，但 `status=pass` |
| B4 | `_srt_to_word_captions()` 读 40 条 CJK cue | 输出 **44** 个伪"词" |

### 10.2 B1 —— 新建 `tools/subtitle/srt_audit.py`

纯标准库（与 `phrase_aligner.py` 同一姿态）。对外函数：
`parse_srt()` / `audit_srt()` / `compare_cue_grid()` / `probe_bottom_band_ink()` /
`union_span()` / `file_sha256()` / `has_cjk()` / `normalise_text()`。

**一个必须记住的算术坑**：覆盖率要用**裁剪到视频窗口内**的并集。
我第一版没裁剪，结果那条 999s 的 cue 算出 `coverage_ratio=1.0` —— **和原缺陷一样错**。
裁剪后为 `0.0`。这正是「不可显示的 cue 不能计入覆盖」。

**严重度结构化**：`audit_srt()` 自己区分 `critical_issues`（文件根本不是这条片子的字幕轨、
cue 越界、乱序、不可解析）与 `issues`（如字幕比画面早结束几秒）。
不靠对消息文本做子串匹配。

**已删除**「文件存在即 `subtitles_present=true`」。现在要求**烧录证据**。

### 10.3 B2 —— atelier 先烧后审

**根因是顺序**：`final_review` 原先在烧录**之前**跑，所以结构上不可能看见字幕。
改动：`_render_via_atelier()` 在审查前调用新增的 `_burn_subtitles_with_record()`。

两个实现细节（都是踩过的坑）：
- **不能读写同一路径**：`_burn_subtitles` 直接写 `output_path`。若 input==output，
  ffmpeg 会失败或损坏文件。改为**烧到临时文件再原子替换**，顺便保证中断不会毁掉已渲染的 master。
- **记录必须含 sha256**：只有这样才能回答「烧进去的是不是声明的那个文件」。

尊重新增的 `edit_decisions.subtitles.burn_in`（schema 新字段，默认 `true`）。

实测：burn 前 ink `0.0%` → burn 后 `3.064%`；record 回填正确；无残留临时文件；抽帧目视
字幕位于底部中央。

### 10.4 B3 —— 根因与计划所写不同

计划写的是「25% 阈值过宽」。实测发现**该分支从未执行**：
- `total_duration_seconds` **不是**合法 `edit_decisions` 字段（schema `additionalProperties: false`）
  → 永远是 `None`；
- `metadata.target_duration_seconds` 合法，但**全仓无任何写入方**。

LDWS 的 `final_review.json` 里 `duration_drift_pct: None` 就是铁证。

**真正的修复**：`_run_final_review` 不再用关键词子串猜 `status`。各检查把致命发现登记进
`critical_issues`，`status` 由它派生；致命项 → `fail` + `re_render`（用户拍板）。
`_check_narration_truncation()` 改为**返回**发现，由调用方升级。

实测：同一 5s vs 20s 场景 `pass → fail`。

### 10.5 B4 —— 两处脱钩

- **声明源 ≠ 实际烧录源**：比对 sha256，不一致判 fail。（LDWS 的真实情形：声明
  `narration.srt`、实烧 `sync4`。）这也是为什么必须先有 B2 的 burn record 才能查这件事。
- **中文 `split()`**：CJK cue 不再切词，每 cue 一条、保留真实起止时间；英文仍逐词。
  实测 40 cue → 40 条；`hello brave new world` → 4 词。

### 10.6 计划外发现（都修了）

1. **`_resolve_subtitle_style` 对 schema 合法输入必然崩溃**
   schema 定 `subtitles.style` 为**字符串**（`"sentence"` / `"word-by-word"` / `"karaoke"`），
   代码却调 `.items()` → `AttributeError: 'str' object has no attribute 'items'`。
   LDWS 自己就写了 `"style": "sentence"` → **任何走 FFmpeg 烧录的路径都会崩**。
   改为按 schema 读平铺字段（`font`/`font_size`/`color`/`background`/`position`/`margin_v`…），
   同时保留对旧嵌套 dict 的兼容。

2. **A3 当时只做到「报告」，没做到「拦截」**
   `_check_narration_truncation` 只写 `issues`，从未影响 `status`。
   已在 Phase 1 记录里加注修正，并在本阶段接入 critical 通道。

3. **一条我自己引入的缺陷**（记下来避免重犯）：`_audit_subtitles` 最初把
   critical 项登记成一句**概括文本**（`"subtitles enabled but no burn evidence..."`），
   而 `issues` 里是**另一句详细文本**。结果 `critical_issues` 与 `issues_found` 对不上，
   读报告的人无法知道到底是什么被拦下。已改为**同一个字符串**贯穿三处。
   这个 bug 是被新写的契约测试
   （`test_critical_issues_are_recorded_structurally`）抓出来的。

4. **`burn_in: false` 的语义需要单独处理**（又一条，同样由测试抓出）
   第一版把"无 burn record"一律判 critical。但若 agent 显式声明
   `burn_in: false`（字幕由 composition 自己绘制），就**永远不会有 burn record**，
   于是合规的合成本绘制字幕路径会被误判为 fail。
   已改为区分两种情形：`burn_in: false` → 像素探针**仅作告警**（按决策，它本来就
   不能证明字幕缺失）；其余 → 无证据即 critical。这条恰好印证了"探针只作告警"的决策
   是对的：它是 composition 绘制路径下唯一可得的证据，但不足以定案。

### 10.7 上游文件标记

| 文件 | 标记数 | 说明 |
|---|---|---|
| `tools/video/video_compose.py` | 4 | B1/B2/B3/样式解析 |
| `tools/video/remotion_caption_burn.py` | 1 | B4 CJK |
| `schemas/artifacts/edit_decisions.schema.json` | 1 | 新增 `subtitles.burn_in` |

新增文件（非上游）：`tools/subtitle/srt_audit.py`、`tests/contracts/test_subtitle_verification_contracts.py`。

### 10.8 新增测试

`tests/contracts/test_subtitle_verification_contracts.py` —— **51 项**，全部离线确定性
（用 ffmpeg 现造 2 秒真 MP4，SRT 内联写入）：

- SRT 解析：`,1000` 畸形毫秒必须**拒绝**（严格解析器行为）、乱序、`end < start`、
  非数字序号**不丢 cue**、CRLF、空输入不崩；
- 覆盖率算术：重叠不重复计、**裁剪到窗口**、部分重叠只算可见部分；
- 越界/漂移/不同轨检出；
- **门禁行为**：越界 SRT 必须 fail、旁白截断必须 fail、声明≠实烧必须 fail；
- 可见性探针**只告警**（不会单独 fail 合规渲染）；
- `critical_issues` 与 `issues_found` 必须一致；
- `final_review` 产出仍满足自身 schema；
- 三种 `subtitles.style` 形状（schema 字符串 / 平铺 dict / 旧嵌套 dict）都不崩；
- 提交的参考 SRT：对 77.824s 渲染审计干净、对旧 76.054s 渲染**必须报越界**、SHA 稳定；
- **atelier 烧录顺序**（B2 核心）：stub 掉 Remotion 渲染后断言副作用顺序必须是
  `render → burn → review`、burn record 必须送达审查器、`burn_in:false` 与
  `enabled:false` 必须跳过烧录、烧录失败必须让整次渲染失败（绝不交付没上字幕的 master）。

### 10.9 测试基线

```
Phase 1 后: 1441 passed, 0 failed, 12 skipped      （全量 tests/）
Phase 3 后: 1492 passed, 0 failed, 12 skipped      （+51，无回归）
```

### 10.10 本次遗留 / 未做

- **未重渲 LDWS 成片**。交付物仍是旧版（76.054s，手工烧的 `sync4`）。
  `projects/ldws-teaching/artifacts/final_review.json` **仍是旧的手写产物**，
  新的审查器要等下次渲染才会重写它。
- **未做 OCR 真核验**（按决策，像素探针只作告警）。
- LDWS 历史产物按 Re-log 约定**只追加** `decision_log` 第 `d-007` 条记录实际交付来源，
  未改动既有 6 条、未改动 `edit_decisions`。
- **下一步：Phase 4（C 组）**，硬前置是先修 C0.1/C0.2/C0.3 三项会真花钱的缺陷。
