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
