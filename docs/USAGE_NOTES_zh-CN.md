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

### 6.0 ⏭️ 待办提醒（用户 2026-09-24 指定）

> **下次真正要生成视频时，顺手用那一次付费提交同时完成两件事，不要为此单独花钱：**
>
> | # | 事项 | 怎么做 |
> |---|---|---|
> | 1 | **D10 定论**——Seedance 查询路由是否健康 | 提交成功后，**立刻**用那个新鲜 `task_id` 查一次 `GET /seedance/api/v3/contents/generations/tasks/{id}`。这一步天然免费（任务已付费）。返回 JSON → 路由正常，D10 关闭；仍 401 → 路由确有问题 |
> | 2 | **C1b 验收**——Seedance 包装成 BaseTool | 同一次提交就是端到端验收：确认创建超时、ID 落盘、`--query` 回捞在真实链路上都生效 |
>
> **背景**：工作区现存 10 个 `cgt-*` 任务 ID 全部是 32~110 天前，超过该网关 **7 天**的查询保留期；
> 而"已过期"与"路由故障"返回**完全一致**（皆 401），因此**无法用免费方式判定**。
> 详见 `docs/USAGE_NOTES_zh-CN.md` §11.11 与 §11.12、`docs/DEV-PLAN-zh-CN.md` §5.3。
> **C1b 在此之前保持阻塞**——若路由确有问题，注册该工具等于交付一个必然失败、且每次提交都产生
> 已计费孤儿的工具。

### 6.1 激活环境

```bash
source /home/fxbchc/CodeSpace/pythonenv/openmontage/bin/activate
cd /home/fxbchc/CodeSpace/AiVideoGeneration/OpenMontage
```

> ⚠️ **工作区根目录的 `AGENTS.md`（不在 git 内）声称本项目用 `.venv`，那是错的** ——
> 该目录不存在。实际解释器是 `/home/fxbchc/CodeSpace/pythonenv/openmontage/bin/python`（3.10.12）。
> 系统无 `python` 命令，`/usr/bin/python3` 缺依赖。详见 §9.1。

### 6.2 先确认远程

```bash
git remote -v     # origin = 自己的 fork（可推）；upstream = 只读上游
```

### 6.3 查看已有项目与进度

```bash
# 列出项目
ls projects/

# 看某项目进展到哪个阶段（只读 checkpoint，不修改任何东西）
python -c "
from pathlib import Path
import lib.checkpoint as c
d, pid = Path('projects'), 'ldws-teaching'
print('completed:', c.get_completed_stages(d, pid, 'animated-explainer'))
print('next     :', c.get_next_stage(d, pid, 'animated-explainer'))
"

# 打开项目看板
python -m backlot open ldws-teaching
```

> ❗**原本文档这里写的 `python -m pipeline.run --pipeline ...` 是错的** ——
> 仓库**没有** `pipeline/` 这个模块（实测 `ModuleNotFoundError: No module named 'pipeline'`）。
> OpenMontage 的流程**不是**由一个 Python 编排器驱动的：**是 agent 自己读
> `pipeline_defs/*.yaml` + `skills/pipelines/**/*-director.md` 来推进**，
> Python 只提供工具（`tools/`）与状态持久化（`lib/checkpoint.py`）。见 `AGENT_GUIDE.md` 的
> "Orchestrator" 与 "Rule Zero"。已更正。

### 6.4 零密钥体验（不需要任何 API key）

```bash
make demo          # 用 Remotion 渲染示例视频
make preflight     # 查看当前能力清单
```

### 6.5 记录新问题与新结果

把发现追加到本文件，再 `git add docs/USAGE_NOTES_zh-CN.md && git commit -m "docs: update usage notes" && git push origin main`。

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
| `AGENTS.md` | mmx 可用 | ⚠️ 早期记为"配额已耗尽"——**该结论已过时**（见 §13.2 更正；实测 `mmx 1.0.22` 可用） |
| `.env` | 应有 API Key | 2026-09-24 前**逐字节等于 `.env.example`，全为空**；现已填入 APIYi 两把 key（`.env` 被 gitignore） |
| — | — | 官方 `image_generation` **0/16**、`video_generation` **0/26** 可用；真实凭据只在 `~/.bashrc` |
| — | — | ✅ venv 里**已有 pytest**（9.1.1，2026-09-24 装）；`requirements-dev.txt` 的 `httpx2` **不是笔误**（见 §13.2） |
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
| `requirements-dev.txt:5` | `httpx2>=2.0` | ✅ **不是笔误**（我先前的判断错了，见 §13.2）——它是 `openai` 依赖的真实包 |

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

