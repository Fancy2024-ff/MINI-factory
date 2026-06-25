# 工厂产物并入合集：能力渲染器 + 功能注册表（v1）

> 状态：设计待审 · 日期：2026-06-25
> 目标：工厂抓到新 app → 自动作为一张新卡片加入 TG 合集（不覆盖旧功能）→ 点进去是真能用、功能名副其实的页面。

## 1. 背景与根因

当前存在两个独立缺陷，叠加导致「每抓一个 app 就替换掉合集、且功能名不副实」：

1. **覆盖合集**：`core/publisher/telegram_deploy.py` 把单个 app 的一个 `index.html` 用 `wrangler pages deploy` 推到 `miniforge-app` 项目生产根。Cloudflare Pages 是整站全量替换，于是合集（同项目）被单页覆盖。
2. **功能名不副实**：
   - `core/opportunity/feature_extraction.py:17-19` 把 `background_remover` 这个 feature 的 `template` 硬编码成 `ai-image`（文生图），而不是 `background-remover`。
   - `telegram_deploy.py` 完全无视 `selected_template`，只看环境变量 `TELEGRAM_WEBAPP_KIND`（默认 `image`），永远渲染文生图页 `image.html`。

合集本身（`apps/web/src/tg/`）已有 5 个**真功能页**：`AiImagePage`(文生图)、`AvatarPage`、`StickerPage`、`PetTalkPage`、`BgRemovePage`(图生图/去背景，调 `/api/generation/image-edit`)。问题是工厂从不复用它们。

## 2. 后端能力的事实边界（设计铁律的依据）

后端 `core/integrations/image_generation.py` 只有两类真实能力：

- `generate_image(prompt, style, aspect_ratio)` → 文生图。已验证可用。
- `edit_image(image_bytes, prompt)` → 图生图（`/images/edits`，模型 `IMAGE_EDIT_MODEL=gpt-image-2`）。

**关键事实**：`edit_image` 不接受 `task` 参数。`task` 仅在 API 层（`apps/api/main.py` 的 `/api/generation/image-edit`）用于**选 prompt**：`task=background_remove` 用内置 `BG_REMOVE_PROMPT`，其余直接用传入 prompt。底层没有任务专属逻辑。

**推论（铁律）**：一个 `task` 是否「名副其实」，取决于「该 prompt 在真实后端模型上的产出质量」，无法靠配置声明保证。因此 **task 白名单 = 已用真实后端验证过、产出名副其实的集合**，新 task 进白名单必须先过验证关，否则只能进 pending/review，不自动上线。这直接落实「不能只靠 editPrompt 保证名副其实」。

## 3. 核心架构：功能注册表 + 能力渲染器 + 任务适配器

分层（避免抽象过薄）：

```
features.json (合并产物)
   ↓
FeatureRegistry (featureRegistry.ts：读取/校验/查询，唯一 registry 逻辑出口)
   ↓
ability renderer (text2img → TextToImageFeaturePage / img2img → ImageToImageFeaturePage)
   ↓
task adapter (task → 后端调用意图 + prompt 构造)
   ↓
image generation / edit API
```

明确语义分离：
- **ability** = 页面交互形态（白名单：`text2img` / `img2img`），只决定用哪个页面壳。
- **task** = 实际业务意图（白名单），决定后端怎么调、用什么 prompt、怎么校验产出。
- **feature config** = 产品化包装（标题/副标题/图标/输入要求/UI 文案）。
- **registry** = 自动扩容入口（首页/路由只读，不写）。

> 这是合集自动扩容的 **v1 能力渲染器层**，不是业务能力的最终边界。后续新增能力形态（如真视频、语音）时，在 ability/task 白名单与 renderer 层扩展，registry 与工厂流程不变。

## 4. 配置 Schema

每个 feature 配置项结构（强化版，避免「只换标题和 prompt」）：

```jsonc
{
  "id": "old-photo-restore",        // 稳定、唯一、URL-safe（^[a-z0-9-]+$）
  "title": "老照片修复",
  "icon": "🖼",
  "ability": "img2img",             // 白名单：text2img | img2img
  "task": "restore",                // 白名单（见 §5）
  "subtitle": "修复老旧照片、去划痕并提升清晰度",
  "input": {
    "imageRequired": true,
    "textRequired": false,
    "acceptedTypes": ["image/png", "image/jpeg", "image/webp"]
  },
  "params": {
    "editPrompt": "修复这张老照片，去除划痕，提升清晰度，保留人物真实面貌",
    "outputMode": "edited_image"    // generated_image | edited_image | transparent_png
  },
  "ui": {
    "uploadLabel": "上传老照片",
    "submitLabel": "开始修复",
    "resultTitle": "修复结果",
    "textPlaceholder": ""           // text2img 用
  },
  "source": { "type": "factory", "confidence": 0.86 }  // builtin | factory
}
```

校验规则（registry validation，build 前强制跑）：
- `id` 唯一、URL-safe；重复时跳过并记日志，不覆盖。
- `ability` ∈ 白名单；`task` ∈ 白名单。
- `text2img` 必须 `input.textRequired=true`；`img2img` 必须 `input.imageRequired=true`（能力兼容校验）。
- 必填字段齐全：`id/title/icon/ability/task/subtitle/ui.submitLabel`。
- 任一项校验失败 → 该项被拒（不进合并产物），构建不因坏项静默带病上线。

