# OpenMontage 测试流程指南（中文）

> 面向本项目当前环境（2026-09-24 实测）。**每一步的命令都在本机跑过并附实测结果**；
> 未实测的部分会明确标注。配套背景见 `docs/USAGE_NOTES_zh-CN.md`（§13.7 是本指南涉及的 D11 修复）。

---

## 0. 先理解一件事：这不是一个「CLI 工具」

这是最容易踩的坑。OpenMontage **没有** `run` / `build` 这样的总入口命令：

- 仓库里**没有** `pipeline/` 模块（`python -m pipeline.run` 会报 `ModuleNotFoundError`）。
- 真正的「引擎」是**你 + 一个 AI agent**。Python 只提供两样东西：
  - **工具**（`tools/`）—— 真正干活的实现
  - **状态持久化**（`lib/checkpoint.py`）—— 把每个阶段的产物写到 `projects/<id>/`

也就是说：**流程由 agent 读 `pipeline_defs/*.yaml` 和 `skills/pipelines/**/*-director.md` 来推进**。
你看到的每条命令，都是「给 agent 用的一颗螺丝」，而不是一条完整流水线。

所以测试分两层：

| 层次 | 你测什么 | 谁在驱动 |
|---|---|---|
| **A. 工具层**（本指南重点） | 单个工具/渲染链路能不能跑通 | 你直接敲命令 |
| **B. 流程层** | 完整 8 阶段生产 | agent 读 yaml + skill 推进，你在审批点拍板 |

先把 A 层跑通，再进 B 层。**A 层全免费**。

---

## 1. 激活环境（每次新开 shell 必做）

```bash
export VIRTUAL_ENV=/home/fxbchc/CodeSpace/pythonenv/openmontage
cd /home/fxbchc/CodeSpace/AiVideoGeneration/OpenMontage
```

**为什么必须这样**：本机**没有 `.venv`**，而 `Makefile:4` 优先读 `$VIRTUAL_ENV`、找不到才回退到不存在的
`.venv`。不导出这个变量，`make` 会去建一个新的 `.venv` 并重新装依赖。

| 事实 | 值 |
|---|---|
| 真实解释器 | `/home/fxbchc/CodeSpace/pythonenv/openmontage/bin/python`（3.10.12）|
| 系统 `python` | **不存在** |
| `/usr/bin/python3` | 存在但**缺项目依赖**，不要用 |

> ⚠️ **另一个坑**：直接用 venv 的 python 跑脚本时，**cwd 必须是仓库根目录**。
> 在别处执行会 `ModuleNotFoundError: No module named 'tools'`（实测）。
> 想从任意目录执行，加 `export PYTHONPATH=/home/fxbchc/CodeSpace/AiVideoGeneration/OpenMontage`。

---

## 2. 第 1 步：预检（免费，只读）

```bash
make preflight
```

输出是 JSON 格式的完整能力清单。看三个关键字段：

```bash
# 只看合成运行时（决定你能不能渲染）
python -c "
from tools.video.video_compose import VideoCompose
print(VideoCompose().get_info()['render_engines'])
"
```

**2026-09-24 实测结果**：

| 运行时 | 状态 | 能否用 |
|---|---|---|
| `ffmpeg` | `True` | ✅ 稳定 |
| `remotion` | `True` | ✅ 稳定（**推荐**）|
| `hyperframes` | `False` | ❌ 缺 Chrome Headless Shell |

按 **HARD RULE**，agent 在提案阶段必须把 remotion 和 hyperframes **都**列给你。
hyperframes 现在如实报 `False`（D11 修复前会**谎报 `True`**）。
想启用它得先跑 `npx hyperframes browser ensure`（下载 152.0.7977.30，**不要中断**）。

---

## 3. 第 2 步：零密钥渲染（免费，**已实测通过**）

这是最安全的第一个测试：不需要任何 API key，走 Remotion 本地渲染。

```bash
make demo-list                      # 列出可用示例（免费）
make demo                           # 渲染全部 3 个（约 3–5 分钟）
```

**只想渲染一个**：`make` **不会**把参数传给 `render_demo.py`——
`make demo world-in-numbers` 会把 `world-in-numbers` 当成**另一个 make 目标**，
结果仍然渲染全部示例（实测：耗时且无提示）。要单个渲染请直接调脚本：

```bash
export VIRTUAL_ENV=/home/fxbchc/CodeSpace/pythonenv/openmontage
python render_demo.py world-in-numbers     # 只渲染这一个（推荐先这样）
```

三个示例：

| 名称 | 内容 |
|---|---|
| `code-to-screen` | 开发者工作流解说 + 对比卡 + KPI 卡 |
| `focusflow-pitch` | 只用 Remotion 组件搭的创业 pitch |
| `world-in-numbers` | 全球规模数据故事 + 标题/统计/图表 |

**实测输出**（`python render_demo.py world-in-numbers`，耗时约 1–2 分钟）：