---

## 11. Phase 4（C 组）实施记录（2026-09-24）

> 计划见 `docs/DEV-PLAN-zh-CN.md` §5。本轮范围经用户确认＝**C0.0–C0.3 + C1a**，
> 并**未花任何钱**（全程离线 + 只读 HTTP 探测）。
> 与原计划的两处口径修正见 §11.6。

### 11.1 C0.1 —— 创建任务超时不再写死 60s

**根因**：`generate_video.py:242` 的 `http_json(req, timeout=60)` 管的是**创建任务**的读超时。
创建请求要上传 base64 素材（2MB 首帧 → 约 2.7MB 文本）并可能排队，超过 60s 时客户端断连，
但**任务已在服务端创建并已预扣费**——用户看到"失败"，钱已花。

**改法**：
- 新增 `--create-timeout`（默认 `DEFAULT_CREATE_TIMEOUT = 300`）；轮询请求仍用短超时
  `DEFAULT_POLL_REQUEST_TIMEOUT = 30`（实测两者必须分离，已有测试锁定）。
- **创建请求绝不重试**：响应丢失时无法判断任务是否已创建，重试可能扣两次费。失败时明确
  提示"创建请求可能已生效"并给 `--query` 回捞指引。

### 11.2 C0.2 —— 任务 ID 先落盘，新增回捞入口

**根因**：拿到的 `task_id` 只 `eprint` 到 stderr，随后任何轮询/下载失败都直接 `return 1`，
ID 随之丢失 → 已付费任务变孤儿。

**改法**：
- 拿到 `task_id` 后**立即**原子落盘 `{mp4}.task.json`（`_atomic_write_json`：先写 `.tmp-<pid>`
  再 `os.replace`），含 `task_id` / `base_url` / `request_body` / `output_path` / `created_at` / `status`。
- 新增 `--query <task_id>` 与 `--resume <task.json>`，两者**只查询/下载、不创建**，因此不可能重复计费。
- `--prompt` 改为可选（回捞路径没有提示词）；无 `--query/--resume` 时仍强制要求。
- 抽出 `finish_task()` 供三条路径（首次轮询 / query / resume）共用，保证恢复路径与正常路径行为一致。
- 成功下载后把 `.task.json` 的 `status` 更新为 `succeeded` 并记 `completed_at`。

**⚠️ 计划口径修正**：原计划写的"加 `task_id` 回捞/**取消**入口"——**取消在该 provider 无法实现**。
实测 `DELETE /…/tasks/{id}` 返回 `200 text/html`、2870 字节，与一个确定不存在的路径
`/totally/not/a/route` 的响应**逐字节相同**（前端 SPA 兜底页）；`PUT`/`PATCH` 同理；
`api-details.md` 也从未提及 cancel。故本轮**只做"落盘 + 回捞"，不做"取消"**。

### 11.3 C0.3 —— 上传前校验（编码之前）

**根因**：`media_to_url()` 只判"文件存在"；`IMG_MIME` 未命中时**静默回落 `image/png`**；
格式/大小/边长**零校验**，且 base64 在**任何校验之前**就已构造——一个注定被拒的文件
先被完整读进内存编码，再被 API 拒绝。

**改法**：新增 `validate_image_file()`，**在编码前**校验
扩展名白名单（jpeg/png/webp/bmp/tiff/gif/heic/heif）、单张 `< 30MB`、边长 `(300,6000)px`、
宽高比 `(0.4,2.5)`；不合格直接 `ValueError`，不消耗内存也不发起调用。

**一处知情取舍**：边长校验需读图，用 Pillow。为保住脚本"纯标准库"的承诺，**惰性导入 PIL**，
缺失时降级为只校验格式/大小**并在 stderr 明示"未能读取尺寸"**——不假装校验过。Pillow 12.3.0
已装且 `requirements.txt:6` 已声明。

### 11.4 C1a —— `apiyi_image` 注册进 registry

新文件 `tools/graphics/apiyi_image.py`（**不在上游树内**，无需补丁标记）：

