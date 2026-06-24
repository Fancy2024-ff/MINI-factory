// 真实用户链路测试（P0-1 收口）：
// 实际执行【生成项目内的 generation.ts】，证明：
//   - avatar / sticker / pet-talk 在 api 模式真实 API success 后，
//     previewData 带 image / image_base64（真实图可渲染），并能从 storage 取回；
//   - funny / blessing 永远不调真实 API，走 honest fallback / preview（capability_mode=fallback_preview）。
//
// 做法：用 page-builder 生成真实项目 -> 改写生成项目的 config/api.ts 为 api 模式 ->
// 用内存 uni stub 注入 globalThis -> 动态 import 生成项目里的 services/generation.ts。
import { describe, it, expect, beforeAll } from "vitest";
import os from "os";
import path from "path";
import fs from "fs-extra";
import { pathToFileURL } from "url";

const OUT = path.join(os.tmpdir(), "gen-real-" + process.pid);

let generateProject: (prd: any, template?: string) => Promise<any>;

beforeAll(async () => {
  process.env.GENERATOR_OUTPUT_DIR = OUT;
  await fs.emptyDir(OUT);
  ({ generateProject } = await import("../codegen/page-builder"));
});

// 每个模板用不同 app_name -> 不同项目目录，避免动态 import 缓存串台。
function prdFor(name: string) {
  return {
    app_name: name,
    summary: "real generation chain test",
    target_platforms: ["wechat"],
    core_features: [{ name: "生成", type: "input" }],
  };
}

// 把生成项目的 config/api.ts 改写成 api 模式 + https base（codegen 默认是 mock）。
async function forceApiMode(projectPath: string) {
  const apiPath = path.join(projectPath, "src/config/api.ts");
  const ts = [
    "export const API_BASE = 'https://api.example.com'",
    "export const GENERATION_MODE: 'mock' | 'api' = 'api'",
    "export const IMAGE_GENERATION_PATH = '/api/generation/image'",
    "export const TEMPLATE_GENERATION_PATH = '/api/generation/template'",
    "",
  ].join("\n");
  await fs.writeFile(apiPath, ts, "utf-8");
}

// 内存 uni stub：request 走注入的 handler；storage 用 Map（证明结果能存能取）。
function installUni(requestHandler: (opts: any) => any) {
  const store = new Map<string, any>();
  (globalThis as any).uni = {
    request: (opts: any) => {
      try {
        const data = requestHandler(opts);
        opts.success && opts.success({ data });
      } catch (e) {
        opts.fail && opts.fail(e);
      }
    },
    setStorageSync: (k: string, v: any) => store.set(k, v),
    getStorageSync: (k: string) => store.get(k),
    showToast: () => {},
    navigateTo: () => {},
    redirectTo: () => {},
    reLaunch: () => {},
  };
  return store;
}

// 动态 import 生成项目里的 generation.ts（按路径，模块级 blueprint 缓存随实例隔离）。
async function importGenerated(projectPath: string) {
  const svc = path.join(projectPath, "src/services/generation.ts");
  return import(pathToFileURL(svc).href);
}

const CORE_CASES = [
  { template: "avatar-viral", previewType: "avatar", title: "AI 头像已生成" },
  { template: "sticker-viral", previewType: "stickerPack", title: "表情包已生成" },
  { template: "pet-talk-viral", previewType: "petVideo", title: "宠物说话预览已生成" },
];

