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

// 把生成项目的 config/ads.ts 改写成「已配置广告位」（codegen 默认空 id + disabled）。
async function forceAdEnabled(projectPath: string, adUnitId = "adunit-test-0001") {
  const adsPath = path.join(projectPath, "src/config/ads.ts");
  const ts = [
    `export const REWARDED_AD_UNIT_ID = '${adUnitId}'`,
    "export const REWARDED_AD_ENABLED: boolean = true",
    "",
  ].join("\n");
  await fs.writeFile(adsPath, ts, "utf-8");
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
    removeStorageSync: (k: string) => store.delete(k),
    showToast: () => {},
    showLoading: () => {},
    hideLoading: () => {},
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

// --- P0-1 最终硬化：结构化字段进入 callRealApi payload（form -> extra -> 后端 input） ---

describe("structured fields enter callRealApi payload (sticker mood / pet line / avatar style)", () => {
  // 捕获真实请求体，断言 data.input 携带结构化字段（form 把它们放进 extra）。
  function captureRequest(template: string, previewType: string) {
    let captured: any = null;
    installUni((opts) => {
      captured = opts;
      return {
        ok: true,
        preview_type: previewType,
        ...(template === "pet-talk-viral" ? { video_supported: false } : {}),
        result: { image_url: `https://cdn.example.com/${template}.png`, title: "ok", prompt: "p" },
      };
    });
    return () => captured;
  }

  it("sticker-viral: mood 进入 /template payload 的 input.mood", async () => {
    const res = await generateProject(prdFor("payload-sticker"), "sticker-viral");
    await forceApiMode(res.project_path);
    const get = captureRequest("sticker-viral", "stickerPack");
    const mod = await importGenerated(res.project_path);
    // form 主输入(theme)->text；mood(select)->extra.mood。
    await mod.mockGenerate({ text: "打工人", extra: { mood: "搞笑" } });
    const req = get();
    expect(req.url).toContain("/api/generation/template");
    expect(req.data.template_id).toBe("sticker-viral");
    expect(req.data.input.prompt).toBe("打工人");
    expect(req.data.input.mood).toBe("搞笑");
  });

  it("pet-talk-viral: line(主输入) 进入 /template payload 的 input.prompt", async () => {
    const res = await generateProject(prdFor("payload-pet"), "pet-talk-viral");
    await forceApiMode(res.project_path);
    const get = captureRequest("pet-talk-viral", "petVideo");
    const mod = await importGenerated(res.project_path);
    // pet-talk 主输入是 line(textarea)->text->prompt。
    await mod.mockGenerate({ text: "主人，该喂饭啦！", extra: {} });
    const req = get();
    expect(req.url).toContain("/api/generation/template");
    expect(req.data.template_id).toBe("pet-talk-viral");
    expect(req.data.input.prompt).toBe("主人，该喂饭啦！");
  });

  it("avatar-viral: style 进入 /template payload 的 input.style", async () => {
    const res = await generateProject(prdFor("payload-avatar"), "avatar-viral");
    await forceApiMode(res.project_path);
    const get = captureRequest("avatar-viral", "avatar");
    const mod = await importGenerated(res.project_path);
    // avatar：主输入(style 文本)->text->prompt；若另有 style 进 extra 也透传。
    await mod.mockGenerate({ text: "赛博朋克", extra: { style: "cyberpunk" } });
    const req = get();
    expect(req.url).toContain("/api/generation/template");
    expect(req.data.template_id).toBe("avatar-viral");
    expect(req.data.input.prompt).toBe("赛博朋克");
    expect(req.data.input.style).toBe("cyberpunk");
  });
});

// --- P0-1 最终硬化：ai-image runtime 行为（/image 路径 + 成功/失败/large-base64） ---

describe("ai-image runtime behavior", () => {
  async function setupAiImage(name: string) {
    // ai-image 不是 viral 模板，page-builder 会按其 template.json 生成 blueprint。
    const res = await generateProject(prdFor(name), "ai-image");
    await forceApiMode(res.project_path);
    return res;
  }

  it("api mode -> calls /api/generation/image (NOT /template)", async () => {
    const res = await setupAiImage("aiimg-path");
    let url = "";
    installUni((opts) => {
      url = opts.url;
      return { ok: true, preview_type: "image", result: { image_url: "https://cdn.example.com/x.png", prompt: "p" } };
    });
    const mod = await importGenerated(res.project_path);
    await mod.mockGenerate({ text: "夕阳海边小屋" });
    expect(url).toContain("/api/generation/image");
    expect(url).not.toContain("/api/generation/template");
  });

  it("success with image_url -> realGeneration=true / fallbackMode=false", async () => {
    const res = await setupAiImage("aiimg-success");
    const imageUrl = "https://cdn.example.com/aiimg.png";
    installUni(() => ({ ok: true, preview_type: "image", result: { image_url: imageUrl, prompt: "p" } }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "夕阳海边小屋" });
    expect(out.realGeneration).toBe(true);
    expect(out.fallbackMode).toBe(false);
    expect(out.apiFailed).toBeFalsy();
    expect(out.previewData.image).toBe(imageUrl);
    expect(out.capabilityMode).toBe("real");
  });

  it("only oversized base64 (no URL) -> apiFailed + fallback_preview", async () => {
    const res = await setupAiImage("aiimg-largeb64");
    installUni(() => ({
      ok: true, preview_type: "image",
      result: { image_base64: "A".repeat(800_000), prompt: "p" },
    }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "夕阳海边小屋" });
    expect(out.realGeneration).toBe(false);
    expect(out.fallbackMode).toBe(true);
    expect(out.apiFailed).toBe(true);
    expect(out.capabilityMode).toBe("fallback_preview");
    expect(out.previewData.image).toBeFalsy();
    expect(out.previewData.image_base64).toBeFalsy();
  });

  it("small base64 -> kept + realGeneration=true (export downgraded, no fake save)", async () => {
    const res = await setupAiImage("aiimg-smallb64");
    installUni(() => ({ ok: true, preview_type: "image", result: { image_base64: "QUJD", prompt: "p" } }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "夕阳海边小屋" });
    expect(out.previewData.image_base64).toBe("QUJD");
    expect(out.realGeneration).toBe(true);
    expect(out.fallbackMode).toBe(false);
    // base64-only 无 URL：导出能力如实降级。
    expect(out.exportSupported).toBe(false);
    expect(mod.classifyExportTarget(out).kind).not.toBe("remote_image");
  });

  it("API failure -> growthLoop capability/export/download all downgraded", async () => {
    const res = await setupAiImage("aiimg-fail");
    installUni(() => { throw new Error("provider down"); });
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "夕阳海边小屋" });
    expect(out.realGeneration).toBe(false);
    expect(out.fallbackMode).toBe(true);
    expect(out.apiFailed).toBe(true);
    expect(out.capabilityMode).toBe("fallback_preview");
    expect(out.growthLoop.capability_mode).toBe("fallback_preview");
    expect(out.exportSupported).toBe(false);
    expect(out.downloadSupported).toBe(false);
    expect(out.growthLoop.export_supported).toBe(false);
    expect(out.growthLoop.download_supported).toBe(false);
  });
});