| 项 | 值 |
|---|---|
| `name` / `capability` / `provider` | `apiyi_image` / `image_generation` / `apiyi` |
| `dependencies` | `["env:APIYI_API_KEY"]` |
| `agent_skills` | `["apiyi-gpt-image-2-all-gen"]` |
| `estimate_cost` | **精确** `0.03 × n`（按次计费，非 token 估算） |
| 端点 | `POST /v1/chat/completions`（**非** `/v1/images/*`） |

- **不走 subprocess**：脚本逻辑内联为 `/tools/graphics/apiyi_image.py`，失败以 `ToolResult`
  返回而非丢失退出码。
- **被 selector 自动发现**（实测 `image_selector.fallback_tools` 含 `apiyi_image`），
  `pipeline_defs/*.yaml` 与 `Makefile` **无需改动**。
- 诚实声明能力：`supports["aspect_ratio"] = False`、`supports["seed"] = False`——
  该模型**无 `size` 参数、无 seed**，比例只能靠提示词引导，不假装支持。
- 部分失败**如实上报**：已写入的图片是真实且已付费的，`success=False` 但
  `data.partial_outputs` 保留、`cost_usd` 只按已产出张数计。

### 11.5 计划外发现并修复的 3 个缺陷（都在我自己新写的代码里）

| # | 缺陷 | 后果 | 处理 |
|---|---|---|---|
| 1 | URL 正则 `[^\s)\"'<>]+?\.(?:png\|jpg…)` 在扩展名处**截断**签名直链 | R2 签名在 query string 里 → 下载 403，**看起来像 CDN 故障，实为解析 bug** | 正则改为保留 `(?:\?…)?`，并加回归测试 |
| 2 | data URI 正则用 `[A-Za-z0-9+/=\s]+` **吞掉尾随散文** | 提取值含空格 → base64 解码失败 | 改为不含 `\s`（base64 本就无空格），加回归测试 |
| 3 | 本地参考图**硬编码** `data:image/png` | JPEG/WebP 被误标 mime，API 可能拒绝或错误解码（**vendor 脚本同样有此 bug**） | 新增 `extension_to_mime()`，加回归测试 |

三个回归测试都做了**变异验证**：把代码改回缺陷版本，测试**必定失败**；改回后文件与变异前
**逐字节相同**。

### 11.6 计划外发现并修正的文档失真（C4 相关）

两份 vendor SKILL.md 都写"**优先 Node.js 版本**，参数与 Python **一致/保持一致**"。实测**不成立**：

| 断言 | 实测结果 |
|---|---|
| Seedance 参数与 Python 一致 | `node generate_video.js --duration -1` → `ERR_PARSE_ARGS_INVALID_OPTION_VALUE`（"argument is ambiguous"）。**官方主推的"智能时长"在 Node 版完全无法使用**（自测 `parseArgs` 亦复现），Python 版正常 |
| 图片参数一致 | Node 图片脚本 `knownFlags` 里**没有 `-k`/`--api-key`**，实测报"未知参数 -k"；Python 版两者都有 |

**C4 裁定 ＝ Python**，已回写两份 SKILL.md 与 `api-details.md`（均为**非上游跟踪**文件）。
同一份 `api-details.md` 另补了计费时点、恢复纪律、以及"`GET` 401 不等于路由故障"的辨伪说明。

### 11.7 C2 —— 环境变量与文档登记

- `.env.example`（**上游跟踪** → 加 `# OpenMontage-local patch:` 标记）新增
  `APIYI_API_KEY=` / `APIYI_API_SEEDANCE_KEY=` 与注释掉的 `APIYI_BASE_URL=`。
- **实测过的坑**：`tests/contracts/test_env_example.py` 会把"值以 `#` 开头"判为假凭据。
  实测 `APIYI_API_KEY=   # 注释` → `dotenv_values` 得到 `'# note here'` → **测试失败**；
  注释**独立成行**安全、`KEY=` 空值安全。故本次注释一律独立成行（已过测试）。
- `.env`（**未跟踪**、已 gitignore）同步加入同样的空占位。**未写入任何真实密钥**——
  密钥仍在 `~/.bashrc`。实测 `_load_dotenv()` 只补不覆盖：shell 已 export 的值**不会被 .env 空值遮蔽**
  （两种情形都已实测，见 §11.9）。