describe("real generation chain (core_runnable templates)", () => {
  for (const { template, previewType, title } of CORE_CASES) {
    it(`${template}: API success exposes a real image in previewData + storage`, async () => {
      const res = await generateProject(prdFor(`real-${template}`), template);
      await forceApiMode(res.project_path);

      const imageUrl = `https://cdn.example.com/${template}.png`;
      let calledUrl = "";
      installUni((opts) => {
        calledUrl = opts.url;
        // 后端真实返回：题材 preview_type + 真实图 url。
        return {
          ok: true,
          preview_type: previewType,
          ...(template === "pet-talk-viral" ? { video_supported: false } : {}),
          result: { image_url: imageUrl, title, prompt: "一只猫", caption: "cap" },
        };
      });

      const mod = await importGenerated(res.project_path);
      const out = await mod.mockGenerate({ text: "一只猫" });

      // 真实链路：调用了 template 接口（非 ai-image 走 /template）。
      expect(calledUrl).toContain("/api/generation/template");
      // 真实图片落在 previewData（前端通用真实图块据此渲染，不是只进 storage）。
      expect(out.previewData.image).toBe(imageUrl);
      expect(out.previewType).toBe(previewType);
      // 能力状态如实：真实生成成功，非降级。
      expect(out.realGeneration).toBe(true);
      expect(out.fallbackMode).toBe(false);
      expect(out.apiFailed).toBeFalsy();
      // 题材身份字段仍在（avatar.note / sticker.theme/stickers / petVideo.line）。
      if (previewType === "avatar") expect(out.previewData.note).toContain("一只猫");
      if (previewType === "stickerPack") expect(Array.isArray(out.previewData.stickers)).toBe(true);
      if (previewType === "petVideo") {
        expect(out.previewData.line).toBe("一只猫");
        expect(out.previewData.videoSupported).toBe(false); // 非动态视频，如实标注
      }
      // 存进 storage 后能取回，且取回的结果也带真实图（证明结果页 loadResult 可见）。
      const reloaded = mod.loadResult(out.id);
      expect(reloaded).toBeTruthy();
      expect(reloaded.previewData.image).toBe(imageUrl);
    });
  }
});

const HONEST_CASES = ["funny-video-viral", "blessing-video-viral"];

describe("honest preview chain (video boundary templates never call API)", () => {
  for (const template of HONEST_CASES) {
    it(`${template}: api mode still goes honest fallback, never calls the API`, async () => {
      const res = await generateProject(prdFor(`honest-${template}`), template);
      await forceApiMode(res.project_path);

      let apiCalled = false;
      installUni(() => {
        apiCalled = true; // 一旦被调用即视为违规
        return { ok: true, result: { image_url: "https://should-not-happen.png" } };
      });

      const mod = await importGenerated(res.project_path);
      const out = await mod.mockGenerate({ text: "打工人的一天" });

      // 关键证据：视频边界型模板在 api 模式下也绝不调用真实 API。
      expect(apiCalled).toBe(false);
      // 如实标记 honest preview / fallback，不伪装真实生成。
      expect(out.realGeneration).toBe(false);
      expect(out.fallbackMode).toBe(true);
      expect(out.capabilityMode).toBe("fallback_preview");
      // 口径一致（finding #2/#5）：growthLoop 对象也必须是 fallback_preview。
      expect(out.growthLoop).toBeTruthy();
      expect(out.growthLoop.capability_mode).toBe("fallback_preview");
      expect(out.previewData.honest_fallback).toBe(true);
      // 没有真实生成图。
      expect(out.previewData.image).toBeFalsy();
    });
  }
});

