#!/usr/bin/env node
/**
 * Seedance 2.0 视频生成脚本（API易 / apiyi.com）
 *
 * 流程：创建异步任务 -> 轮询状态 -> 下载 mp4（并保存任务元数据 JSON）。
 * 零第三方依赖（Node >= 18，使用内置 fetch / util.parseArgs）。
 *
 * 认证：环境变量 APIYI_API_SEEDANCE_KEY（令牌须勾选 SeeDance2 分组，计费模式为按量优先/按量计费）。
 */

import { parseArgs } from "node:util";
import { readFileSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { resolve, extname, dirname } from "node:path";

const BASE_URL_DEFAULT = "https://api.apiyi.com";
const TASKS_PATH = "/seedance/api/v3/contents/generations/tasks";

const MODEL_ALIASES = {
  standard: "doubao-seedance-2-0-260128",
  fast: "doubao-seedance-2-0-fast-260128",
  mini: "doubao-seedance-2-0-mini-260615",
};
const VALID_MODELS = new Set(Object.values(MODEL_ALIASES));
const VALID_RESOLUTIONS = ["480p", "720p", "1080p"];
const VALID_RATIOS = ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"];
const IMG_MIME = {
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
  ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif",
  ".tiff": "image/tiff", ".tif": "image/tiff",
  ".heic": "image/heic", ".heif": "image/heif",
};

const eprint = (...a) => console.error(...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function resolveModel(m) {
  m = (m || "").trim();
  if (MODEL_ALIASES[m]) return MODEL_ALIASES[m];
  if (VALID_MODELS.has(m)) return m;
  throw new Error(
    `未知模型: ${m}。可选: standard / fast / mini 或完整 ID (${[...VALID_MODELS].join(", ")})`
  );
}

function mediaToUrl(spec, kind) {
  spec = spec.trim();
  const low = spec.toLowerCase();
  if (/^(https?:\/\/|data:|asset:\/\/)/.test(low)) return spec;
  let buf;
  try {
    buf = readFileSync(spec);
  } catch {
    throw new Error(`输入文件不存在: ${spec}（也可传公网 URL 或 asset:// 素材 ID）`);
  }
  if (kind !== "image") {
    throw new Error(
      `本地${kind}文件不能直接上传: ${spec}。请提供公网 URL，或先上传到 API易素材库后用 asset:// 素材 ID。`
    );
  }
  const mime = IMG_MIME[extname(spec).toLowerCase()] || "image/png";
  return `data:${mime};base64,${buf.toString("base64")}`;
}

function buildBody(v) {
  const content = [{ type: "text", text: v.prompt }];
  const first = v["first-frame"];
  const last = v["last-frame"];
  const refsImg = v["reference-image"] || [];
  const refsVid = v["reference-video"] || [];
  const refsAud = v["reference-audio"] || [];

  const hasFL = Boolean(first || last);
  const hasRef = refsImg.length || refsVid.length || refsAud.length;
  if (hasFL && hasRef) throw new Error("首尾帧/首帧模式与多模态参考模式互斥，不能混用。");
  if (last && !first)
    throw new Error("不支持仅尾帧：请同时提供 --first-frame 与 --last-frame，或只用 --first-frame。");

  if (hasFL) {
    content.push({
      type: "image_url",
      image_url: { url: mediaToUrl(first, "image") },
      role: "first_frame",
    });
    if (last)
      content.push({
        type: "image_url",
        image_url: { url: mediaToUrl(last, "image") },
        role: "last_frame",
      });
  } else if (hasRef) {
    if (refsImg.length > 9) throw new Error("参考图最多 9 张。");
    if (refsVid.length > 3) throw new Error("参考视频最多 3 段。");
    if (refsAud.length > 3) throw new Error("参考音频最多 3 段。");
    if (!(refsImg.length || refsVid.length))
      throw new Error("多模态参考模式至少需要 1 张参考图或 1 段参考视频。");
    for (const s of refsImg)
      content.push({
        type: "image_url",
        image_url: { url: mediaToUrl(s, "image") },
        role: "reference_image",
      });
    for (const s of refsVid)
      content.push({
        type: "video_url",
        video_url: { url: mediaToUrl(s, "video") },
        role: "reference_video",
      });
    for (const s of refsAud)
      content.push({
        type: "audio_url",
        audio_url: { url: mediaToUrl(s, "audio") },
        role: "reference_audio",
      });
  }

  const model = resolveModel(v.model);
  const resolution = v.resolution || "720p";
  const ratio = v.ratio || "adaptive";
  if (!VALID_RESOLUTIONS.includes(resolution))
    throw new Error(`resolution 须为 ${VALID_RESOLUTIONS.join("/")}`);
  if (!VALID_RATIOS.includes(ratio))
    throw new Error(`ratio 须为 ${VALID_RATIOS.join("/")}`);
  if (resolution === "1080p" && model !== MODEL_ALIASES.standard)
    throw new Error("1080p 仅标准版 doubao-seedance-2-0-260128 支持；fast/mini 最高 720p。");

  const duration = parseInt(v.duration ?? "5", 10);
  if (Number.isNaN(duration) || (duration !== -1 && (duration < 4 || duration > 15)))
    throw new Error("duration 须为 4-15 的整数秒，或 -1（模型智能选时长）。");

  const body = {
    model,
    content,
    resolution,
    ratio,
    duration,
    generate_audio: !v["no-audio"],
    watermark: Boolean(v.watermark),
  };
  if (v.seed !== undefined) body.seed = parseInt(v.seed, 10);
  if (v["return-last-frame"]) body.return_last_frame = true;
  if (v["execution-expires-after"] !== undefined)
    body.execution_expires_after = parseInt(v["execution-expires-after"], 10);
  return body;
}

async function httpJson(url, options, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { ...options, signal: ctrl.signal });
    const raw = await resp.text();
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${raw}`);
    try {
      return JSON.parse(raw);
    } catch {
      throw new Error(`响应不是合法 JSON: ${raw.slice(0, 500)}`);
    }
  } finally {
    clearTimeout(t);
  }
}

async function download(url, outPath, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    // 视频直链下载不要带 Authorization 头
    const resp = await fetch(url, {
      headers: { "Accept-Encoding": "identity" },
      signal: ctrl.signal,
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const buf = Buffer.from(await resp.arrayBuffer());
    writeFileSync(outPath, buf);
  } finally {
    clearTimeout(t);
  }
}

async function main() {
  const { values: v } = parseArgs({
    options: {
      prompt: { type: "string", short: "p" },
      model: { type: "string", short: "m", default: "mini" },
      filename: { type: "string", short: "f" },
      resolution: { type: "string", default: "720p" },
      ratio: { type: "string", default: "adaptive" },
      duration: { type: "string", default: "5" },
      "no-audio": { type: "boolean", default: false },
      watermark: { type: "boolean", default: false },
      seed: { type: "string" },
      "first-frame": { type: "string" },
      "last-frame": { type: "string" },
      "reference-image": { type: "string", multiple: true },
      "reference-video": { type: "string", multiple: true },
      "reference-audio": { type: "string", multiple: true },
      "return-last-frame": { type: "boolean", default: false },
      "execution-expires-after": { type: "string" },
      "poll-interval": { type: "string", default: "20" },
      timeout: { type: "string", default: "1200" },
      "base-url": { type: "string", default: process.env.APIYI_BASE_URL || BASE_URL_DEFAULT },
      "api-key": { type: "string", default: process.env.APIYI_API_SEEDANCE_KEY || "" },
      help: { type: "boolean", short: "h", default: false },
    },
  });

  if (v.help || !v.prompt) {
    eprint(`用法: node generate_video.js -p "提示词" [选项]
  -p, --prompt          视频描述提示词（必填）
  -m, --model           standard / fast / mini 或完整 ID（默认 mini，最便宜最快）
  -f, --filename        输出 mp4 路径（默认 seedance2_<时间戳>.mp4）
  --resolution          480p / 720p / 1080p（默认 720p；1080p 仅标准版）
  --ratio               16:9/4:3/1:1/3:4/9:16/21:9/adaptive（默认 adaptive，全比例同价）
  --duration            4-15 整数秒，或 -1 智能时长（默认 5；费用与时长线性相关）
  --no-audio            不生成同步音频（默认生成）
  --watermark           加「AI 生成」水印（默认不加）
  --seed N              随机种子
  --first-frame IMG     首帧图片（本地路径/URL/asset://）
  --last-frame IMG      尾帧图片（需与 --first-frame 同用）
  --reference-image IMG 参考图（可重复，最多 9 张）
  --reference-video URL 参考视频（可重复，最多 3 段）
  --reference-audio URL 参考音频（可重复，最多 3 段，需搭配图或视频）
  --return-last-frame   同时返回尾帧 png（用于多段接力）
  --poll-interval N     轮询间隔秒数（默认 20）
  --timeout N           整体等待上限秒数（默认 1200）
  --api-key KEY         默认读环境变量 APIYI_API_SEEDANCE_KEY`);
    return v.help ? 0 : 1;
  }
  if (!v["api-key"]) {
    eprint("错误: 缺少 API Key。请设置环境变量 APIYI_API_SEEDANCE_KEY，或用 --api-key 传入。");
    return 1;
  }

  let body;
  try {
    body = buildBody(v);
  } catch (e) {
    eprint(`参数错误: ${e.message}`);
    return 1;
  }

  const base = v["base-url"].replace(/\/+$/, "") + TASKS_PATH;
  const headers = {
    Authorization: `Bearer ${v["api-key"]}`,
    "Content-Type": "application/json",
    "Accept-Encoding": "identity",
  };
  const pollInterval = parseInt(v["poll-interval"], 10) || 20;
  const timeoutSec = parseInt(v.timeout, 10) || 1200;

  // 1. 创建任务
  eprint(
    `[1/3] 创建任务: model=${body.model} resolution=${body.resolution} ` +
      `ratio=${body.ratio} duration=${body.duration} audio=${body.generate_audio}`
  );
  let created;
  try {
    created = await httpJson(
      base,
      { method: "POST", headers, body: JSON.stringify(body) },
      60000
    );
  } catch (e) {
    eprint(`创建任务失败: ${e.message}`);
    return 1;
  }
  const taskId = created.id;
  if (!taskId) {
    eprint(`创建任务响应异常（无 id）: ${JSON.stringify(created)}`);
    return 1;
  }
  eprint(`task_id: ${taskId}`);

  const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
  const outPath = resolve(v.filename || `seedance2_${ts}.mp4`);
  mkdirSync(dirname(outPath), { recursive: true });

  // 2. 轮询直到终态
  eprint(`[2/3] 轮询任务状态（每 ${pollInterval}s，上限 ${timeoutSec}s）... 视频生成通常需要 1.5-5 分钟`);
  const deadline = Date.now() + timeoutSec * 1000;
  let lastStatus = null;
  let task = {};
  while (Date.now() < deadline) {
    await sleep(pollInterval * 1000);
    try {
      task = await httpJson(`${base}/${taskId}`, { headers }, 30000);
    } catch (e) {
      eprint(`查询失败（将继续重试）: ${e.message}`);
      continue;
    }
    if (task.status !== lastStatus) {
      eprint(`status: ${task.status}`);
      lastStatus = task.status;
    }
    if (["succeeded", "failed", "expired"].includes(task.status)) break;
  }
  if (lastStatus !== "succeeded") {
    if (Date.now() >= deadline && !["failed", "expired"].includes(lastStatus)) {
      eprint(`等待超时（${timeoutSec}s），任务可能仍在进行。task_id=${taskId}，可稍后手动查询: GET ${base}/${taskId}`);
    } else {
      eprint(`任务未成功: status=${lastStatus} error=${JSON.stringify(task.error)}`);
    }
    return 1;
  }

  const content = task.content || {};
  const videoUrl = content.video_url;
  if (!videoUrl) {
    eprint(`任务成功但无 video_url: ${JSON.stringify(task)}`);
    return 1;
  }
  eprint(
    `任务成功。tokens=${task.usage?.completion_tokens} 实际参数: duration=${task.duration} ` +
      `ratio=${task.ratio} resolution=${task.resolution} seed=${task.seed}`
  );

  // 3. 下载视频（直链 24 小时过期）
  eprint(`[3/3] 下载视频 -> ${outPath}`);
  try {
    await download(videoUrl, outPath, 300000);
  } catch (e) {
    eprint(`下载失败: ${e.message}\n视频直链（24小时内有效，请尽快手动下载）: ${videoUrl}`);
    return 1;
  }

  // 保存任务元数据
  const metaPath = outPath + ".json";
  writeFileSync(metaPath, JSON.stringify(task, null, 2));

  // 尾帧
  for (const [k, val] of Object.entries(content)) {
    if (k !== "video_url" && k.includes("frame") && typeof val === "string" && val.startsWith("http")) {
      const framePath = outPath.replace(/\.mp4$/i, "") + "_last_frame.png";
      try {
        await download(val, framePath, 120000);
        eprint(`尾帧已保存 -> ${framePath}`);
      } catch (e) {
        eprint(`尾帧下载失败: ${e.message}（链接: ${val}）`);
      }
    }
  }

  const sizeMb = statSync(outPath).size / (1024 * 1024);
  console.log(
    JSON.stringify({
      ok: true,
      video: outPath,
      size_mb: Math.round(sizeMb * 100) / 100,
      metadata: metaPath,
      task_id: taskId,
      video_url: videoUrl,
      tokens: task.usage?.completion_tokens,
      duration: task.duration,
      resolution: task.resolution,
      ratio: task.ratio,
      seed: task.seed,
    })
  );
  eprint(`完成: ${outPath} (${sizeMb.toFixed(1)} MB)`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