```
projects/demos/renders/world-in-numbers.mp4   4.1 MB
```

ffprobe 校验：`h264 / 1920x1080 / aac / 23.06s` ✅

> 这一步能同时验证：Node + Remotion 链路、ffmpeg 编码、`projects/` 写盘。
> **如果这一步就失败，后面都不用试了。**

---

## 4. 第 3 步：看板（免费，只读）

```bash
python -m backlot open                # 项目列表
python -m backlot open ldws-teaching  # 打开已有项目
```

看板是**纯观察者**：它只读 `projects/<id>/` 下的 checkpoint 和产物，**永远不会阻塞流程**。
启动失败也不影响生产（这是设计如此）。

---

## 5. 第 4 步：查已有项目的进度（免费，只读）

```bash
python -c "
from pathlib import Path
import lib.checkpoint as c
d, pid = Path('projects'), 'ldws-teaching'
print('completed:', c.get_completed_stages(d, pid, 'animated-explainer'))
print('next     :', c.get_next_stage(d, pid, 'animated-explainer'))
"
```

**实测**：LDWS 已完成 8 个阶段（`research → proposal → script → scene_plan → assets → edit → compose → publish`），
`next: None` —— 即该流水线的阶段全部走完。

> 传入 `pipeline_type` 时返回 `next: None`；**不传**则会打印一句 fallback 警告并给出
> `next: idea`（那只是回退顺序的产物，不代表真要做的事）。所以**建议传** `pipeline_type`。

---

## 6. 免费资产工具（不花钱就能出素材）

实测可用性：

| 工具 | 状态 | 用途 |
|---|---|---|
| `edge_tts` | ✅ available | 中文旁白 + **词级时间戳**（免费）|
| `pixabay_music` | ✅ available | 免费 BGM |
| `diagram_gen` | ✅ available | 示意图 |
| `code_snippet` | ✅ available | 代码高亮截图 |
| `music_library` | ✅ available | 本地曲库 |
| `apiyi_image` | ✅ available | AI 生图（**$0.03/张，付费**）|
| `math_animate` / `video_selector` / `music_gen` | ❌ unavailable | — |

**实测**（免费 TTS 冒烟）：

```bash
python -c "
from tools.audio.edge_tts import EdgeTTS
t = EdgeTTS()
print('status:', t.get_status().value)
r = t.execute({'text':'这是一次免费语音测试。',
               'output_path':'/tmp/om_test_tts.mp3',
               'voice':'zh-CN-XiaoxiaoNeural'})
print('success:', r.success, 'err:', r.error)
"
```

实测：`status: available` / `success: True`，产出 15,840 字节 mp3 ✅

---

## 7. 三个测试档位：选一个开始

### 档位 1 —— 纯免费冒烟（**建议从这里开始**，0 元）

```bash
python render_demo.py world-in-numbers    # 渲染一个示例（免费）
make preflight                            # 确认能力清单
python -m backlot open                    # 看看板
```

**验证**：Node/Remotion/ffmpeg 链路 + 看板。**不碰任何付费接口。**

---

### 档位 2 —— 免费重渲染 LDWS（**0 元，但价值最高**）

`projects/ldws-teaching/` 是仓库里唯一完整走完 8 阶段的真实项目（77s 中文教学视频）。
**它的 16 个素材全部还在磁盘上**（实测 `missing on disk: none`），所以可以**零成本重渲染**。

```bash
# 1. 确认素材齐备
python -c "
import json, pathlib
m = json.load(open('projects/ldws-teaching/artifacts/asset_manifest.json'))
a = m.get('assets') or []
miss = [x.get('path') for x in a if x.get('path') and not pathlib.Path(x['path']).exists()]
print('assets:', len(a), '| missing:', miss or 'none')
"

# 2. 查看当前渲染设定
python -c "
import json
d = json.load(open('projects/ldws-teaching/artifacts/edit_decisions.json'))
print('render_runtime :', d.get('render_runtime'))
print('composition_mode:', d.get('composition_mode'))
print('subtitles      :', json.dumps(d.get('subtitles'), ensure_ascii=False))
"
```

实测输出：

```
assets: 16 | missing: none
render_runtime  : remotion
composition_mode: atelier
subtitles       : {"enabled": true, "style": "sentence", "source": ".../narration.srt"}
```

**为什么这个档位价值最高**：它能验证本次会话的全部修复——
旁白裁切（A 组）、字幕真实性校验（B 组）、atelier 烧字幕路径、时长漂移检查。
而**这些恰恰是旧版有 bug 的地方**。

> ⚠️ **注意**：`make` 里**没有**「重渲染 LDWS」这条命令。
> 这一步需要 agent 走 pipeline 的 `compose` 阶段（即 B 层流程），
> 不是一条可以复制粘贴的脚本。**你要做的是对 agent 说**：
> 「重渲染 ldws-teaching 的 compose 阶段，用现有素材，不要重新生成任何素材」。
>
> 现有的成片保留在 `projects/ldws-teaching/export/`（final 6.9 MB / master 19 MB），
> 重渲染前建议先备份。

