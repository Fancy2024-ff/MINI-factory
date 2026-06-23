/**
 * Page builder — generates uni-app pages from PRD features (Node / parity shell).
 *
 * ⚠️ NOT the live execution source. The single execution truth for the
 * production pipeline (apps/api → core/pipeline/runner.py) is the Python module
 * `core/generator/codegen.py` (generate_miniapp). This TypeScript builder is a
 * **parity / compatibility shell** for the Node ecosystem and its vitest suite;
 * it MUST stay rule-compatible with codegen.py:
 *   - same template fact source: core/generator/src/templates
 *   - same token contract: __APP_NAME__ / __APP_SUBTITLE__ /
 *     __APP_FEATURES_JSON__ / __APP_FEATURE_TITLE__
 *   - same template selection names (base / ai-* / *-viral)
 * If you change generation rules, change codegen.py first, then mirror here.
 *
 * Strategy (fixed, shared with codegen.py):
 *   1. ALWAYS copy the complete `base` template first (guarantees a buildable project).
 *   2. Overlay the requested template (ai-tool / *-viral / ...) on top.
 *   3. Fill the shared token contract on data-injected pages.
 *   4. Generate PRD feature pages (without clobbering template pages).
 *   5. Write manifest.json -> src/manifest.json and pages.json -> src/pages.json.
 */

import path from "path";
import fs from "fs-extra";

interface PRDFeature {
  name: string;
  description?: string;
  type?: "input" | "display" | "interaction" | "navigation";
  api_endpoint?: string;
}

interface PRD {
  app_name: string;
  summary?: string;
  core_features: PRDFeature[];
  target_platforms: string[];
  monetization?: string;
}

interface GenerateResult {
  project_path: string;
  pages_generated: number;
  platforms: string[];
  template: string;
  fallback_used: boolean;
  generated_files_count: number;
}

const ALLOWED_TEMPLATES = [
  "base", "ai-tool", "ai-chat", "ai-image",
  // 传播型模板工厂（题材模板，overlay 在 base 之上）
  "avatar-viral", "sticker-viral", "pet-talk-viral",
  "funny-video-viral", "blessing-video-viral",
] as const;
type TemplateName = (typeof ALLOWED_TEMPLATES)[number];

// Reserved template page names that PRD features must never overwrite.
// 含各题材模板的签名页（gallery/pack/upload），避免被 PRD feature 页覆盖。
const RESERVED_PAGES = new Set([
  "index", "form", "result", "profile", "chat", "canvas",
  "gallery", "pack", "upload", "clip", "greeting",
]);

/**
 * Resolve the templates directory robustly whether we run from source (tsx,
 * __dirname = src/codegen) or from the compiled output (tsc, __dirname =
 * dist/codegen). Templates are NOT copied into dist, so we look in both spots.
 */
function resolveTemplatesDir(): string {
  const candidates = [
    path.resolve(__dirname, "../templates"), // dev: src/codegen -> src/templates
    path.resolve(__dirname, "../../src/templates"), // prod: dist/codegen -> src/templates
    path.resolve(process.cwd(), "src/templates"),
    path.resolve(process.cwd(), "core/generator/src/templates"),
    path.resolve(process.cwd(), "generator/src/templates"), // legacy layout
  ];
  for (const c of candidates) {
    if (fs.pathExistsSync(c)) return c;
  }
  // Fall back to the dev path; downstream existence checks will surface a clear error.
  return candidates[0];
}

function resolveProjectsDir(): string {
  if (process.env.GENERATOR_OUTPUT_DIR) {
    return path.resolve(process.env.GENERATOR_OUTPUT_DIR);
  }
  return path.resolve(__dirname, "../../data/projects");
}

const TEMPLATES_DIR = resolveTemplatesDir();
const PROJECTS_DIR = resolveProjectsDir();

