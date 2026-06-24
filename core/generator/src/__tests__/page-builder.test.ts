import { describe, it, expect, beforeAll } from "vitest";
import os from "os";
import path from "path";
import fs from "fs-extra";

const OUT = path.join(os.tmpdir(), "gen-test-" + process.pid);

let generateProject: (prd: any, template?: string) => Promise<any>;

beforeAll(async () => {
  process.env.GENERATOR_OUTPUT_DIR = OUT;
  await fs.emptyDir(OUT);
  ({ generateProject } = await import("../codegen/page-builder"));
});

const prd = {
  app_name: "Test App",
  summary: "a test app",
  target_platforms: ["wechat"],
  core_features: [
    { name: "翻译", type: "input" },        // Chinese-only -> must not yield empty path
    { name: "Summary", type: "display" },
  ],
};

describe("generateProject (ai-tool)", () => {
  it("produces a complete buildable uni-app project", async () => {
    const res = await generateProject(prd, "ai-tool");
    const p = res.project_path;
    const required = [
      "package.json",
      "vite.config.ts",
      "tsconfig.json",
      "index.html",
      "src/main.ts",
      "src/App.vue",
      "src/manifest.json",
      "src/pages.json",
      "src/pages/index/index.vue",
    ];
    for (const f of required) {
      expect(await fs.pathExists(path.join(p, f)), `missing ${f}`).toBe(true);
    }
    expect(res.template).toBe("ai-tool");
    expect(res.generated_files_count).toBeGreaterThan(5);
  });

  it("writes manifest/pages under src/", async () => {
    const res = await generateProject(prd, "ai-tool");
    expect(await fs.pathExists(path.join(res.project_path, "src/pages.json"))).toBe(true);
    expect(await fs.pathExists(path.join(res.project_path, "src/manifest.json"))).toBe(true);
    // NOT at project root
    expect(await fs.pathExists(path.join(res.project_path, "pages.json"))).toBe(false);
  });

  it("pages.json contains index + a PRD feature page", async () => {
    const res = await generateProject(prd, "ai-tool");
    const pages = (await fs.readJSON(path.join(res.project_path, "src/pages.json"))).pages;
    const paths = pages.map((p: any) => p.path);
    expect(paths).toContain("pages/index/index");
    // English feature page
    expect(paths).toContain("pages/summary/summary");
  });

  it("Chinese feature names never produce empty paths", async () => {
    const res = await generateProject(prd, "ai-tool");
    const pages = (await fs.readJSON(path.join(res.project_path, "src/pages.json"))).pages;
    for (const pg of pages) {
      expect(pg.path).toMatch(/^pages\/[^/]+\/[^/]+$/);
      expect(pg.path).not.toContain("//");
    }
    // The Chinese feature collapses to a stable fallback name, not empty.
    const paths = pages.map((p: any) => p.path);
    expect(paths.some((x: string) => x.startsWith("pages/feature-"))).toBe(true);
  });

  it("falls back to ai-tool for an unknown template", async () => {
    const res = await generateProject(prd, "nonsense");
    expect(res.template).toBe("ai-tool");
    expect(res.fallback_used).toBe(true);
  });

  // Regression guard: vite.config MUST be .ts, never .mjs.
  // @dcloudio/vite-plugin-uni is CommonJS; under native ESM (.mjs without
  // "type":"module") the default import is the namespace object, not the
  // callable factory -> "uni is not a function" at build time. The .ts path
  // gets esbuild CJS->ESM interop so uni() is callable.
  it("ships canonical vite.config.ts and never a stray .mjs", async () => {
    const res = await generateProject(prd, "ai-tool");
    const p = res.project_path;
    expect(await fs.pathExists(path.join(p, "vite.config.ts"))).toBe(true);
    expect(await fs.pathExists(path.join(p, "vite.config.mjs"))).toBe(false);
    const cfg = await fs.readFile(path.join(p, "vite.config.ts"), "utf-8");
    expect(cfg).toMatch(/from ['"]@dcloudio\/vite-plugin-uni['"]/);
    expect(cfg).toMatch(/plugins:\s*\[\s*uni\(\)\s*\]/);
  });

  // Regression guard: the shared token contract must be fully substituted.
  // The base template ships __APP_NAME__ / __APP_SUBTITLE__ /
  // __APP_FEATURES_JSON__ / __APP_FEATURE_TITLE__ placeholders; both the Node
  // generator and runner.py must fill them. A leftover token = broken output.
  it("fills the shared token contract (no __APP_ tokens leak)", async () => {
    const res = await generateProject(prd, "ai-tool");
    const p = res.project_path;
    const exts = [".vue", ".json", ".ts", ".md", ".html"];
    const walk = async (dir: string): Promise<string[]> => {
      const out: string[] = [];
      for (const e of await fs.readdir(dir, { withFileTypes: true })) {
        const full = path.join(dir, e.name);
        if (e.isDirectory()) {
          if (e.name === "node_modules") continue;
          out.push(...(await walk(full)));
        } else if (exts.includes(path.extname(e.name))) {
          out.push(full);
        }
      }
      return out;
    };
    for (const f of await walk(p)) {
      const text = await fs.readFile(f, "utf-8");
      expect(text.includes("__APP_"), `unfilled token in ${path.relative(p, f)}`).toBe(false);
    }
    // app data actually injected into the index page
    const idx = await fs.readFile(path.join(p, "src/pages/index/index.vue"), "utf-8");
    expect(idx).toContain(prd.app_name);
  });

  // Regression guard: base template owns the full skeleton (single source).
  it("produces the full skeleton from the base template", async () => {
    const res = await generateProject(prd, "ai-tool");
    const p = res.project_path;
    for (const f of [
      "package.json", "tsconfig.json", "index.html", "vite.config.ts",
      "src/main.ts", "src/App.vue", "src/utils/request.ts",
      "src/pages/index/index.vue", "src/pages/form/form.vue",
      "src/pages/result/result.vue", "src/pages/profile/profile.vue",
    ]) {
      expect(await fs.pathExists(path.join(p, f)), `missing ${f}`).toBe(true);
    }
  });

  // 传播型模板工厂：每个 *-viral 模板必须可选中、有独立身份页、保留可构建骨架。
  const VIRAL = [
    { template: "avatar-viral", sig: "src/pages/gallery/gallery.vue" },
    { template: "sticker-viral", sig: "src/pages/pack/pack.vue" },
    { template: "pet-talk-viral", sig: "src/pages/upload/upload.vue" },
    { template: "funny-video-viral", sig: "src/pages/clip/clip.vue" },
    { template: "blessing-video-viral", sig: "src/pages/greeting/greeting.vue" },
  ];
  for (const { template, sig } of VIRAL) {
    it(`selects ${template} and keeps a buildable skeleton + signature page`, async () => {
      const res = await generateProject(prd, template);
      const p = res.project_path;
      expect(res.template).toBe(template);
      expect(res.fallback_used).toBe(false);
      // 题材身份页存在（base 没有）
      expect(await fs.pathExists(path.join(p, sig)), `missing signature ${sig}`).toBe(true);
      // base 骨架仍在，保证可构建
      for (const f of ["vite.config.ts", "package.json", "src/pages/index/index.vue"]) {
        expect(await fs.pathExists(path.join(p, f)), `missing ${f}`).toBe(true);
      }
      // index 仍填了 token（题材 overlay 兼容 token 契约）
      const idx = await fs.readFile(path.join(p, "src/pages/index/index.vue"), "utf-8");
      expect(idx).not.toContain("__APP_");
      expect(idx).toContain(prd.app_name);
    });
  }

  // P0-1: pet-talk upload 签名页必须接入 mockGenerate 并带 result.id 跳转，
  // 不能是「等一会儿跳无 id 的 result」断链页，也不能宣称生成视频。
  it("pet-talk upload page is wired to mockGenerate (no broken result link)", async () => {
    const res = await generateProject(prd, "pet-talk-viral");
    const raw = await fs.readFile(
      path.join(res.project_path, "src/pages/upload/upload.vue"),
      "utf-8",
    );
    // 去 HTML 注释后再校验用户可见/逻辑文案（注释里的口径说明不算违规）。
    const upload = raw.replace(/<!--[\s\S]*?-->/g, " ");
    // 接入统一生成入口。
    expect(upload).toContain("mockGenerate");
    // 跳转必须带 result.id（不再是无 id 的 /pages/result/result）。
    expect(upload).toMatch(/result\?id=/);
    expect(upload).not.toMatch(/navigateTo\(\s*\{\s*url:\s*['"]\/pages\/result\/result['"]\s*\}/);
    // 不得宣称生成视频。
    expect(upload).not.toContain("生成说话视频");
    expect(upload).not.toContain("生成视频");
    // 照片占位口径明确。
    expect(upload).toContain("占位");
  });

  // P1: 生成项目交互闭环结构（generation service + 模板配置 + 模板 token 注入）。
  it("ships the generation service and injects selected template", async () => {
    const res = await generateProject(prd, "avatar-viral");
    const p = res.project_path;
    // 统一生成服务存在且含契约
    const svcPath = path.join(p, "src/services/generation.ts");
    expect(await fs.pathExists(svcPath), "missing src/services/generation.ts").toBe(true);
    const svc = await fs.readFile(svcPath, "utf-8");
    for (const token of ["mockGenerate", "GeneratedResult", "shareTitle", "unlockHint", "watermarkEnabled"]) {
      expect(svc.includes(token), `generation.ts missing ${token}`).toBe(true);
    }
    // 模板配置注入真实 selected template，无残留 token
    const cfg = await fs.readFile(path.join(p, "src/config/template.ts"), "utf-8");
    expect(cfg).not.toContain("__APP_TEMPLATE__");
    expect(cfg).not.toContain("__APP_PREVIEW_TYPE__");
    expect(cfg).toContain("avatar-viral");
    expect(cfg).toContain("PREVIEW_TYPE");
    // form 调用 mockGenerate
    const form = await fs.readFile(path.join(p, "src/pages/form/form.vue"), "utf-8");
    expect(form).toContain("mockGenerate");
  });

  // v2: blueprint 接入（template.json -> blueprint.json）与 Python codegen parity。
  it("writes blueprint.json and keeps generation.ts blueprint-driven", async () => {
    const res = await generateProject(prd, "avatar-viral");
    const p = res.project_path;
    // blueprint.json 写入，template_id / preview_type 正确
    const bpPath = path.join(p, "src/config/blueprint.json");
    expect(await fs.pathExists(bpPath), "missing src/config/blueprint.json").toBe(true);
    const bp = await fs.readJSON(bpPath);
    expect(bp.template_id).toBe("avatar-viral");
    expect(bp.preview_type).toBe("avatar");
    expect(bp.is_fallback).toBe(false);
    // 模板能力字段（P0-1 收口）：avatar-viral 是核心可跑通
    expect(bp.template_status).toBe("core_runnable");
    expect(bp.generation_backend).toBe("template_api");
    expect(bp.real_generation).toBe(true);
    expect(bp.fallback_mode).toBe(false);
    // generation.ts 支持 blueprint 驱动
    const svc = await fs.readFile(path.join(p, "src/services/generation.ts"), "utf-8");
    expect(svc).toContain("loadBlueprint");
    expect(svc).toContain("generateFromBlueprint");
  });

  // P0-1: 诚实边界型模板（funny/blessing）blueprint 状态正确。
  const HONEST = ["funny-video-viral", "blessing-video-viral"];
  for (const template of HONEST) {
    it(`marks ${template} as honest_preview (not fallback config)`, async () => {
      const res = await generateProject(prd, template);
      const bp = await fs.readJSON(path.join(res.project_path, "src/config/blueprint.json"));
      expect(bp.template_status).toBe("honest_preview");
      expect(bp.generation_backend).toBe("honest_fallback");
      expect(bp.real_generation).toBe(false);
      expect(bp.fallback_mode).toBe(true);
      // 有自己的 template.json，不是兜底配置
      expect(bp.is_fallback).toBe(false);
    });
  }

  // v2: 兜底模板（ai-tool）无 template.json -> fallback blueprint（preview_type text）。
  it("falls back to a text blueprint for templates without template.json", async () => {
    const res = await generateProject(prd, "ai-tool");
    const p = res.project_path;
    const bp = await fs.readJSON(path.join(p, "src/config/blueprint.json"));
    expect(bp.preview_type).toBe("text");
    expect(bp.is_fallback).toBe(true);
  });

  // P0-2 parity: Node 生成的 blueprint.json 必须写入结构化 growth_loop（与 Python 对齐），
  // 不能 Python 写了、Node 半拉子不写。
  const GROWTH_LOOP_KEYS = [
    "has_share_cta", "share_cta_label", "share_title", "share_copy",
    "has_unlock", "unlock_type", "unlock_hint",
    "has_watermark", "watermark_label", "remove_watermark_supported",
    "brand_exposure", "brand_label",
    "download_supported", "export_supported", "export_label",
    "capability_mode", "capability_note",
  ];

  it("writes a complete growth_loop for viral templates (capability_mode=real)", async () => {
    const res = await generateProject(prd, "avatar-viral");
    const bp = await fs.readJSON(path.join(res.project_path, "src/config/blueprint.json"));
    expect(bp.growth_loop, "blueprint.json 缺少 growth_loop").toBeTruthy();
    for (const k of GROWTH_LOOP_KEYS) {
      expect(k in bp.growth_loop, `growth_loop 缺键 ${k}`).toBe(true);
    }
    // 核心模板 capability_mode 必须 real
    expect(bp.growth_loop.capability_mode).toBe("real");
  });

  it("writes growth_loop with capability_mode=fallback_preview for video boundary templates", async () => {
    for (const template of ["funny-video-viral", "blessing-video-viral"]) {
      const res = await generateProject(prd, template);
      const bp = await fs.readJSON(path.join(res.project_path, "src/config/blueprint.json"));
      expect(bp.growth_loop, `${template} 缺 growth_loop`).toBeTruthy();
      expect(bp.growth_loop.capability_mode).toBe("fallback_preview");
    }
  });

  it("writes a generic growth_loop even for fallback (ai-tool) templates", async () => {
    const res = await generateProject(prd, "ai-tool");
    const bp = await fs.readJSON(path.join(res.project_path, "src/config/blueprint.json"));
    expect(bp.growth_loop, "兜底模板也必须有 growth_loop").toBeTruthy();
    for (const k of GROWTH_LOOP_KEYS) {
      expect(k in bp.growth_loop, `fallback growth_loop 缺键 ${k}`).toBe(true);
    }
    expect(bp.growth_loop.capability_mode).toBe("fallback_preview");
  });
});