describe("large base64 honesty (no silent drop while claiming real generation)", () => {
  it("avatar: API returns only oversized base64 -> degrades to apiFailed, not fake real image", async () => {
    const res = await generateProject(prdFor("large-b64"), "avatar-viral");
    await forceApiMode(res.project_path);

    // 仅返回超大 base64（>700KB 编码上限）且无 image_url。
    const hugeBase64 = "A".repeat(800_000);
    installUni(() => ({
      ok: true,
      preview_type: "avatar",
      result: { image_base64: hugeBase64, title: "AI 头像已生成", prompt: "一只猫" },
    }));

    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "一只猫" });

    // 关键：不能静默丢图还标真实生成。必须显式降级。
    expect(out.realGeneration).toBe(false);
    expect(out.fallbackMode).toBe(true);
    expect(out.apiFailed).toBe(true);
    expect(out.capabilityMode).toBe("fallback_preview");
    expect(out.fallbackReason).toBeTruthy();
    // 结果里不得残留"可见真实图"的假象（既无 url 也无可渲染 base64）。
    expect(out.previewData.image).toBeFalsy();
    expect(out.previewData.image_base64).toBeFalsy();
    // 取回的结果同样是降级态，不是"真实图可见"。
    const reloaded = mod.loadResult(out.id);
    expect(reloaded.realGeneration).toBe(false);
    expect(reloaded.apiFailed).toBe(true);
  });

  it("avatar: API returns small base64 -> kept and marked real", async () => {
    const res = await generateProject(prdFor("small-b64"), "avatar-viral");
    await forceApiMode(res.project_path);

    const smallBase64 = "QUJD"; // tiny, well under limit
    installUni(() => ({
      ok: true,
      preview_type: "avatar",
      result: { image_base64: smallBase64, title: "AI 头像已生成", prompt: "猫" },
    }));

    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });

    // 体积可控的 base64 正常保留 + 真实生成（图片可渲染）。
    expect(out.previewData.image_base64).toBe(smallBase64);
    expect(out.realGeneration).toBe(true);
    expect(out.fallbackMode).toBe(false);
    expect(out.apiFailed).toBeFalsy();
    // finding #1（方案 B）：base64-only 无可保存 URL -> 导出能力如实降级，不留假承诺。
    expect(out.exportSupported).toBe(false);
    expect(out.downloadSupported).toBe(false);
    expect(out.growthLoop.export_supported).toBe(false);
    expect(out.growthLoop.download_supported).toBe(false);
    // 导出目标分类不是 remote_image（无 URL），文本兜底或 none，绝不是「假装可存相册」。
    const target = mod.classifyExportTarget(out);
    expect(target.kind).not.toBe("remote_image");
  });
});

// --- 行为级守护：growth_loop 真实驱动结果对象（P0-2 复核 finding #2 / #5 / #6） ---

describe("growth_loop behavior: share/unlock copy comes from growth_loop, not legacy mock_example", () => {
  it("avatar (mock mode): 文案来自 growth_loop，但能力/导出按当前运行模式降级 (finding #2)", async () => {
    const res = await generateProject(prdFor("gl-copy"), "avatar-viral");
    // 默认 mock 模式（不 forceApiMode）：核心模板走本地预览降级。
    installUni(() => ({ ok: true, result: {} }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "赛博朋克" });

    // growthLoop 对象存在。
    expect(out.growthLoop).toBeTruthy();
    // 文案优先来自 growth_loop（题材身份不丢）。
    expect(out.shareTitle).toBe(out.growthLoop.share_title);
    expect(out.shareCopy).toBe(out.growthLoop.share_copy);
    expect(out.unlockHint).toBe(out.growthLoop.unlock_hint);
    expect(out.shareTitle).toContain("头像");
    // finding #2：mock 运行模式下，能力/导出口径降级为 fallback_preview，不显示 real。
    expect(out.realGeneration).toBe(false);
    expect(out.fallbackMode).toBe(true);
    expect(out.capabilityMode).toBe("fallback_preview");
    expect(out.growthLoop.capability_mode).toBe("fallback_preview");
    expect(out.exportSupported).toBe(false);
    expect(out.downloadSupported).toBe(false);
    expect(out.growthLoop.export_supported).toBe(false);
    expect(out.previewData.local_preview).toBe(true);
    expect(out.previewData.mock_preview).toBe(true);
    expect(out.capabilityNote).toContain("本地预览");
  });
});

