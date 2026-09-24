---
name: apiyi-seedance2-video-gen
description: AI视频生成技能，使用字节跳动 Seedance 2.0 视频生成模型（doubao-seedance-2-0-260128 标准版 / doubao-seedance-2-0-fast-260128 极速版 / doubao-seedance-2-0-mini-260615 轻量版），当用户需要生成视频、文生视频、图片转视频、首尾帧视频、参考图生视频、制作视频素材/短片/动效时使用此技能。基于API易平台(https://api.apiyi.com/)的 Seedance 2.0 官方资源，无需访问外网。支持4-15秒可控时长、480p/720p/1080p三档分辨率、6种宽高比+adaptive自适应、默认带同步音频（人声/音效/配乐）、seed可复现，脚本自动完成"提交任务→轮询→下载保存mp4"全流程。即使用户只说"帮我做个视频"、"把这张图片做成动态视频"、"生成一段动画/短片"，也应使用本技能。
---

# 视频生成（Seedance 2.0）Skill

基于 API易 平台接入火山引擎 Seedance 2.0 官方视频生成资源，通过自然语言帮助用户生成视频。三模型并行：

| 别名 | 模型 ID | 定位 | 最高分辨率 |
|------|---------|------|-----------|
| `standard` | `doubao-seedance-2-0-260128` | 最高画质，唯一支持 1080p | 1080p |
| `fast` | `doubao-seedance-2-0-fast-260128` | 画质与成本折中 | 720p |
| `mini` | `doubao-seedance-2-0-mini-260615` | **单价约标准版一半、生成最快**，批量出片首选 | 720p |

## 使用指引

### 第1步：分析需求与参数提取

1. **明确生成模式**（三种图生模式互斥）：
   - **文生视频**：纯文字描述 → 只传 `-p`
   - **首帧/首尾帧**：用户给了 1 张图作首帧（`--first-frame`），或 2 张图控制首尾画面（`--first-frame` + `--last-frame`）
   - **多模态参考**：用户给参考图/视频/音频，希望保持角色与风格一致（`--reference-image` 最多 9 张、`--reference-video` / `--reference-audio` 最多 3 段）

2. **提示词（Prompt）**：
   - **使用用户原始完整输入**作为 `-p` 的主体，避免自行改写、总结或二次创作，防止细节丢失。
   - 信息不足（缺主体动作、镜头运动、光线风格、时长等）时先向用户提问确认，确认后**以追加方式**拼接到原始提示词后。
   - 建议结构：「主体 + 动作 + 镜头运动 + 光线/风格」；中文 ≤500 字、英文 ≤1000 词。
   - 需要角色说话时，台词放双引号内可显著优化配音效果（`generate_audio` 默认开启）。

3. **关键参数**：
   - **Model（可选，默认 mini）**：用户要 1080p/最高画质 → `standard`；成本敏感/批量 → `mini`；折中 → `fast`。未明确指定时用 `mini`（最便宜最快）。
   - **Resolution（可选，默认 720p）**：`480p` / `720p` / `1080p`（1080p 仅 standard；mini/fast 传 1080p 会报 400，不扣费但不友好，提前规避）。
   - **Ratio（可选，默认 adaptive）**：`16:9` 横屏 / `9:16` 竖屏 / `1:1` 方形 / `4:3` / `3:4` / `21:9` / `adaptive` 自适应。图生视频推荐保持 `adaptive`（按首帧图自动适配，避免裁剪）；**同档位全比例同价**，横竖屏切换零成本。
   - **Duration（可选，默认 5）**：4–15 整数秒，或 `-1` 智能时长。**费用与时长线性相关**，不确定节奏时用 5 秒先验证。
   - **音频（默认开启）**：用户明确说不要声音/后期自行配音时加 `--no-audio`。
   - **Filename（可选）**：输出 mp4 路径，建议根据内容起有意义的文件名（如 `sunset_sea.mp4`），避免通用名；不传则自动生成带时间戳的文件名。

### 第2步：环境检查与命令执行

> ⚠️ **本仓库优先使用注册工具，不是脚本**（2026-09-24 起）
>
> OpenMontage **已经把这个能力包装成一等工具** `apiyi_seedance_video`
> （`tools/video/apiyi_seedance_video.py`），`video_selector` 能自动发现它。
>
> **在 OpenMontage 流水线里，请调用工具（走 registry），不要跑下面的脚本。**
> 跑脚本会导致：产物不进 `asset_manifest`、不触发 cost 记账、`events.jsonl` 无记录
> （LDWS 项目当年就是这样做的，它的 manifest 里写着一个代码库里不存在的工具名）。
>
> 脚本仍然有效，适用于**脱离流水线的单条试片**场景。
>
> | 场景 | 用什么 |
> |---|---|
> | 流水线内的 asset 阶段 | **`apiyi_seedance_video` 工具**（经 `video_selector`）|
> | 想快速试一个 prompt / 手工出片 | 下面的 `scripts/generate_video.py` |
>
> 工具与脚本的**参数语义一致**，差异只有三点（工具已内建处理）：
> ① 工具用 `Accept-Encoding: identity` 绕过网关 gzip 头不匹配（脚本同样有）；
> ② 工具按次计价（与脚本的费用速查表一致）；
> ③ **该网关无法取消任务** —— 工具的 `task_action="cancel"` 会明确报错。

1. **检查环境**：确认 `APIYI_API_SEEDANCE_KEY` 环境变量已设置（通常假定已设置，运行失败再提示用户）。令牌须勾选 `SeeDance2` 分组且计费模式为「按量优先」，否则报「该模型无可用渠道」。
2. **构建并运行命令**（仅在脱离流水线、手工试片时）：
   - **优先使用 Python 版本**：`scripts/generate_video.py`（仅用标准库，无需 pip install）。
     ⚠️ **本仓库已裁定 Python 为准**（2026-09-24 实测）——原文档"优先 Node、参数与 Python 一致"
     的说法**不成立**，见下方"Node 版本已知缺陷"。
   - Node 版本 `scripts/generate_video.js` 仅在无 Python 可用时使用，且**不支持** `--duration -1`。

   **Node 版本已知缺陷（实测复现）：**

   | 缺陷 | 表现 |
   |---|---|
   | `--duration -1` 不可用 | `parseArgs` 抛 `ERR_PARSE_ARGS_INVALID_OPTION_VALUE`（"argument is ambiguous"）——官方主推的"智能时长"在 Node 版**完全无法使用**（写成 `--duration=-1` 才可能绕过），Python 版正常 |
   | 参数并非"与 Python 一致" | 上一条即反例；此处文档已更正 |

   **Python 版本已加固（本仓库补丁）**：`--create-timeout` 可配（创建是计费步骤，原写死 60s
   会在任务已创建扣费后误报失败）、任务 ID 先落盘 `.task.json` 再轮询、`--query` / `--resume`
   回捞入口、上传前校验格式/大小/边长。详见仓库 `docs/PROVIDERS.md` 的 APIYi 章节。

   **文生视频命令模板：**
   ```bash
   node scripts/generate_video.js -p "{prompt}" -m {model} -f "{filename}" [--resolution 720p] [--ratio adaptive] [--duration 5] [--no-audio]
   ```

   **首帧/首尾帧命令模板：**
   ```bash
   node scripts/generate_video.js -p "{prompt}" --first-frame "{img}" [--last-frame "{img2}"] -f "{filename}"
   ```

   **多模态参考命令模板：**
   ```bash
   node scripts/generate_video.js -p "{prompt}" --reference-image "{img1}" [--reference-image "{img2}"] -f "{filename}"
   ```

   （Python 版把 `node scripts/generate_video.js` 换成 `python3 scripts/generate_video.py` 即可，参数完全一致。）

### ⏱️ 长时间任务处理策略

**执行前必须告知用户**：
- "视频生成已启动，预计需要 2–5 分钟（mini 更快，约 1.5–2.5 分钟；1080p 或 15 秒更长）"
- 脚本是异步任务式调用：提交 → 每 20 秒轮询 → 成功后自动下载 mp4 和元数据 JSON。终端会持续输出状态，属正常现象，耐心等待即可。

### 第3步：结果反馈

1. **成功**：脚本输出 JSON 结果（video 路径、size_mb、tokens、实际 duration/ratio/resolution/seed）。告知用户视频保存路径、文件大小、实际参数。任务元数据保存在同名 `.json` 文件中，可用于复现（seed）与对账（tokens）。
2. **失败**：
   - 缺 API Key → 指导用户设置 `APIYI_API_SEEDANCE_KEY`
   - 报「该模型无可用渠道」→ 令牌未勾选 `SeeDance2` 分组，指导用户到控制台勾选
   - 400 参数错误 → 按报错信息修正参数（不扣费）
   - 403 → 内容审核拦截（真人人脸/违规内容），更换素材或调整提示词
   - 任务 failed → 查看 error 字段，必要时换 seed 重试

## 命令行使用样例

### 文生视频

```bash
# 基础文生视频（mini，720p，5 秒，带音频）
node scripts/generate_video.js -p "无人机航拍视角飞越秋天的山谷，金黄色的森林和蜿蜒的河流，电影感" -f "valley.mp4"

# 竖屏短视频（9:16）
node scripts/generate_video.js -p "一只橘猫在窗台上晒太阳，镜头缓慢推近，温馨氛围" --ratio 9:16 -f "cat.mp4"

# 1080p 高清（仅标准版支持）
node scripts/generate_video.js -p "雪山脚下的湖泊倒映着星空，延时摄影效果" -m standard --resolution 1080p -f "stars.mp4"

# 不要声音（后期自行配音）
node scripts/generate_video.js -p "海浪拍打礁石，慢镜头" --no-audio -f "wave.mp4"

# 10 秒长视频 + 固定 seed（便于复现类似结果）
node scripts/generate_video.js -p "樱花飘落的日本街道，女孩撑伞走过" --duration 10 --seed 12345 -f "sakura.mp4"

# 带台词（自动生成人声配音）
node scripts/generate_video.js -p "夜晚天台，男人望着城市灯火说：\"总有一天，我会站在这座城市的顶端。\"，电影感" -f "rooftop.mp4"
```

### 首帧 / 首尾帧生视频

```bash
# 首帧图生视频（ratio 保持 adaptive，按图片自动适配）
node scripts/generate_video.js -p "让画面动起来：人物眨眼微笑，微风吹动头发" --first-frame "photo.png" -f "alive.mp4"

# 首尾帧：画面从 first 平滑过渡到 last
node scripts/generate_video.js -p "画面从第一帧平滑过渡到最后一帧，镜头缓慢运动" --first-frame "first.jpg" --last-frame "last.jpg" -f "transition.mp4"
```

本地图片会自动转 Base64 上传；也可直接传公网 URL 或 `asset://` 素材 ID。

### 多模态参考生视频

```bash
# 参考图保持角色/风格一致（最多 9 张）
node scripts/generate_video.js -p "以参考图的角色和风格，生成角色在雨夜街头行走的镜头" --reference-image "character.png" -f "rainy.mp4"

# 参考视频 + 参考图（编辑/延长已有视频）
node scripts/generate_video.js -p "延续参考视频的动作，让角色转身面对镜头" --reference-video "https://example.com/clip.mp4" --reference-image "style.png" -f "extended.mp4"
```

### 多段视频接力（连续长视频）

```bash
# 第一段：返回尾帧
node scripts/generate_video.js -p "..." --return-last-frame -f "part1.mp4"
# 第二段：用第一段尾帧作首帧（尾帧保存为 part1_last_frame.png）
node scripts/generate_video.js -p "..." --first-frame "part1_last_frame.png" --return-last-frame -f "part2.mp4"
```

## 命令行参数说明

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `-p` / `--prompt` | 是 | — | 视频描述提示词（中文≤500字/英文≤1000词），保留用户原始完整输入 |
| `-m` / `--model` | 否 | `mini` | `standard` / `fast` / `mini` 或完整模型 ID |
| `-f` / `--filename` | 否 | 自动时间戳 | 输出 mp4 路径 |
| `--resolution` | 否 | `720p` | `480p` / `720p` / `1080p`（1080p 仅 standard） |
| `--ratio` | 否 | `adaptive` | `16:9`/`4:3`/`1:1`/`3:4`/`9:16`/`21:9`/`adaptive`；同档位全比例同价 |
| `--duration` | 否 | `5` | 4–15 整数秒，或 `-1` 智能时长（按实际产出计费） |
| `--no-audio` | 否 | 生成音频 | 加此 flag 关闭同步音频 |
| `--watermark` | 否 | 无水印 | 加此 flag 添加「AI 生成」水印 |
| `--seed` | 否 | 随机 | [-1, 2^32-1]，相同 seed 结果类似 |
| `--first-frame` | 否 | — | 首帧图片（本地路径/URL/asset://） |
| `--last-frame` | 否 | — | 尾帧图片，需与 `--first-frame` 同用 |
| `--reference-image` | 否 | — | 参考图，可重复最多 9 张 |
| `--reference-video` | 否 | — | 参考视频（URL/asset://），可重复最多 3 段，2–15 秒 |
| `--reference-audio` | 否 | — | 参考音频（URL/asset://），可重复最多 3 段，需搭配图或视频 |
| `--return-last-frame` | 否 | 否 | 返回尾帧 png，用于多段接力 |
| `--poll-interval` | 否 | 20 | 轮询间隔秒数 |
| `--timeout` | 否 | 1200 | 整体等待上限秒数 |

## 费用速查（输入不含视频，16:9 / 5 秒，官方锚点价）

| 分辨率 | standard | fast | mini |
|--------|----------|------|------|
| 480p | ¥2.31 | ¥1.86 | ¥1.16 |
| 720p | ¥4.97 | ¥4.00 | ¥2.50 |
| 1080p | ¥12.39 | — | — |

- 站内名义扣费约官网 1.1 倍；费用与时长线性相关（15 秒 ≈ 3 × 5 秒）；同档位全比例同价
- token 公式：`token ≈ 时长 × 宽 × 高 × 24 / 1024`，实际用量以结果中的 `tokens` 为准
- 参数错误（400）不扣费；提交预扣费、完成后多退少补
- **省钱建议**：先 mini + 480p + 4~5 秒验证 prompt，满意后再升分辨率/时长/换标准版

## 注意事项

- **令牌分组**：API Key 必须勾选 `SeeDance2` 分组（计费模式按量优先/按量计费），否则报「该模型无可用渠道」。获取/配置令牌：https://api.apiyi.com
- **成功状态是 `succeeded`**，不是 `completed`
- **视频直链 24 小时过期**：脚本成功后立即自动下载，无需担心；手动下载时不要带 Authorization 头
- **生成耗时**：通常 1.5–5 分钟（mini 最快）；脚本默认等待上限 20 分钟，超时后会给出 task_id 供手动查询
- **真人人脸限制**：不支持含真人人脸的输入素材（403 拦截）；AI 生成人脸/虚拟人像可用
- **当前会话变量未生效**：`APIYI_API_SEEDANCE_KEY` 刚写入 `~/.bashrc` 时，已打开的会话/非交互 shell 可能读不到。脚本报缺 Key 时，先从 ~/.bashrc 提取加载再运行：`export APIYI_API_SEEDANCE_KEY=$(grep '^export APIYI_API_SEEDANCE_KEY' ~/.bashrc | cut -d'"' -f2)`，或用 `--api-key` 显式传入
- **三种图生模式互斥**：首尾帧 / 首帧 / 多模态参考不能混用，脚本会提前拦截
- **不支持** `frames`、`camera_fixed` 参数（Seedance 1.x 能力），帧率固定 24fps
- 输出文件旁会生成同名 `.json` 元数据（含 seed、实际 ratio/duration、tokens），用于复现与对账

### API Key 设置

```bash
# Linux/Mac（Seedance 2.0 专用变量）
export APIYI_API_SEEDANCE_KEY="sk-your-api-key"
```

没有 Key 时前往 https://api.apiyi.com 注册 → 控制台创建令牌 → **勾选 `SeeDance2` 分组**、计费模式选「按量优先」。

## 文件资源说明

| 资源 | 说明 |
|------|------|
| [`scripts/generate_video.js`](scripts/generate_video.js) | Node.js 版本（零依赖，优先使用） |
| [`scripts/generate_video.py`](scripts/generate_video.py) | Python 版本（仅标准库，Node 不可用时用） |
| [`references/api-details.md`](references/api-details.md) | API 深度参考：端点、参数全表、分辨率像素表、计费、错误码、状态机、最佳实践。遇到报错或需要细节时按需加载 |