// --- P0-1 最终硬化：form 输入归一纯函数 buildGenerateInput（直接单测）---

describe("buildGenerateInput (form input normalization, pure function)", () => {
  let buildGenerateInput: any;
  beforeAll(async () => {
    // 任一生成项目的 generation.ts 都导出同一纯函数；用 avatar 项目导入。
    const res = await generateProject(prdFor("bgi-fn"), "avatar-viral");
    const mod = await importGenerated(res.project_path);
    buildGenerateInput = mod.buildGenerateInput;
  });

  it("avatar: style(主字段) 同时进入 text 和 extra.style", () => {
    const fields = [
      { id: "photo", type: "image", required: false, drives_generation: false },
      { id: "style", type: "text", required: false },
    ];
    const out = buildGenerateInput(fields, { style: "赛博朋克" }, {}, {});
    expect(out.valid).toBe(true);
    expect(out.text).toBe("赛博朋克");
    // 关键（修复点）：primary 字段也写入 extra，主字段语义不丢。
    expect(out.extra.style).toBe("赛博朋克");
    // 占位图未选：assetPlaceholder 为空。
    expect(out.assetPlaceholder).toBe("");
  });

  it("sticker: theme(主) + mood(select) -> text + extra.theme + extra.mood", () => {
    const fields = [
      { id: "theme", type: "text", required: true },
      { id: "mood", type: "select", required: false, options: ["搞笑", "可爱"] },
    ];
    const out = buildGenerateInput(fields, { theme: "打工人" }, { mood: "搞笑" }, {});
    expect(out.valid).toBe(true);
    expect(out.text).toBe("打工人");
    expect(out.extra.theme).toBe("打工人");
    expect(out.extra.mood).toBe("搞笑");
  });

  it("pet-talk: line(主) -> text + extra.line", () => {
    const fields = [
      { id: "pet_photo", type: "image", required: false, drives_generation: false },
      { id: "line", type: "textarea", required: true },
    ];
    const out = buildGenerateInput(fields, { line: "主人，该喂饭啦！" }, {}, {});
    expect(out.valid).toBe(true);
    expect(out.text).toBe("主人，该喂饭啦！");
    expect(out.extra.line).toBe("主人，该喂饭啦！");
  });

  it("only placeholder image picked -> invalid (占位图不参与 valid，不调用生成)", () => {
    const fields = [
      { id: "photo", type: "image", required: false, drives_generation: false },
      { id: "style", type: "text", required: false },
    ];
    // 只点了占位图，没填任何文本/选择。
    const out = buildGenerateInput(fields, {}, {}, { photo: true });
    expect(out.valid).toBe(false);            // 不满足提交条件
    expect(out.text).toBe("");
    expect(Object.keys(out.extra).length).toBe(0);
    // assetPlaceholder 可作为辅助标记存在，但不影响 valid。
    expect(out.assetPlaceholder).toBe("素材占位（不参与生成）");
  });

  it("placeholder image NOT marked (chooseImage cancel) -> no assetPlaceholder", () => {
    const fields = [
      { id: "photo", type: "image", required: false, drives_generation: false },
      { id: "style", type: "text", required: false },
    ];
    // assetPicked 为空（模拟 chooseImage 被取消，success 未触发）。
    const out = buildGenerateInput(fields, { style: "日系" }, {}, {});
    expect(out.assetPlaceholder).toBe("");    // 取消选择不标记已选
    expect(out.valid).toBe(true);             // 但文本输入仍使其有效
    expect(out.extra.style).toBe("日系");
  });

  it("valid requires real input: placeholder asset alone never makes it valid", () => {
    const fields = [{ id: "photo", type: "image", required: false, drives_generation: false }];
    const out = buildGenerateInput(fields, {}, {}, { photo: true });
    expect(out.valid).toBe(false);            // 纯占位图字段：永远 invalid
  });

  // --- required 校验（P0-1 收口）---

  it("sticker: only mood (required theme missing) -> invalid + missingRequired=['theme']", () => {
    const fields = [
      { id: "theme", type: "text", required: true },
      { id: "mood", type: "select", required: false, options: ["搞笑", "可爱"] },
    ];
    const out = buildGenerateInput(fields, {}, { mood: "搞笑" }, {});
    expect(out.valid).toBe(false);
    expect(out.missingRequired).toEqual(["theme"]);
  });

  it("sticker: theme + mood -> valid + extra.theme + extra.mood + no missing", () => {
    const fields = [
      { id: "theme", type: "text", required: true },
      { id: "mood", type: "select", required: false, options: ["搞笑", "可爱"] },
    ];
    const out = buildGenerateInput(fields, { theme: "打工人" }, { mood: "搞笑" }, {});
    expect(out.valid).toBe(true);
    expect(out.missingRequired).toEqual([]);
    expect(out.text).toBe("打工人");
    expect(out.extra.theme).toBe("打工人");
    expect(out.extra.mood).toBe("搞笑");
  });

  it("pet-talk: required line missing -> invalid + missingRequired=['line']", () => {
    const fields = [
      { id: "pet_photo", type: "image", required: false, drives_generation: false },
      { id: "line", type: "textarea", required: true },
    ];
    const out = buildGenerateInput(fields, {}, {}, {});
    expect(out.valid).toBe(false);
    expect(out.missingRequired).toEqual(["line"]);
  });

  it("ai-image: required prompt missing -> invalid + missingRequired=['prompt']", () => {
    const fields = [
      { id: "prompt", type: "textarea", required: true },
      { id: "source_image", type: "image", required: false, drives_generation: false },
    ];
    const out = buildGenerateInput(fields, {}, {}, {});
    expect(out.valid).toBe(false);
    expect(out.missingRequired).toEqual(["prompt"]);
  });

  it("avatar: style optional but present -> valid; only placeholder photo -> invalid", () => {
    const fields = [
      { id: "photo", type: "image", required: false, drives_generation: false },
      { id: "style", type: "text", required: false },
    ];
    // style 非 required，填了就有效。
    const present = buildGenerateInput(fields, { style: "赛博朋克" }, {}, {});
    expect(present.valid).toBe(true);
    expect(present.missingRequired).toEqual([]);
    expect(present.extra.style).toBe("赛博朋克");
    // 只点占位图、没填 style -> 无 required 字段但也无真实输入 -> invalid。
    const onlyPhoto = buildGenerateInput(fields, {}, {}, { photo: true });
    expect(onlyPhoto.valid).toBe(false);
    expect(onlyPhoto.missingRequired).toEqual([]); // 无 required 字段，靠"无真实输入"判 invalid
  });

  it("required image field is NOT counted in missingRequired (image never required input)", () => {
    // 即便 image 被错标 required，也不应进入 missingRequired（image 无真实上传链）。
    const fields = [
      { id: "photo", type: "image", required: true, drives_generation: false },
      { id: "prompt", type: "textarea", required: true },
    ];
    const out = buildGenerateInput(fields, { prompt: "猫" }, {}, {});
    expect(out.missingRequired).toEqual([]); // photo 不计入
    expect(out.valid).toBe(true);
  });
});