describe("growth_loop behavior: API-failure downgrade keeps flat + growthLoop consistent (finding #2)", () => {
  it("avatar: API throws -> capabilityMode AND growthLoop.capability_mode both fallback_preview, export downgraded", async () => {
    const res = await generateProject(prdFor("gl-apifail"), "avatar-viral");
    await forceApiMode(res.project_path);

    // 真实 API 调用直接抛错。
    installUni(() => {
      throw new Error("network down");
    });

    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });

    // 扁平字段：如实降级。
    expect(out.realGeneration).toBe(false);
    expect(out.fallbackMode).toBe(true);
    expect(out.apiFailed).toBe(true);
    expect(out.capabilityMode).toBe("fallback_preview");
    // 关键（finding #2）：growthLoop 对象口径必须与扁平字段一致，不能残留 real。
    expect(out.growthLoop.capability_mode).toBe("fallback_preview");
    // 导出/下载在降级后不得继续宣称真实高清导出。
    expect(out.exportSupported).toBe(false);
    expect(out.downloadSupported).toBe(false);
    expect(out.growthLoop.export_supported).toBe(false);
    expect(out.growthLoop.download_supported).toBe(false);
    // 没有真实图。
    expect(out.previewData.image).toBeFalsy();
  });
});

describe("unlockResult honors removeWatermarkSupported (finding #5/#6)", () => {
  it("removeWatermarkSupported=true (avatar): unlock removes watermark", async () => {
    const res = await generateProject(prdFor("gl-unlock-true"), "avatar-viral");
    installUni(() => ({ ok: true, result: {} }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });
    expect(out.watermarkEnabled).toBe(true);
    expect(out.removeWatermarkSupported).toBe(true);

    const unlocked = mod.unlockResult(out.id);
    expect(unlocked.watermarkEnabled).toBe(false);
    expect(unlocked.unlocked).toBe(true);
  });

  it("removeWatermarkSupported=false: unlock keeps watermark but marks unlocked", async () => {
    const res = await generateProject(prdFor("gl-unlock-false"), "avatar-viral");
    installUni(() => ({ ok: true, result: {} }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });

    // 直接改 storage 里的结果，模拟「事实源不支持去水印」的模板。
    out.removeWatermarkSupported = false;
    mod.saveResult(out);

    const unlocked = mod.unlockResult(out.id);
    // 不假装去水印：watermarkEnabled 保持 true，但 unlocked=true。
    expect(unlocked.watermarkEnabled).toBe(true);
    expect(unlocked.unlocked).toBe(true);
  });
});

describe("has_watermark=false drives watermarkEnabled=false (finding #6)", () => {
  it("avatar with has_watermark=false in blueprint: watermarkEnabled=false", async () => {
    const res = await generateProject(prdFor("gl-no-wm"), "avatar-viral");
    // 篡改生成项目的 blueprint.json：has_watermark=false。
    const bpPath = path.join(res.project_path, "src/config/blueprint.json");
    const bp = await fs.readJson(bpPath);
    bp.growth_loop.has_watermark = false;
    await fs.writeJson(bpPath, bp);

    installUni(() => ({ ok: true, result: {} }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });

    // 事实源 has_watermark=false -> 初始 watermarkEnabled=false（不再硬编码 true）。
    expect(out.hasWatermark).toBe(false);
    expect(out.watermarkEnabled).toBe(false);
  });
});

// --- finding #2：mock runtime 下核心模板不得显示 real / 高清导出 ---

