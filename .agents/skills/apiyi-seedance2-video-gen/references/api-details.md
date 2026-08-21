# Seedance 2.0 API 详细参考（API易）

本文档为 `apiyi-seedance2-video-gen` 技能的深度参考资料，包含分辨率像素表、计费、错误码、状态机等细节。脚本已封装大部分逻辑，遇到问题时查阅。

## 端点

| 端点 | 用途 |
|------|------|
| `POST https://api.apiyi.com/seedance/api/v3/contents/generations/tasks` | 创建视频生成任务 |
| `GET https://api.apiyi.com/seedance/api/v3/contents/generations/tasks/{id}` | 查询任务状态 / 获取视频地址 |

- 路径前缀是 `/seedance/api/v3`，**不要漏掉 `/api`**，也不要走 `/v1/videos`
- 域名可用 `api.apiyi.com`（主）或 `vip.apiyi.com`
- 请求头必须：`Authorization: Bearer <key>`、`Content-Type: application/json`
- Python requests 用户须加 `Accept-Encoding: identity`（网关 gzip 头与实际编码不符，否则报 `ContentDecodingError` 或拿到截断 JSON）。本技能脚本（urllib / fetch）已处理，不受此影响
- 令牌必须勾选 **`SeeDance2` 分组**，计费模式为「按量优先」或「按量计费」，否则报「该模型无可用渠道」

## 请求参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `model` | string | ✓ | — | `doubao-seedance-2-0-260128`（标准版，支持 1080p）/ `doubao-seedance-2-0-fast-260128`（极速版，最高 720p）/ `doubao-seedance-2-0-mini-260615`（轻量版，最高 720p，单价约标准版一半、生成最快）。写纯 ID，不带 `ep-` 前缀 |
| `content` | array | ✓ | — | 输入信息数组（见「生成模式」） |
| `resolution` | string | | `720p` | `480p` / `720p` / `1080p`（1080p 仅标准版） |
| `ratio` | string | | `adaptive` | `16:9` / `4:3` / `1:1` / `3:4` / `9:16` / `21:9` / `adaptive`；同档位全比例同价 |
| `duration` | int | | `5` | 4–15 整数秒；`-1` 模型智能选时长（按实际产出计费） |
| `generate_audio` | bool | | `true` | 生成同步音频（人声/音效/配乐，单声道）。**注意默认 true**，不需要声音时显式传 false |
| `watermark` | bool | | `false` | 右下角「AI 生成」水印 |
| `seed` | int | | `-1` | [-1, 2^32-1]；相同 seed 生成类似（不保证一致）结果 |
| `return_last_frame` | bool | | `false` | 返回尾帧 png（无水印），用于多段视频接力 |
| `execution_expires_after` | int | | `172800` | 任务过期阈值（秒）[3600, 259200] |

**不支持** `frames`、`camera_fixed`、`service_tier` 参数（Seedance 1.x 的能力），帧率固定 24fps。

## 生成模式（content 组合）

| 模式 | content 组成 | role |
|------|--------------|------|
| 文生视频 | 1 个 `text` | — |
| 首尾帧 | text（可选）+ 2 个 `image_url` | 必填 `first_frame` / `last_frame` |
| 首帧 | text（可选）+ 1 个 `image_url` | `first_frame` 或不填 |
| 多模态参考 | text + 0–9 `image_url`（+ 可选 0–3 `video_url` / 0–3 `audio_url`，至少 1 图或 1 视频） | `reference_image` / `reference_video` / `reference_audio` |

- 三种图生场景**互斥**
- 图片支持：公网 URL、Base64（`data:image/png;base64,...`）、素材 ID（`asset://...`）
- 图片格式 jpeg/png/webp/bmp/tiff/gif/heic/heif；宽高比 (0.4, 2.5)；边长 (300, 6000)px；单张 < 30MB
- 参考音频 wav/mp3、单段 2–15s、最多 3 段、需与图片或视频一起传
- **不支持含真人人脸的输入素材**（上游内容安全拦截）；AI 生成人脸/虚拟人像可用（通道自带白名单）

## 响应与状态机

创建成功只返回任务 ID：`{"id": "cgt-..."}`

状态机：`queued → running → succeeded / failed / expired`

- 成功状态是 **`succeeded`**（不是 `completed`）
- 视频地址在 **`content.video_url`**（不在顶层），签名直链 **24 小时过期**，成功后立即下载转存；下载时**不要带 Authorization 头**
- task_id 7 天内可查询
- `usage.completion_tokens` 为计费 token 数
- `duration: -1` 或 `ratio: adaptive` 时，实际值以查询响应的 `duration` / `ratio` 字段为准