## 5. ability / task 白名单（v1）

ability 白名单：`text2img`、`img2img`。

task 白名单（**只含已用真实后端验证过、名副其实的**）：

| task | ability | 后端 | 状态 |
|---|---|---|---|
| `generate_image` | text2img | `/api/generation/image` | ✅ 已验证 |
| `background_remove` | img2img | `/api/generation/image-edit` (内置 BG_REMOVE_PROMPT) | ✅ 已验证 |

> 其余 task（restore / cartoonize / change-bg-color 等）**默认不在白名单**。工厂识别到这类题材时，配置进入 `pending`（不上线），需先用真实后端验证该 task 的 prompt 产出名副其实，再人工加入白名单。这是「低置信度不自动上线」的落地。

## 6. 注册表分离与合并策略

```
apps/web/src/tg/registry/
  features.base.json        # 手写内置功能（5 个现有页），工厂永不改
  features.generated.json   # 工厂 append 的新功能，唯一自动写入口
  (build 前合并 → 内存 registry，base 优先；同 id 以 base 为准并记日志)
```

- 工厂只写 `features.generated.json`，且只 append、同 id 跳过。永不触碰 base。
- 合并在 `featureRegistry.ts` 加载时完成；base 与 generated 同 id 冲突时 base 胜。
- 好处：自动流程不污染人工配置、无 merge 冲突、回滚只需清 generated。

## 7. 前端改动（数据驱动）

- 新增 `apps/web/src/tg/registry/featureRegistry.ts`：`getAllFeatures()` / `getFeatureById(id)` / 加载时校验。registry 逻辑只此一处，不散入组件。
- 新增 2 个能力渲染器组件（由现有页抽象而来，保留其真实后端调用与重试/广告逻辑）：
  - `TextToImageFeaturePage.vue`（源自 AiImagePage）
  - `ImageToImageFeaturePage.vue`（源自 BgRemovePage）
  - 接收 feature config 作为 props，按 `params`/`ui`/`input` 渲染与调用。
- `TgHome.vue`：卡片改为 `v-for getAllFeatures()` 渲染，不再硬编码。
- `TgApp.vue` / `route.ts`：路由改为 `/tg/{id}`，按 `getFeatureById(id).ability` 选渲染器；**id 不在 registry → 显示「功能不存在」，不再默认跳 ai-image**。
- 现有 5 个页迁为 base 配置 + 渲染器，URL（id）保持不变。实测形态：
  - `ai-image`：text2img（文字→图）
  - `avatar`：text2img（纯文字，页面已注明「暂不支持上传自拍」）
  - `sticker`：text2img（纯文字）
  - `pet-talk`：text2img（文字 + 一个**占位**上传，占位不调后端）→ 迁移时去掉假占位，老实呈现为 text2img
  - `bg-remove`：img2img（上传→去背景）
  > pet-talk 的占位上传是历史遗留的「看着能用实则不调用」，迁移顺手清掉，符合「功能名副其实」。

## 8. 工厂改动

- `core/opportunity/feature_extraction.py:17-19`：修 `background_remover` 的 template 错配（→ 正确 ability/task）。
- 分类产出从「单一 template 名」升级为「ability + task + 配置草稿」。沿用 `classifier.py` 的关键词匹配，但输出对齐新 schema。
- `core/publisher/telegram_deploy.py` 重写部署流程：
  ```
  生成 feature draft → validate（schema + 白名单 + 能力兼容）
    → 不合规或 task 不在白名单 → 记 pending，不上线
    → 合规 → append 到 features.generated.json（同 id 跳过）
    → npm run build 合集 → smoke test → 部署 dist 到 miniforge-app 根
  ```
- 删除/弃用单页渲染路径（`render_image_template` / `image.html` 单部署）。

## 9. 部署安全门（防止新增 app 弄挂合集）

部署前必须通过，任一失败则中止部署、保留线上现状：
- registry validation 通过（无坏项）。
- `npm run build` 成功。
- 路由 smoke test：合集功能数 ≥ 部署前数量（旧功能不丢）；新 id 能解析到渲染器。
- 失败 → 不部署，报告原因。

## 10. 测试

- 后端/Python：`feature_extraction` 修复后映射正确（pytest）；telegram_deploy 的 validate/merge/pending 分支。
- 前端/vitest：registry 校验（坏项被拒、同 id 跳过、白名单外 task 拒绝）；route 解析（未知 id → 不存在页）；2 个渲染器按 config 渲染与调用。
- smoke：构建产物功能数不减少。

## 11. 明确不做（YAGNI / 防过度）

- 不为每个新 app 生成新 Vue 页代码。
- 不把所有功能塞进一个页面。
- 不用 title 关键词直接决定路由。
- 不让工厂覆盖 base 注册表或人工配置。
- 不在无 schema 校验下自动部署。
- 不把 ability 当作完整业务分类体系（它只是 v1 渲染器层）。

