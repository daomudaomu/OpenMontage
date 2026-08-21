#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seedance 2.0 视频生成脚本（API易 / apiyi.com）

流程：创建异步任务 -> 轮询状态 -> 下载 mp4（并保存任务元数据 JSON）。
仅依赖 Python 标准库，无需 pip install。

认证：环境变量 APIYI_API_SEEDANCE_KEY（令牌须勾选 SeeDance2 分组，计费模式为按量优先/按量计费）。
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL_DEFAULT = "https://api.apiyi.com"
TASKS_PATH = "/seedance/api/v3/contents/generations/tasks"

# 模型别名 -> 完整模型 ID
MODEL_ALIASES = {
    "standard": "doubao-seedance-2-0-260128",
    "fast": "doubao-seedance-2-0-fast-260128",
    "mini": "doubao-seedance-2-0-mini-260615",
}
VALID_MODELS = set(MODEL_ALIASES.values())
VALID_RESOLUTIONS = ("480p", "720p", "1080p")
VALID_RATIOS = ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive")

IMG_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif",
    ".tiff": "image/tiff", ".tif": "image/tiff",
    ".heic": "image/heic", ".heif": "image/heif",
}


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def resolve_model(m: str) -> str:
    m = m.strip()
    if m in MODEL_ALIASES:
        return MODEL_ALIASES[m]
    if m in VALID_MODELS:
        return m
    raise ValueError(
        f"未知模型: {m}。可选: standard / fast / mini 或完整 ID "
        f"({', '.join(sorted(VALID_MODELS))})"
    )


def media_to_url(spec: str, kind: str) -> str:
    """把输入媒体规范转换为 API 可接受的 URL。

    - http(s):// / data: / asset:// 原样透传
    - 本地图片文件 -> base64 data URL
    - 本地视频/音频文件不支持（需公网 URL 或 asset:// 素材 ID）
    """
    spec = spec.strip()
    low = spec.lower()
    if low.startswith(("http://", "https://", "data:", "asset://")):
        return spec
    p = Path(spec)
    if not p.is_file():
        raise ValueError(f"输入文件不存在: {spec}（也可传公网 URL 或 asset:// 素材 ID）")
    if kind != "image":
        raise ValueError(
            f"本地{kind}文件不能直接上传: {spec}。请提供公网 URL，或先上传到 API易素材库后用 asset:// 素材 ID。"
        )
    mime = IMG_MIME.get(p.suffix.lower(), "image/png")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_body(args) -> dict:
    content = [{"type": "text", "text": args.prompt}]

    first = args.first_frame
    last = args.last_frame
    refs_img = args.reference_image or []
    refs_vid = args.reference_video or []
    refs_aud = args.reference_audio or []

    has_fl = bool(first or last)
    has_ref = bool(refs_img or refs_vid or refs_aud)
    if has_fl and has_ref:
        raise ValueError("首尾帧/首帧模式与多模态参考模式互斥，不能混用。")
    if last and not first:
        raise ValueError("不支持仅尾帧：请同时提供 --first-frame 与 --last-frame，或只用 --first-frame。")

    if has_fl:
        content.append({
            "type": "image_url",
            "image_url": {"url": media_to_url(first, "image")},
            "role": "first_frame",
        })
        if last:
            content.append({
                "type": "image_url",
                "image_url": {"url": media_to_url(last, "image")},
                "role": "last_frame",
            })
    elif has_ref:
        if len(refs_img) > 9:
            raise ValueError("参考图最多 9 张。")
        if len(refs_vid) > 3:
            raise ValueError("参考视频最多 3 段。")
        if len(refs_aud) > 3:
            raise ValueError("参考音频最多 3 段。")
        if not (refs_img or refs_vid):
            raise ValueError("多模态参考模式至少需要 1 张参考图或 1 段参考视频。")
        for s in refs_img:
            content.append({
                "type": "image_url",
                "image_url": {"url": media_to_url(s, "image")},
                "role": "reference_image",
            })
        for s in refs_vid:
            content.append({
                "type": "video_url",
                "video_url": {"url": media_to_url(s, "video")},
                "role": "reference_video",
            })
        for s in refs_aud:
            content.append({
                "type": "audio_url",
                "audio_url": {"url": media_to_url(s, "audio")},
                "role": "reference_audio",
            })

    model = resolve_model(args.model)
    if args.resolution == "1080p" and model != MODEL_ALIASES["standard"]:
        raise ValueError("1080p 仅标准版 doubao-seedance-2-0-260128 支持；fast/mini 最高 720p。")

    duration = int(args.duration)
    if duration != -1 and not (4 <= duration <= 15):
        raise ValueError("duration 须为 4-15 的整数秒，或 -1（模型智能选时长）。")

    body = {
        "model": model,
        "content": content,
        "resolution": args.resolution,
        "ratio": args.ratio,
        "duration": duration,
        "generate_audio": not args.no_audio,
        "watermark": args.watermark,
    }
    if args.seed is not None:
        body["seed"] = args.seed
    if args.return_last_frame:
        body["return_last_frame"] = True
    if args.execution_expires_after is not None:
        body["execution_expires_after"] = args.execution_expires_after
    return body