// --- form 源码契约：pickAsset 只在 chooseImage success 里标记 + 占位不进 valid ---

describe("form.vue source contract (placeholder image honesty)", () => {
  it("pickAsset marks assetPicked only inside chooseImage success; valid ignores placeholder", async () => {
    const res = await generateProject(prdFor("form-contract"), "avatar-viral");
    const form = await fs.readFile(
      path.join(res.project_path, "src/pages/form/form.vue"),
      "utf-8",
    );
    // 用纯函数归一（主字段语义不丢）。
    expect(form).toContain("buildGenerateInput");
    // assetPicked 只在 success 回调里置 true（取消不标记）。
    expect(form).toMatch(/success:\s*\(\)\s*=>\s*\{[\s\S]*?assetPicked\[f\.id\]\s*=\s*true/);
    // 不存在"进入 pickAsset 立即标记 assetPicked=true"的旧写法。
    expect(form).not.toMatch(/function pickAsset[\s\S]*?assetPicked\[f\.id\]\s*=\s*true[\s\S]*?uni\.chooseImage/);
    // valid 由 buildGenerateInput.valid 决定，占位图不参与。
    expect(form).toContain("built.valid");
  });
});

// --- P0-2 激励广告下载门槛（rewarded video ad gate）行为级测试 ---

describe("rewarded ad download gate (P0-2)", () => {
  // 准备一个 avatar 真实生成成功（有 remote image URL）+ 广告已配置的结果。
  async function prepRealImageWithAd(name: string) {
    const res = await generateProject(prdFor(name), "avatar-viral");
    await forceApiMode(res.project_path);
    await forceAdEnabled(res.project_path);
    const imageUrl = "https://cdn.example.com/" + name + ".png";
    installUni(() => ({
      ok: true,
      preview_type: "avatar",
      result: { image_url: imageUrl, title: "AI 头像已生成", prompt: "猫" },
    }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });
    return { mod, out, imageUrl };
  }

  it("ad unit configured + gate enabled -> result requires ad unlock initially", async () => {
    const { mod, out } = await prepRealImageWithAd("ad-required");
    // 真实生成成功有图：download_gate 透传，初始未解锁，需要看广告。
    expect(out.downloadGate).toBeTruthy();
    expect(out.downloadGate.gate_type).toBe("rewarded_ad");
    expect(out.adUnlockRequired).toBe(true);
    expect(out.adUnlocked).toBeFalsy();
    expect(mod.isRewardedAdRequired(out)).toBe(true);
  });

  it("adUnitId missing -> requestRewardedAdUnlock ok=false reason=not_configured, watermark unchanged", async () => {
    // 默认 ads.ts 是空 id + disabled（不调 forceAdEnabled）。
    const res = await generateProject(prdFor("ad-not-config"), "avatar-viral");
    await forceApiMode(res.project_path);
    installUni(() => ({
      ok: true, preview_type: "avatar",
      result: { image_url: "https://cdn.example.com/x.png", title: "t", prompt: "猫" },
    }));
    const mod = await importGenerated(res.project_path);
    const out = await mod.mockGenerate({ text: "猫" });
    const wmBefore = out.watermarkEnabled;

    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(false);
    expect(r.reason).toBe("not_configured");
    // 水印不变、未解锁。
    const reloaded = mod.loadResult(out.id);
    expect(reloaded.watermarkEnabled).toBe(wmBefore);
    expect(reloaded.adUnlocked).toBeFalsy();
  });

  it("user closes ad early (isEnded=false) -> ok=false reason=closed_early, not unlocked", async () => {
    const { mod, out } = await prepRealImageWithAd("ad-closed-early");
    // 注入 mock 广告工厂：onClose 回传 isEnded=false。
    mod.__setRewardedAdFactory((_id: string) => {
      let closeCb: any = null;
      return {
        load: () => {},
        show: () => { closeCb && closeCb({ isEnded: false }); },
        onClose: (cb: any) => { closeCb = cb; },
        onError: () => {},
      };
    });
    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(false);
    expect(r.reason).toBe("closed_early");
    const reloaded = mod.loadResult(out.id);
    expect(reloaded.adUnlocked).toBeFalsy();
    expect(reloaded.downloadUnlocked).toBeFalsy();
    expect(reloaded.watermarkEnabled).toBe(true);
  });

  it("user finishes ad (isEnded=true) -> ok=true, adUnlocked + downloadUnlocked, watermark removed", async () => {
    const { mod, out } = await prepRealImageWithAd("ad-finished");
    expect(out.removeWatermarkSupported).toBe(true);
    mod.__setRewardedAdFactory((_id: string) => {
      let closeCb: any = null;
      return {
        load: () => {},
        show: () => { closeCb && closeCb({ isEnded: true }); },
        onClose: (cb: any) => { closeCb = cb; },
        onError: () => {},
      };
    });
    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(true);
    const reloaded = mod.loadResult(out.id);
    expect(reloaded.adUnlocked).toBe(true);
    expect(reloaded.downloadUnlocked).toBe(true);
    // gate.required_for 含 remove_watermark + 事实源支持 -> 看完广告去水印。
    expect(reloaded.watermarkEnabled).toBe(false);
    expect(mod.isRewardedAdRequired(reloaded)).toBe(false);
  });

  it("ad error -> ok=false reason=ad_error, not unlocked", async () => {
    const { mod, out } = await prepRealImageWithAd("ad-error");
    mod.__setRewardedAdFactory((_id: string) => {
      let errCb: any = null;
      return {
        load: () => {},
        show: () => { errCb && errCb(new Error("sdk boom")); },
        onClose: () => {},
        onError: (cb: any) => { errCb = cb; },
      };
    });
    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(false);
    expect(r.reason).toBe("ad_error");
    const reloaded = mod.loadResult(out.id);
    expect(reloaded.adUnlocked).toBeFalsy();
  });
});

// --- P0-2 视频导出：remote_video 分类 + saveVideo 路径存在 ---

describe("classifyExportTarget remote_video (P0-2)", () => {
  it("result with remote video_url -> kind=remote_video", async () => {
    const res = await generateProject(prdFor("cls-video"), "avatar-viral");
    installUni(() => ({ ok: true, result: {} }));
    const mod = await importGenerated(res.project_path);
    // 构造带真实视频 URL 的结果（后端未来返回 video_url 时）。
    const r = {
      previewType: "petVideo",
      previewData: { video_url: "https://cdn.example.com/clip.mp4" },
      videoUrl: "https://cdn.example.com/clip.mp4",
      title: "t", shareCopy: "c",
    };
    const target = mod.classifyExportTarget(r);
    expect(target.kind).toBe("remote_video");
    expect(target.video).toBe("https://cdn.example.com/clip.mp4");
  });

  it("result.vue handles remote_video via saveVideoToPhotosAlbum", async () => {
    const res = await generateProject(prdFor("vue-video"), "avatar-viral");
    const vue = await fs.readFile(
      path.join(res.project_path, "src/pages/result/result.vue"),
      "utf-8",
    );
    expect(vue).toContain("saveVideoToPhotosAlbum");
    expect(vue).toContain("remote_video");
  });
});

// --- P0-2 下载漏斗埋点（analytics 事件顺序与失败原因）---

async function importAnalytics(projectPath: string) {
  const svc = path.join(projectPath, "src/services/analytics.ts");
  return import(pathToFileURL(svc).href);
}

// 看完整条广告的 mock 工厂（isEnded=true）。
function adFactoryEnded(mod: any) {
  mod.__setRewardedAdFactory((_id: string) => {
    let closeCb: any = null;
    return {
      load: () => {},
      show: () => { closeCb && closeCb({ isEnded: true }); },
      onClose: (cb: any) => { closeCb = cb; },
      onError: () => {},
    };
  });
}
function adFactoryClosedEarly(mod: any) {
  mod.__setRewardedAdFactory((_id: string) => {
    let closeCb: any = null;
    return {
      load: () => {},
      show: () => { closeCb && closeCb({ isEnded: false }); },
      onClose: (cb: any) => { closeCb = cb; },
      onError: () => {},
    };
  });
}

describe("download funnel analytics events (P0-2)", () => {
  async function prep(name: string, adEnabled = true) {
    const res = await generateProject(prdFor(name), "avatar-viral");
    await forceApiMode(res.project_path);
    if (adEnabled) await forceAdEnabled(res.project_path);
    installUni(() => ({
      ok: true, preview_type: "avatar",
      result: { image_url: "https://cdn.example.com/" + name + ".png", title: "t", prompt: "猫" },
    }));
    const mod = await importGenerated(res.project_path);
    const analytics = await importAnalytics(res.project_path);
    analytics.clearGrowthEvents();
    const out = await mod.mockGenerate({ text: "猫" });
    return { mod, analytics, out };
  }

  it("completed ad -> request -> completed -> download_unlocked order, with watermark_removed", async () => {
    const { mod, analytics, out } = await prep("funnel-ok");
    adFactoryEnded(mod);
    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(true);

    const names = analytics.getGrowthEvents().map((e: any) => e.name);
    // 完播链路顺序（至少包含）：request -> completed -> download_unlocked。
    const reqIdx = names.indexOf("rewarded_ad_request");
    const compIdx = names.indexOf("rewarded_ad_completed");
    const unlockIdx = names.indexOf("download_unlocked");
    expect(reqIdx).toBeGreaterThanOrEqual(0);
    expect(compIdx).toBeGreaterThan(reqIdx);
    expect(unlockIdx).toBeGreaterThan(compIdx);
    // gate 含 remove_watermark -> watermark_removed。
    expect(names).toContain("watermark_removed");
    // 中途关闭不应出现。
    expect(names).not.toContain("rewarded_ad_closed_early");
    // 事件带上下文。
    const reqEvt = analytics.getGrowthEvents().find((e: any) => e.name === "rewarded_ad_request");
    expect(reqEvt.template).toBe("avatar-viral");
    expect(reqEvt.gate_type).toBe("rewarded_ad");
  });

  it("closed early -> closed_early event, NO download_unlocked", async () => {
    const { mod, analytics, out } = await prep("funnel-closed");
    adFactoryClosedEarly(mod);
    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(false);
    const names = analytics.getGrowthEvents().map((e: any) => e.name);
    expect(names).toContain("rewarded_ad_request");
    expect(names).toContain("rewarded_ad_closed_early");
    expect(names).not.toContain("download_unlocked");
    expect(names).not.toContain("rewarded_ad_completed");
  });

  it("ad not configured -> not_configured event, NO completed/unlock", async () => {
    const { mod, analytics, out } = await prep("funnel-noad", /*adEnabled*/ false);
    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(false);
    expect(r.reason).toBe("not_configured");
    const names = analytics.getGrowthEvents().map((e: any) => e.name);
    expect(names).toContain("rewarded_ad_request");
    expect(names).toContain("rewarded_ad_not_configured");
    expect(names).not.toContain("rewarded_ad_completed");
    expect(names).not.toContain("download_unlocked");
  });

  it("ad load error -> rewarded_ad_load_error, not unlocked", async () => {
    const { mod, analytics, out } = await prep("funnel-loaderr");
    mod.__setRewardedAdFactory((_id: string) => ({
      load: () => Promise.reject(new Error("load boom")),
      show: () => {},
      onClose: () => {},
      onError: () => {},
    }));
    const r = await mod.requestRewardedAdUnlock(out.id);
    expect(r.ok).toBe(false);
    expect(r.reason).toBe("ad_error");
    const names = analytics.getGrowthEvents().map((e: any) => e.name);
    expect(names).toContain("rewarded_ad_load_error");
    expect(names).not.toContain("download_unlocked");
  });
});