/** Sanitize a feature name into a safe ascii page directory/file name. */
function sanitizePageName(name: string, index: number): string {
  const cleaned = (name || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  // Chinese-only / empty names collapse to '' -> fall back to a stable name.
  return cleaned || `feature-${index + 1}`;
}

const VIRAL_TEMPLATES = new Set([
  "avatar-viral", "sticker-viral", "pet-talk-viral",
  "funny-video-viral", "blessing-video-viral",
]);

const SUPPORTED_PREVIEW_TYPES = new Set([
  "avatar", "stickerPack", "petVideo", "funnyStoryboard", "blessingCard",
  "image", "text",
]);

/**
 * Resolve a template blueprint from its template.json (parity with Python
 * core/generator/blueprint_builder.py). Viral templates MUST have a valid
 * template.json (no silent downgrade); fallback templates default to a text
 * blueprint. Returns the structured blueprint object written to the project.
 */
async function buildBlueprint(
  template: string,
  prd: PRD,
  templatesDir: string
): Promise<any> {
  const cfgPath = path.join(templatesDir, template, "template.json");
  const appName = prd.app_name;
  if (await fs.pathExists(cfgPath)) {
    const cfg = await fs.readJSON(cfgPath);
    if (cfg.id !== template) {
      throw new Error(`${template}/template.json id=${cfg.id} 与目录名不一致`);
    }
    if (!SUPPORTED_PREVIEW_TYPES.has(cfg.preview_type)) {
      throw new Error(`${template}/template.json preview_type=${cfg.preview_type} 不受支持`);
    }
    const resultContract = (cfg.result_fields || [])
      .map((f: any) => f.id)
      .filter(Boolean);
    const realGeneration = !!cfg.real_generation;
    return {
      template_id: cfg.id,
      app_name: appName || cfg.name_cn,
      preview_type: cfg.preview_type,
      input_fields: cfg.input_fields,
      pages: cfg.pages || [],
      result_contract: resultContract,
      share_hooks: cfg.share_hooks,
      unlock_hooks: cfg.unlock_hooks,
      growth_angles: cfg.growth_angles || [],
      compliance_notes: cfg.compliance_notes || [],
      mock_examples: cfg.mock_examples,
      is_fallback: false,
      // 模板能力字段（与 Python _capability_from_config 对齐）。
      template_status: cfg.template_status || (realGeneration ? "core_runnable" : "honest_preview"),
      status_label: cfg.status_label || (realGeneration ? "核心可跑通" : "诚实预览"),
      generation_backend: cfg.generation_backend || (realGeneration ? "template_api" : "honest_fallback"),
      real_generation: realGeneration,
      fallback_mode: cfg.fallback_mode !== undefined ? !!cfg.fallback_mode : !realGeneration,
      result_identity: cfg.result_identity || cfg.description || "",
      boundary_note: cfg.boundary_note || "",
      qa_expectation: cfg.qa_expectation || "",
      frontend_badge: cfg.frontend_badge || cfg.status_label || (realGeneration ? "核心可跑通" : "诚实预览"),
    };
  }
  if (VIRAL_TEMPLATES.has(template)) {
    throw new Error(`传播型模板 ${template} 缺少 template.json，拒绝静默降级。`);
  }
  // fallback blueprint（与 Python _fallback_blueprint 对齐的轻量版）
  return {
    template_id: template,
    app_name: appName || "小程序",
    preview_type: "text",
    input_fields: [
      { id: "text", label: "输入内容", type: "textarea", required: false,
        placeholder: "请输入内容 / 主题 / 一句话..." },
    ],
    pages: ["index", "form", "result", "profile"],
    result_contract: ["text"],
    share_hooks: ["看看我用它生成的结果", "一键生成，分享解锁完整高清结果"],
    unlock_hooks: ["分享解锁高清无水印结果", "分享解锁更多模板"],
    growth_angles: ["通用工具型分享", "结果页内置分享入口"],
    compliance_notes: ["生成内容需符合平台规范"],
    mock_examples: [{
      title: "生成结果",
      preview_type: "text",
      preview_data: { text: "这是一段示例生成结果。" },
      share_title: "看看我用它生成的结果",
      share_copy: "一键生成，分享解锁完整高清结果",
      unlock_hint: "分享解锁高清无水印结果 + 解锁更多模板",
    }],
    is_fallback: true,
    // 兜底模板默认通用预览，不冒充真实生成（与 Python _fallback_blueprint 对齐）。
    template_status: "honest_preview",
    status_label: "通用预览",
    generation_backend: "honest_fallback",
    real_generation: false,
    fallback_mode: true,
    result_identity: "通用文本结果",
    boundary_note: "通用兜底模板：当前仅提供通用文本预览，非题材化真实生成。",
    qa_expectation: "兜底模板，无强制题材分类要求。",
    frontend_badge: "通用预览",
  };
}

export async function generateProject(
  prd: PRD,
  template: string = "ai-tool"
): Promise<GenerateResult> {
  if (!prd || !prd.app_name) {
    throw new Error("PRD with app_name is required");
  }

  // Validate template; fall back to ai-tool for anything unknown.
  let fallbackUsed = false;
  let selected = template as TemplateName;
  if (!ALLOWED_TEMPLATES.includes(selected)) {
    selected = "ai-tool";
    fallbackUsed = true;
  }

  const projectName =
    prd.app_name
      .toLowerCase()
      .replace(/[^a-z0-9一-龥]/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "miniapp-project";

  const projectPath = path.join(PROJECTS_DIR, projectName);

  // --- 1. ALWAYS copy the complete base template first ---
  const basePath = path.join(TEMPLATES_DIR, "base");
  if (!(await fs.pathExists(basePath))) {
    throw new Error(`Base template not found at ${basePath}`);
  }
  await fs.emptyDir(projectPath);
  await fs.copy(basePath, projectPath, { overwrite: true });

  // --- 2. Overlay the requested template (if not base) ---
  if (selected !== "base") {
    const overlayPath = path.join(TEMPLATES_DIR, selected);
    if (await fs.pathExists(overlayPath)) {
      await fs.copy(overlayPath, projectPath, { overwrite: true });
    } else {
      fallbackUsed = true;
    }
  }

  const srcDir = path.join(projectPath, "src");
  const pagesDir = path.join(srcDir, "pages");
  await fs.ensureDir(pagesDir);

  // --- 2a. 解析模板蓝图（template.json -> blueprint），与 Python blueprint_builder 对齐。
  // viral 模板缺 template.json 视为非法（保持与 Python 同样不静默降级的口径）；
  // 兜底模板缺配置 -> preview_type 'text'。完整蓝图写到 src/config/blueprint.json。
  const blueprint = await buildBlueprint(selected, prd, TEMPLATES_DIR);
  const previewType = blueprint.preview_type;

  // --- 2b. Fill the shared token contract on the data-injected template
  // pages. The base template (single source of page structure) ships
  // __APP_NAME__ / __APP_SUBTITLE__ / __APP_FEATURES_JSON__ /
  // __APP_FEATURE_TITLE__ / __APP_TEMPLATE__ / __APP_PREVIEW_TYPE__ placeholders;
  // runner.py fills the same tokens. This keeps page STRUCTURE in the template,
  // only DATA here.
  const featureNames = (prd.core_features || []).map((f) => f.name).filter(Boolean);
  const tokens: Record<string, string> = {
    __APP_NAME__: prd.app_name,
    __APP_SUBTITLE__: (prd.summary || "").slice(0, 40),
    __APP_FEATURES_JSON__: JSON.stringify(featureNames),
    __APP_FEATURE_TITLE__: featureNames[0] || "功能",
    __APP_TEMPLATE__: selected,
    __APP_PREVIEW_TYPE__: previewType,
  };
  for (const rel of [
    "pages/index/index.vue",
    "pages/form/form.vue",
    "config/template.ts",
  ]) {
    const f = path.join(srcDir, rel);
    if (await fs.pathExists(f)) {
      let text = await fs.readFile(f, "utf-8");
      for (const [k, v] of Object.entries(tokens)) text = text.split(k).join(v);
      await fs.writeFile(f, text, "utf-8");
    }
  }

  // --- 2c. Write the structured blueprint into the generated project. ---
  await fs.ensureDir(path.join(srcDir, "config"));
  await fs.writeFile(
    path.join(srcDir, "config", "blueprint.json"),
    JSON.stringify(blueprint, null, 2),
    "utf-8"
  );

  // --- 3. Generate PRD feature pages (never overwrite template pages) ---
  let pagesGenerated = 0;
  const prdPages: Array<{ path: string; style: { navigationBarTitleText: string } }> = [];
  prd.core_features = prd.core_features || [];

  for (let idx = 0; idx < prd.core_features.length; idx++) {
    const feature = prd.core_features[idx];
    const pageName = sanitizePageName(feature.name, idx);
    const pagePath = `pages/${pageName}/${pageName}`;
    prdPages.push({ path: pagePath, style: { navigationBarTitleText: feature.name } });

    if (RESERVED_PAGES.has(pageName)) {
      // Keep the richer template page; only register the route.
      continue;
    }
    const pageDir = path.join(pagesDir, pageName);
    await fs.ensureDir(pageDir);
    await fs.writeFile(
      path.join(pageDir, `${pageName}.vue`),
      generateVuePage(feature, prd.app_name),
      "utf-8"
    );
    pagesGenerated++;
  }

  // --- 4. Write manifest.json under src/ ---
  const manifest = generateManifest(prd);
  await fs.writeFile(
    path.join(srcDir, "manifest.json"),
    JSON.stringify(manifest, null, 2),
    "utf-8"
  );

  // --- 5. Merge + write pages.json under src/ ---
  const pagesJsonPath = path.join(srcDir, "pages.json");
  let templatePages: any[] = [];
  let templateGlobalStyle: any = {};
  let templateTabBar: any = {};
  if (await fs.pathExists(pagesJsonPath)) {
    const existing = await fs.readJSON(pagesJsonPath);
    templatePages = existing.pages || [];
    templateGlobalStyle = existing.globalStyle || {};
    templateTabBar = existing.tabBar || {};
  }

  // Discover any extra pages shipped by the overlay (e.g. ai-tool form/result).
  const discoveredPages: any[] = [];
  if (await fs.pathExists(pagesDir)) {
    for (const dir of await fs.readdir(pagesDir)) {
      const vue = path.join(pagesDir, dir, `${dir}.vue`);
      if (await fs.pathExists(vue)) {
        discoveredPages.push({ path: `pages/${dir}/${dir}` });
      }
    }
  }

  const seen = new Set<string>();
  const mergedPages: any[] = [];
  const pushPage = (pg: any) => {
    if (!pg?.path || seen.has(pg.path)) return;
    seen.add(pg.path);
    mergedPages.push(pg);
  };
  // index first
  pushPage({ path: "pages/index/index", style: { navigationBarTitleText: "首页" } });
  templatePages.forEach(pushPage);
  discoveredPages.forEach(pushPage);
  prdPages.forEach(pushPage);

  const pagesConfig = {
    pages: mergedPages,
    globalStyle: templateGlobalStyle.navigationBarTextStyle
      ? templateGlobalStyle
      : {
          navigationBarTextStyle: "black",
          navigationBarBackgroundColor: "#ffffff",
          backgroundColor: "#f5f5f5",
        },
    ...(templateTabBar.list?.length ? { tabBar: templateTabBar } : {}),
  };
  await fs.writeFile(pagesJsonPath, JSON.stringify(pagesConfig, null, 2), "utf-8");

  const generatedFilesCount = (await fs.pathExists(projectPath))
    ? await walkCountAsync(projectPath)
    : 0;

  return {
    project_path: projectPath,
    pages_generated: pagesGenerated,
    platforms: prd.target_platforms || [],
    template: selected,
    fallback_used: fallbackUsed,
    generated_files_count: generatedFilesCount,
  };
}

async function walkCountAsync(dir: string): Promise<number> {
  let count = 0;
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules") continue;
      count += await walkCountAsync(full);
    } else {
      count++;
    }
  }
  return count;
}