- `docs/PROVIDERS.md`（**上游跟踪** → 补丁标记）新增 APIYi 章节、环境变量摘要行、
  快速上手表 `5b` 行、以及文末 provider 总表一行。

### 11.8 C0.0 —— **计划中的"路由健康探针"已取消（自我否决）**

原计划提出新增 C0.0"提交前探测查询路由是否健康，不健康就拒绝提交"。**经推敲后取消**，理由：
判定查询路由健康**必须用 7 天内的新鲜 task_id**，而用凭空编造的 ID 探测时，"已过期"
与"路由故障"的返回**完全一致**（都是 401）。因此该探针**不可能给出有效信号**，做出来
只是**安全剧场**。它的真实意图（"绝不丢失已付费任务"）已由 C0.2 的落盘 + 回捞完整覆盖。

### 11.9 实测证据汇总

**C0.1 / C0.2 / C0.3（离线，零花费）**

| 验证 | 结果 |
|---|---|
| `--create-timeout` 默认值 | 300s；轮询请求 30s（分离，有测试锁定） |
| 创建失败只调用 1 次 | ✅ 绝不重试（mutating 掉"不重试"→ 测试失败） |
| 落盘时机 | 首次轮询**之前** `.task.json` 已存在（变异验证：删掉落盘 → 测试失败） |
| 落盘原子性 | 目录无 `.tmp-*` 残留 |
| `--query` 成功路径 | 直接下载、**不创建**、`rc=0` |
| `--query` 运行中路径 | 正确进入轮询循环（3 次轮询后成功） |
| `--resume` | 从记录还原 `task_id` 与自定义 `base_url` |
| 参数守卫 | 无 prompt（非回捞）→ rc=1；`--query`+`--resume` 同用 → rc=1；记录缺失 → rc=1 |
| 校验（Pillow 在） | 200px 太小✓、7000px 太大✓、10:1 比例✓、`.txt` 格式✓、0 字节✓、超限✓、1024×1024 通过✓ |
| 校验时机 | 不合格文件在 base64 **之前**抛错（变异验证：去掉校验 → 2 个测试失败） |
| 无 Pillow 降级 | 只校格式/大小并明示"未能读取尺寸"，**不崩、不假装** |
| 零依赖承诺 | 核心路径仍仅标准库（`import` 清单已核） |

**C1a（离线，零花费）**

| 验证 | 结果 |
|---|---|
| registry 注册 | `apiyi_image` 已注册，`capability=image_generation`、`provider=apiyi` |
| selector 发现 | `image_selector.fallback_tools` 含 `apiyi_image` |
| 计费精确性 | `n=1`→0.03、`n=3`→0.09、`n=0`→0.03、`n=999`→0.30、`n="abc"`→0.03 |
| 端点正确 | 请求打到 `/v1/chat/completions`，**非** `/v1/images/*` |
| 签名 URL | 保留 query string（变异验证：改回截断版 → 测试失败） |
| data URI | 不吞散文、可成功解码（变异验证：改回吞空格版 → 测试失败） |
| 本地参考图 mime | `.jpg` → `data:image/jpeg`（变异验证：改回硬编码 png → 测试失败） |
| 真实形态解析 | markdown / 裸 URL / parts 列表 / 单 part dict 全部命中 |
| 拒稿不当成图片 | 纯文字回复 → `success=False`、**不产生空文件** |
| 部分失败 | 2 张中第 2 张失败 → `images_generated=1`、`cost_usd=0.03`（只为已产出付费） |
| 调用前置守卫 | >5 张参考图 / 参考图不存在 / 缺 key / 非 https base_url → 全部**零调用即拒绝** |

**C4（实测复现）**

```
node generate_video.js --duration -1 -p x
  → TypeError [ERR_PARSE_ARGS_INVALID_OPTION_VALUE]: Option '--duration' argument is ambiguous.
node generate_image.js -p test -k sk-x
  → 错误: 未知参数 -k，请使用 --help 查看帮助
python generate_video.py --duration -1 -p x     → 通过参数解析（仅报缺 key）
python generate_image.py --help                 → 正常列出 -k/--api-key
```

**只读 HTTP 探测（零花费，为 D10 与"取消"结论取证）**