---

### 档位 3 —— 真实付费生产（**花钱，需明确批准**）

想测「从 0 到成片」的完整流程时用。**先读第 8 节的成本表。**

对 agent 说一句话即可，例如：

> 「做一个 30 秒的中文动画解说，主题是 __，用 remotion，成本控制在 $1 以内」

agent 会按 Rule Zero 走 8 阶段，并在这些点**停下来等你批准**：
`proposal` → `script` → `scene_plan` → `assets` → `publish`。

**可用能力现状（实测）**：

| 能力 | 可用 provider | 说明 |
|---|---|---|
| `image_generation` | `apiyi` (1/17) | $0.03/张 |
| `tts` | `edge_tts`, `piper` | 免费 |
| `music_library` | `local` | 免费 |
| `subtitle` | 3/3 | 内置 |
| `video_post` | `ffmpeg` | 内置 |
| **`video_generation`** | **0/26** | ⚠️ **registry 里没有可用 provider** |

> ⚠️ **重要**：`video_generation` 是 **0/26**。Seedance 只能通过
> `.agents/skills/apiyi-seedance2-video-gen/scripts/generate_video.py` **脚本直调**，
> 不经过 registry。所以 pipeline 的 `video_selector` 会是 `unavailable`。
> 要做 AI 动态视频，得显式指定走脚本（这也是 C1b 未完成的原因）。

---

## 8. 成本参考（必须事先知情）

| 项目 | 单价 |
|---|---|
| `apiyi_image`（GPT Image 2）| **$0.03/张** |
| Seedance `mini` + 480p + 4–5s | 约 **¥1.16** |
| Seedance `standard` + 1080p + 5s | 约 **¥12.39** |
| Edge TTS / Pixabay BGM / ffmpeg / Remotion | **$0** |

**省钱策略**：先 `mini + 480p + 4s` 验证 prompt → 满意再升参数。

**LDWS 的历史成本**供参考：5 张 AI 图 + 8 个 Seedance mini 片段 ≈ **$1.46**。

> 🔴 **两条硬规矩**：
> 1. **未经你明确批准，不产生任何付费调用。**
> 2. 付费前 agent 必须报出 **tool / provider / model / 原因 / 是抽样还是批量**。
>
> Seedance 的计费**发生在任务创建被接受时**——预扣费，后续失败**不退**。
> 所以第一条尤其重要。

---

## 9. 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `make` 要新建 `.venv` | 没导出 `VIRTUAL_ENV` | 见 §1 |
| `ModuleNotFoundError: No module named 'tools'` | cwd 不在仓库根 | `cd` 到仓库根，或设 `PYTHONPATH` |
| `ModuleNotFoundError: No module named 'pipeline'` | 该模块**不存在** | 流程由 agent 驱动，见 §0 |
| `apiyi_image` 报 `unavailable` | 新 shell 没读 `.env` | `BaseTool._load_dotenv()` 只读 `.env`；确认 `.env` 里两把 key 非空 |
| `hyperframes` 显示不可用 | 缺 Chrome Headless Shell | 正常。用 `remotion` |
| Seedance 查询返回 401 | 见 D10 | 过期 ID 与路由故障**返回完全一致**，无法免费区分 |
| 看板打不开 | 设计上非致命 | 不影响生产，忽略即可 |

---

## 10. 本次测试的特别提醒

> **下次真正要生成视频时，顺手用那一次付费提交同时完成两件事，不要为此单独花钱：**
>
> | # | 事项 | 怎么做 |
> |---|---|---|
> | 1 | **D10 定论** —— Seedance 查询路由是否健康 | 提交成功后**立刻**用那个新鲜 `task_id` 查一次 `GET /seedance/api/v3/contents/generations/tasks/{id}`。任务已付费，这一步天然免费。返回 JSON → 路由正常；仍 401 → 路由确有问题 |
> | 2 | **C1b 验收** —— Seedance 包装成 BaseTool | 同一次提交就是端到端验收 |
>
> **背景**：工作区现存 10 个 `cgt-*` ID 全部是 32~110 天前，超过网关 **7 天**查询保留期，
> 而「已过期」与「路由故障」返回**完全一致**（皆 401），因此**无法免费判定**。
> 详见 `USAGE_NOTES_zh-CN.md` §11.11 / §11.12。
>
> **渲染运行时请选 `remotion`**（`ffmpeg` 也稳）；`hyperframes` 本机确实渲染不了。

---

## 11. 一句话总结

**先跑档位 1（`make demo`，0 元）确认链路，再决定要不要进档位 2（免费重渲染 LDWS）或档位 3（付费）。**

任何一步失败，把原始报错贴给我，我来定位。
