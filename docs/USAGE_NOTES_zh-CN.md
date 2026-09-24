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