def http_json(req: urllib.request.Request, timeout: int) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(f"HTTP {e.code}: {raw}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"响应不是合法 JSON: {raw[:500]}") from None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Seedance 2.0 视频生成（API易）：创建任务 -> 轮询 -> 下载 mp4"
    )
    ap.add_argument("-p", "--prompt", required=True, help="视频描述提示词（中文≤500字/英文≤1000词）")
    ap.add_argument("-m", "--model", default="mini",
                    help="模型：standard / fast / mini 或完整 ID（默认 mini，最便宜最快）")
    ap.add_argument("-f", "--filename", help="输出 mp4 路径（默认 seedance2_<时间戳>.mp4）")
    ap.add_argument("--resolution", default="720p", choices=VALID_RESOLUTIONS,
                    help="分辨率：480p / 720p / 1080p（默认 720p；1080p 仅标准版）")
    ap.add_argument("--ratio", default="adaptive", choices=VALID_RATIOS,
                    help="宽高比：16:9/4:3/1:1/3:4/9:16/21:9/adaptive（默认 adaptive，同档位全比例同价）")
    ap.add_argument("--duration", default="5",
                    help="时长秒数：4-15 整数，或 -1 智能时长（默认 5；费用与时长线性相关）")
    ap.add_argument("--no-audio", action="store_true",
                    help="不生成同步音频（默认生成人声/音效/配乐）")
    ap.add_argument("--watermark", action="store_true", help="加「AI 生成」水印（默认不加）")
    ap.add_argument("--seed", type=int, help="随机种子 [-1, 2^32-1]，相同 seed 结果类似")
    ap.add_argument("--first-frame", help="首帧图片（本地路径/URL/asset://）")
    ap.add_argument("--last-frame", help="尾帧图片（本地路径/URL/asset://），需与 --first-frame 同用")
    ap.add_argument("--reference-image", action="append",
                    help="多模态参考图（可重复，最多 9 张；本地路径/URL/asset://）")
    ap.add_argument("--reference-video", action="append",
                    help="参考视频（可重复，最多 3 段，2-15 秒；URL 或 asset://）")
    ap.add_argument("--reference-audio", action="append",
                    help="参考音频（可重复，最多 3 段，2-15 秒 wav/mp3；URL 或 asset://，需搭配图或视频）")
    ap.add_argument("--return-last-frame", action="store_true",
                    help="同时返回尾帧 png（无水印），用于多段视频接力")
    ap.add_argument("--execution-expires-after", type=int,
                    help="任务过期阈值秒数 [3600, 259200]（默认 172800）")
    ap.add_argument("--poll-interval", type=int, default=20, help="轮询间隔秒数（默认 20）")
    ap.add_argument("--timeout", type=int, default=1200, help="整体等待上限秒数（默认 1200）")
    ap.add_argument("--base-url", default=os.environ.get("APIYI_BASE_URL", BASE_URL_DEFAULT),
                    help=f"API 域名（默认 {BASE_URL_DEFAULT}）")
    ap.add_argument("--api-key",
                    default=os.environ.get("APIYI_API_SEEDANCE_KEY", ""),
                    help="API Key（默认读环境变量 APIYI_API_SEEDANCE_KEY）")
    args = ap.parse_args()

    if not args.api_key:
        eprint("错误: 缺少 API Key。请设置环境变量 APIYI_API_SEEDANCE_KEY，或用 --api-key 传入。")
        return 1

    try:
        body = build_body(args)
    except ValueError as e:
        eprint(f"参数错误: {e}")
        return 1

    base = args.base_url.rstrip("/") + TASKS_PATH
    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Content-Type": "application/json",
        # 网关 gzip 头与实际编码不符，显式声明 identity 规避解码问题
        "Accept-Encoding": "identity",
    }

    # 1. 创建任务
    eprint(f"[1/3] 创建任务: model={body['model']} resolution={body['resolution']} "
           f"ratio={body['ratio']} duration={body['duration']} audio={body['generate_audio']}")
    req = urllib.request.Request(base, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        created = http_json(req, timeout=60)
    except RuntimeError as e:
        eprint(f"创建任务失败: {e}")
        return 1
    task_id = created.get("id")
    if not task_id:
        eprint(f"创建任务响应异常（无 id）: {created}")
        return 1
    eprint(f"task_id: {task_id}")

    out_path = Path(args.filename) if args.filename else Path(
        f"seedance2_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. 轮询直到终态
    eprint(f"[2/3] 轮询任务状态（每 {args.poll_interval}s，上限 {args.timeout}s）..."
           f"视频生成通常需要 1.5-5 分钟")
    deadline = time.time() + args.timeout
    last_status = None
    task = {}
    while time.time() < deadline:
        time.sleep(args.poll_interval)
        req = urllib.request.Request(f"{base}/{task_id}", headers=headers, method="GET")
        try:
            task = http_json(req, timeout=30)
        except RuntimeError as e:
            eprint(f"查询失败（将继续重试）: {e}")
            continue
        status = task.get("status")
        if status != last_status:
            eprint(f"status: {status}")
            last_status = status
        if status in ("succeeded", "failed", "expired"):
            break
    else:
        eprint(f"等待超时（{args.timeout}s），任务可能仍在进行。task_id={task_id}，"
               f"可稍后手动查询: GET {base}/{task_id}")
        return 1

    if last_status != "succeeded":
        eprint(f"任务未成功: status={last_status} error={task.get('error')}")
        return 1

    content = task.get("content") or {}
    video_url = content.get("video_url")
    if not video_url:
        eprint(f"任务成功但无 video_url: {task}")
        return 1
    usage = task.get("usage") or {}
    eprint(f"任务成功。tokens={usage.get('completion_tokens')} "
           f"实际参数: duration={task.get('duration')} ratio={task.get('ratio')} "
           f"resolution={task.get('resolution')} seed={task.get('seed')}")

    # 3. 下载视频（直链 24 小时过期；不要带 Authorization 头）
    eprint(f"[3/3] 下载视频 -> {out_path}")
    try:
        req = urllib.request.Request(video_url, headers={"Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(out_path, "wb") as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    except Exception as e:
        eprint(f"下载失败: {e}\n视频直链（24小时内有效，请尽快手动下载）: {video_url}")
        return 1

    # 保存任务元数据（含 seed/ratio/duration 实际值与 tokens，便于复现与对账）
    meta_path = out_path.with_suffix(out_path.suffix + ".json")
    meta_path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")

    # 尾帧（return_last_frame 时，content 下会有尾帧 url 字段）
    for k, v in content.items():
        if k != "video_url" and "frame" in k and isinstance(v, str) and v.startswith("http"):
            frame_path = out_path.with_name(out_path.stem + "_last_frame.png")
            try:
                req = urllib.request.Request(v, headers={"Accept-Encoding": "identity"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    frame_path.write_bytes(resp.read())
                eprint(f"尾帧已保存 -> {frame_path}")
            except Exception as e:
                eprint(f"尾帧下载失败: {e}（链接: {v}）")

    size_mb = out_path.stat().st_size / (1024 * 1024)
    # 最终结果打印到 stdout，便于调用方解析
    print(json.dumps({
        "ok": True,
        "video": str(out_path),
        "size_mb": round(size_mb, 2),
        "metadata": str(meta_path),
        "task_id": task_id,
        "video_url": video_url,
        "tokens": usage.get("completion_tokens"),
        "duration": task.get("duration"),
        "resolution": task.get("resolution"),
        "ratio": task.get("ratio"),
        "seed": task.get("seed"),
    }, ensure_ascii=False))
    eprint(f"完成: {out_path} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