成功响应样本：

```json
{
  "id": "cgt-20260606160057-6bbjd",
  "model": "doubao-seedance-2-0-fast-260128",
  "status": "succeeded",
  "content": { "video_url": "https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/....mp4?X-Tos-Expires=86400&..." },
  "usage": { "completion_tokens": 108900, "total_tokens": 108900 },
  "seed": 97151, "resolution": "720p", "ratio": "16:9", "duration": 5,
  "framespersecond": 24, "generate_audio": true
}
```

## 分辨率像素表（各档位定义像素面积，全比例同价）

| 宽高比 | 480p | 720p | 1080p（仅标准版） |
|--------|------|------|-------------------|
| 16:9 | 864×496 | 1280×720 | 1920×1080 |
| 4:3 | 752×560 | 1112×834 | 1664×1248 |
| 1:1 | 640×640 | 960×960 | 1440×1440 |
| 3:4 | 560×752 | 834×1112 | 1248×1664 |
| 9:16 | 496×864 | 720×1280 | 1080×1920 |
| 21:9 | 992×432 | 1470×630 | 2206×946 |

adaptive 适配规则：文生视频按提示词内容选比例；首尾帧/首帧按首帧图片比例选最接近的；多模态参考按提示词意图或第一个媒体文件。

## 计费

- token 公式：`token ≈ 时长(秒) × 宽 × 高 × 24 / 1024`（输入含视频时，时长 = 输入视频时长 + 输出视频时长）
- 同档位所有宽高比像素面积相同 → **价格只取决于分辨率档位与时长，横竖屏同价**
- 官方价格锚点（16:9 / 5 秒，无输入视频，元/个）：

| 分辨率 | 标准版 | fast | mini |
|--------|--------|------|------|
| 480p | ¥2.31 | ¥1.86 | ¥1.16 |
| 720p | ¥4.97 | ¥4.00 | ¥2.50 |
| 1080p | ¥12.39 | 不支持 | 不支持 |

- 站内名义扣费约官网 1.1 倍（叠加充值加赠后基本持平官网）；提交时预扣费、完成后多退少补
- 参数错误（HTTP 400）**不扣费**
- 费用与时长线性相关（15 秒 ≈ 3 × 5 秒）

## 生成耗时（实测参考）

- mini：5 秒 720p 约 1.5–2.5 分钟；15 秒约 3 分钟（最快）
- fast：5 秒 720p 约 90–140 秒；15 秒约 170 秒
- 1080p 约 3 分钟+；分辨率越高、时长越长越慢
- 轮询建议：提交后 20–30 秒首查，之后每 10–20 秒一次；10–15 分钟未到终态视为异常

## 错误码

| 状态码 | 含义 | 处理 |
|--------|------|------|
| 400 | InvalidParameter（如 fast/mini + 1080p、非法 ratio/duration） | 按报错信息修正参数；不扣费 |
| 401 | 令牌无效 | 检查 Bearer Token |
| 403 | 内容审核拦截（真人面孔、违规内容） | 更换素材或调整提示词 |
| 429 | 限流 / 余额不足 | 指数退避重试；检查余额 |
| 5xx | 网关/后端错误 | 重试 1–2 次 |
| 任务 failed | 生成失败 | 查看任务 error 字段，必要时换 seed 重试 |
| 任务 expired | 超过 execution_expires_after 未完成 | 重新提交 |

## 提示词要点

- 中文 ≤500 字、英文 ≤1000 词；支持中、英、日、西、葡、印尼语
- 建议结构：「主体 + 动作 + 镜头运动 + 光线/风格」
- 需要角色说话时，台词放双引号内可优化配音效果，如：男人说："你记住，以后不可以用手指指月亮。"

## 最佳实践

1. 要 1080p 或最高画质 → 标准版；批量出片、成本敏感 → mini（约半价、最快）；折中 → fast
2. 图生视频保持默认 `adaptive` 比例，避免居中裁剪
3. 先用 5 秒小视频验证 prompt，满意后再上 10–15 秒
4. 不需要声音显式传 `generate_audio: false`
5. 成功后立即下载（直链 24 小时过期）
6. `return_last_frame: true` 拿尾帧作下一段首帧，拼接连续长视频
7. 记录 task_id 便于排查（7 天内可查）