| 探测 | 结果 |
|---|---|
| `GET /tasks/{32 天前的真实 id}` | 401 `AuthenticationError`（api 与 vip 双域名、3/3 次、两把 key 均同） |
| `POST /tasks` 空体 | 503 "Current group **SeeDance2** has no available channels…" → **鉴权通过、组名正确** |
| `POST` 有效模型 + 缺 `content` | 400 `MissingParameter` → 鉴权通过 |
| `POST` 无效模型 | 403 "该令牌无权使用模型：…" → 路由与鉴权都活着 |
| `POST /v1/chat/completions` 空体 | 503（到达 APIYi 路由）；`gpt-image-2-all` → 429 上游负载饱和（**瞬时**，非路由断裂） |
| `DELETE /tasks/{id}` | 200 `text/html` 2870B，与不存在的路径**逐字节相同** → **SPA 兜底，无 cancel 接口** |
| 历史任务真实性 | 8 个 mp4 全部 `succeeded`，`created_at → updated_at` 恰为 1.5~2.5 分钟（2026-08-23） |

### 11.10 测试基线

```
Phase 1 后:  1441 passed, 0 failed, 12 skipped
Phase 3 后:  1492 passed, 0 failed, 12 skipped   (+51)
Phase 4 后:  1564 passed, 0 failed, 12 skipped   (+72：APIYi 图片 40 + Seedance 脚本 32)
```

新测试文件：
- `tests/contracts/test_apiyi_image_contracts.py`（40）
- `tests/contracts/test_apiyi_seedance_script_contracts.py`（32）

> 写脚本测试时踩到一个坑并已修：假 `http_json` 若对**每次**调用都返回"创建成功"形状，
> 轮询会一直跑到 1200s 默认上限，**整个测试套件挂死**。现在 `run_script()` 会注入
> `--timeout 10` 兜底，并 stub `time.sleep`，且假响应第二次即返回终态。

### 11.11 D10 —— **未决，非"已确认故障"**（重要更正）

调查初期我看到"创建路由鉴权通过、查询路由却 401"，一度判断为**查询路由故障**。
**该结论已撤回**：`api-details.md` 明写 task_id **仅 7 天内可查**，而工作区内全部 10 个
`cgt-*` ID 均为 **32~110 天**前，磁盘上**无任何** 7 天内的任务。在"任务已过期"与"路由故障"
之间，前者是更简约的解释，且对过期 ID 与捏造 ID 的返回**完全一致**。

**定论 D10 需要一个 7 天内的新鲜 task_id**，即需要一次真实付费提交。**本轮未申请、未花费**；
其边际成本会在**下次真正生成视频时自然为零**（那次提交天然产出新鲜 ID）。

### 11.12 C1b（Seedance 视频工具）**保持阻塞**

未把 Seedance 包装成 `BaseTool`。原因是 D10 未决：**若查询路由真有问题，注册该工具等于
交付一个必然失败、且每次提交都产生已计费孤儿的工具**。C0.1–C0.3 的加固（创建超时、
ID 落盘、回捞入口、上传校验）已先行落地，为将来解封做好准备。

### 11.13 本次遗留 / 未做

- **未花任何钱**：无付费提交、无 API 生成调用（C1a 全程用假 `requests` + 断网护栏）。
- **未做 C1b**（理由见 §11.12）。
- **未做 C3 的"完整"部分**：`estimate_cost` 已实现且被测试覆盖；Seedance 侧的契约测试
  只覆盖脚本（非 registry 工具，因为 C1b 未做）。
- **D10 未决**（见 §11.11）——需新鲜 task_id，因此需一次付费提交。
- 未改动 LDWS 任何产物；未重渲成片。

---

## 13. Phase 5（收尾卫生）实施记录（2026-09-24）

> 本轮为**用户测试前的准备**：修正文档失真、让测试路径真正可用。**未改任何业务流程代码。**

### 13.1 🔴 关键发现：新 shell 里图片工具是 UNAVAILABLE（会直接卡住测试）

用户准备做一次真实的视频测试，但**当时的默认 shell 里 `APIYI_API_KEY` 未导出**：

```
APIYI_API_KEY          = UNSET
APIYI_API_SEEDANCE_KEY = UNSET
→ registry.get('apiyi_image').get_status() == 'unavailable'
```

**根因**：`BaseTool._load_dotenv()` **只读仓库 `.env`**，不读 `~/.bashrc`；
而仓库 `.env` 里这两个键只是**空占位**。密钥实际只存在于 `~/.bashrc`，
于是"注册了工具"≠"工具可用" —— 任何走图片生成的测试都会在**第一步就失败**。