function generateVuePage(feature: PRDFeature, appName: string): string {
  return `<template>
  <view class="container">
    <view class="header">
      <text class="title">${feature.name}</text>
      <text class="desc">${feature.description || ""}</text>
    </view>

    <view class="content">
      <!-- ${feature.type || "input"} type component -->
      ${getComponentByType(feature)}
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const loading = ref(false)
const result = ref('')

async function handleAction() {
  loading.value = true
  try {
    const response = await uni.request({
      url: '${feature.api_endpoint || "/api/" + (feature.name || "action").toLowerCase()}',
      method: 'POST',
      data: {}
    })
    result.value = response.data as string
  } catch (error) {
    uni.showToast({ title: '操作失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.container { padding: 32rpx; min-height: 100vh; background: #f5f5f5; }
.header { margin-bottom: 40rpx; }
.title { font-size: 36rpx; font-weight: bold; color: #333; }
.desc { font-size: 28rpx; color: #666; margin-top: 12rpx; display: block; }
.content { background: #fff; border-radius: 16rpx; padding: 32rpx; }
</style>
`;
}

function getComponentByType(feature: PRDFeature): string {
  switch (feature.type) {
    case "input":
      return `<textarea class="input-area" placeholder="请输入内容..." />
      <button class="action-btn" @click="handleAction" :loading="loading">开始处理</button>
      <view v-if="result" class="result-area">{{ result }}</view>`;
    case "display":
      return `<view class="display-area">
        <image v-if="result" :src="result" mode="widthFix" />
      </view>`;
    case "interaction":
      return `<scroll-view class="chat-area" scroll-y>
      </scroll-view>
      <view class="input-bar">
        <input placeholder="输入消息..." />
        <button size="mini" @click="handleAction">发送</button>
      </view>`;
    default:
      return `<view class="default-content">
        <text>{{ result || '暂无内容' }}</text>
      </view>`;
  }
}

function generateManifest(prd: PRD): object {
  return {
    name: prd.app_name,
    appid: "",
    description: prd.summary || "",
    versionName: "1.0.0",
    versionCode: "100",
    "mp-weixin": { appid: "", setting: { urlCheck: false }, usingComponents: true },
    "mp-alipay": { appid: "" },
    "mp-toutiao": { appid: "" },
  };
}