describe("mock runtime: core templates degrade to local preview, not fake real (finding #2)", () => {
  for (const { template } of CORE_CASES) {
    it(`${template}: mock mode -> fallback_preview + export off + local_preview`, async () => {
      const res = await generateProject(prdFor(`mock-local-${template}`), template);
      // 不 forceApiMode：默认 mock 运行模式。
      installUni(() => ({ ok: true, result: {} }));
      const mod = await importGenerated(res.project_path);
      const out = await mod.mockGenerate({ text: "测试" });

      // 当前运行结果并非真实生成：不得显示 real。
      expect(out.realGeneration).toBe(false);
      expect(out.fallbackMode).toBe(true);
      expect(out.capabilityMode).toBe("fallback_preview");
      expect(out.growthLoop.capability_mode).toBe("fallback_preview");
      // 高清导出/下载关闭。
      expect(out.exportSupported).toBe(false);
      expect(out.downloadSupported).toBe(false);
      expect(out.growthLoop.export_supported).toBe(false);
      expect(out.growthLoop.download_supported).toBe(false);
      // 标记本地预览 + 诚实文案。
      expect(out.previewData.local_preview).toBe(true);
      expect(out.previewData.mock_preview).toBe(true);
      expect(out.capabilityNote).toContain("本地预览");
      // 没有伪造的真实图。
      expect(out.previewData.image).toBeFalsy();
    });
  }
});

// --- finding #3：导出能力行为级判定（classifyExportTarget 纯函数）---

describe("classifyExportTarget: exportSupported=true must have a real export path (finding #3)", () => {
  it("remote image URL -> kind=remote_image (downloadFile + saveImageToPhotosAlbum path)", async () => {
    const res = await generateProject(prdFor("cls-remote"), "avatar-viral");
    await forceApiMode(res.project_path);
    const imageUrl = "https://cdn.example.com/avatar.png";
    installUni(() => ({
      ok: true,
      preview_type: "avatar",
      result: { image_url: imageUrl, title: "AI 头像已生成", prompt: "猫" },
    }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });

    // 真实远程图：exportSupported=true 且导出目标可执行（remote_image）。
    expect(out.exportSupported).toBe(true);
    const target = mod.classifyExportTarget(out);
    expect(target.kind).toBe("remote_image");
    expect(target.image).toBe(imageUrl);
  });

  it("base64-only -> exportSupported=false AND classify never remote_image (no fake export)", async () => {
    const res = await generateProject(prdFor("cls-b64"), "avatar-viral");
    await forceApiMode(res.project_path);
    installUni(() => ({
      ok: true,
      preview_type: "avatar",
      result: { image_base64: "QUJD", title: "AI 头像已生成", prompt: "猫" },
    }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });

    // 关键（finding #1/#3）：exportSupported=false，且不会被分类成可存相册。
    expect(out.exportSupported).toBe(false);
    expect(mod.classifyExportTarget(out).kind).not.toBe("remote_image");
  });

  for (const template of HONEST_CASES) {
    it(`${template}: text preview -> kind=text, copy content has script/card text`, async () => {
      const res = await generateProject(prdFor(`cls-text-${template}`), template);
      installUni(() => ({ ok: true, result: {} }));
      const mod = await importGenerated(res.project_path);
      const out = await mod.mockGenerate({ text: "打工人的一天" });

      // 文本型可导出：exportSupported=true（事实源），分类为 text 且复制内容非空。
      expect(out.exportSupported).toBe(true);
      const target = mod.classifyExportTarget(out);
      expect(target.kind).toBe("text");
      expect(typeof target.text).toBe("string");
      expect(target.text!.length).toBeGreaterThan(0);
      // 复制内容应包含脚本/祝福卡关键文本（用户输入或题材字段）。
      if (template === "funny-video-viral") {
        expect(target.text).toContain("打工人的一天");
      } else {
        // 祝福卡：含收礼人/祝福语等卡片字段。
        expect(target.text!.length).toBeGreaterThan(2);
      }
    });
  }

  it("classifyExportTarget(no content) -> kind=none", async () => {
    const res = await generateProject(prdFor("cls-none"), "avatar-viral");
    installUni(() => ({ ok: true, result: {} }));
    const mod = await importGenerated(res.project_path);
    // 构造一个无任何可导出内容的结果对象。
    const empty = { previewType: "avatar", previewData: {}, title: "", shareCopy: "" };
    expect(mod.classifyExportTarget(empty).kind).toBe("none");
  });
});