**处理**（经用户授权用于测试）：把两把 key 从 `~/.bashrc` **填入 `.env` 的空占位**。

- **不覆盖**：只在值**为空**时填充；已有真实值一律不动。
- **不泄露**：全程用脚本写入，日志只打印 `len`，不打印值。
- **不进库**：`.env` 被 `.gitignore:44`（`*.env`）忽略，且 `git ls-files` 确认**从未被跟踪**。

**验证**（新 shell，显式 unset 两个变量后）：

```
apiyi_image: available          ✅
GET https://api.apiyi.com/v1/models -> HTTP 200, 289 models
  gpt-image-2-all present: True ✅（真实凭据有效，非假可用）
```

> **教训**：`可用` 有三个层次——**已注册 / 已配置 / 已验活**。
> 只查 registry 会看到 `available` 或 `unavailable`，但**凭据是否真能用**必须打一次只读端点才知道。
> 本轮的 `/v1/models` 探测**零花费**。

### 13.2 ✅ 更正我自己的两处错误结论

**（1）`httpx2` 不是笔误 —— 我先前判断错了。**

早期笔记写 `requirements-dev.txt:5` 的 `httpx2>=2.0` "疑似笔误，应为 `httpx`"。
**实测证明那是错的**：

```
pip show httpx2  →  Name: httpx2   Version: 2.12.0
                    Home-page: https://github.com/pydantic/httpx2
                    Requires: anyio, httpcore2, idna, truststore, typing-extensions
                    Required-by: openai
pip show openai  →  Requires: anyio, httpx2, jiter, pydantic, sniffio, typing-extensions
                    其中 httpx2<3,>=2.7.0
```

`httpx2` 是 **pydantic 维护的真实 PyPI 包**（httpx 的下一代），由 `openai` SDK 引入。
**该行无需改动**，已更正 `USAGE_NOTES` §8.1 与本表。

**（2）"mmx 配额已耗尽"是过时结论。**

实测 `mmx 1.0.22` 命令**存在且可执行**，`~/.mmx/config.json` 存在（2026-08-21 写入）。
是否仍受配额/额度限制**需要实际调用才知道**，不应继续当作既成事实。
已从"现实"栏改为待验证项。

### 13.3 其余环境事实复核

| 项 | 结论 |
|---|---|
| 仓库内 `AGENTS.md` | 9 行，仅指向 `AGENT_GUIDE.md` → ✅ **正确，无需改** |
| 工作区根 `AGENTS.md` | 仍声称用 `.venv` → ❌ 失真，但**权限 `-r--r--r--` 且不在 git 内**，无法也不应改；已在 §9.1 与本文档标注 |
| `remotion-composer/node_modules` | 存在（133 项）→ Remotion 渲染就绪 |
| `ffmpeg` | 4.4.2 → 就绪 |
| `node` | v24.19.0（HyperFrames 需 ≥22）→ 就绪 |
| 三个合成运行时 | `ffmpeg / remotion / hyperframes` **全部可用** |
| pytest | 9.1.1 已装 → `make test` 可用 |

### 13.4 用 `make` 需要先指认真实环境

`Makefile:4` 的 `RUN_PYTHON` 会**优先用 `$VIRTUAL_ENV`**，然后才回落到 `.venv`。
由于本机没有 `.venv`，直接 `make xxx` 会指向不存在的路径。**正确用法**：

```bash
export VIRTUAL_ENV=/home/fxbchc/CodeSpace/pythonenv/openmontage
make preflight      # ✅ 实测可用
```

**已实测**：`make preflight` 在设置 `VIRTUAL_ENV` 后正常输出完整能力清单。

### 13.5 本轮测试基线

```
Phase 4 后:  1564 passed, 0 failed, 12 skipped
Phase 5 后:  1564 passed, 0 failed, 12 skipped   （仅文档 + .env 变更，无回归）
```

### 13.6 未做

- **未改动任何业务流程代码**（`tools/`、`lib/`、`skills/`、`pipeline_defs/` 均未动）。
- 未修改工作区根 `AGENTS.md`（只读且不在 git 内）。
- 未修复"工作区 `AGENTS.md` 的 `.venv` 失真"本身 —— 只能绕过，无法从仓库侧修。
