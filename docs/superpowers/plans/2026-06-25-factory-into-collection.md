# 工厂产物增量并入合集 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 点流水线启动后，工厂抓到的新功能作为一条配置追加进 TG 合集（新卡片 + 可用页面），不再用单页 HTML 整站覆盖合集。

**架构：** 增量并入方案。新增 `features.generated.json` 注册表（工厂只 append）+ `featureRegistry.ts`（合并 base 内置 + generated，含校验）；TgHome 在硬编码卡片下方追加渲染 registry 卡片，TgApp/route 支持 `/tg/gen/{id}` 动态路由复用现有 AiImagePage/BgRemovePage 渲染器；`telegram_deploy.py` 改为「写 registry → 构建合集 → 部署整站」，并加部署安全门。修掉 `feature_extraction.py` 的 background_remover 模板错配。

**技术栈：** Python 3.11（pytest）、Vue 3 + TypeScript（vue-tsc / vitest）、Cloudflare Pages（wrangler）。

**范围说明：** 本计划是「增量并入」——现有 5 个页面与 tgPages 测试不动。设计文档 §7 的「全量重构」（迁移 5 页为 base 配置）不在本次范围。task 白名单 v1 仅 `generate_image`、`background_remove`（设计 §5 铁律）。

---

## 文件结构

**Python（工厂侧）**
- 修改 `core/opportunity/feature_extraction.py` — 修 background_remover 模板错配（`ai-image`→`background-remover`）。
- 修改 `core/opportunity/classifier.py` — 新增 `template_to_ability_task(template)` 映射函数（template → ability/task）。
- 新建 `core/publisher/feature_registry.py` — 生成/校验 feature 配置项，append 到 `features.generated.json`（schema + 白名单 + 同 id 跳过）。
- 修改 `core/publisher/telegram_deploy.py` — `deploy_telegram` 改为「生成配置 → validate → append registry → 构建合集 → smoke 检查 → 部署整站」。
- 新建 `core/publisher/tests/test_feature_registry.py` — registry 生成/校验单测。

**前端（合集侧）**
- 新建 `apps/web/src/tg/registry/features.generated.json` — 工厂追加入口（初始 `[]`）。
- 新建 `apps/web/src/tg/registry/featureRegistry.ts` — 加载 + 校验 + 查询（`getGeneratedFeatures()` / `getFeatureById(id)`）。
- 新建 `apps/web/src/tg/GeneratedFeaturePage.vue` — 按 feature.ability 包一层，复用 AiImagePage / BgRemovePage 形态。
- 修改 `apps/web/src/tg/TgHome.vue` — 现有卡片下方 `v-for` 追加 registry 卡片。
- 修改 `apps/web/src/tg/route.ts` — 支持 `/tg/gen/{id}` 路由解析。
- 修改 `apps/web/src/tg/TgApp.vue` — `/tg/gen/{id}` 渲染 GeneratedFeaturePage。
- 新建 `apps/web/src/__tests__/featureRegistry.test.ts` — 校验逻辑 vitest。

数据契约（feature 配置项，base 与 generated 同形）：

```jsonc
{
  "id": "sticker-ly-sticker",        // ^[a-z0-9-]+$，唯一
  "title": "表情包",
  "icon": "😄",
  "ability": "text2img",             // text2img | img2img
  "task": "generate_image",          // 白名单：generate_image | background_remove
  "subtitle": "一句话生成表情贴纸",
  "input": { "imageRequired": false, "textRequired": true },
  "params": { "promptTemplate": "{input}, 表情包贴纸风格", "outputMode": "generated_image" },
  "ui": { "textPlaceholder": "描述你想要的表情", "submitLabel": "生成表情", "resultTitle": "表情包" },
  "source": { "type": "factory", "confidence": 0.86 }
}
```

---

## 任务清单

### 任务 1：修复 feature_extraction 模板错配

**文件：**
- 修改：`core/opportunity/feature_extraction.py:17-19`
- 测试：`core/opportunity/tests/test_feature_extraction.py`（若不存在则创建）

- [ ] **步骤 1：编写失败的测试**

创建/追加 `core/opportunity/tests/test_feature_extraction.py`：

```python
from core.opportunity.feature_extraction import extract_features


def test_background_remover_maps_to_background_remover_template():
    candidate = {
        "canonical_key": "app_store:com.x.sticker",
        "name": "Sticker Maker",
        "description": "background remover and cutout tool",
        "features": ["background remover"],
    }
    feats = extract_features(candidate)
    bg = [f for f in feats if "background" in f["feature_name"].lower()]
    assert bg, "background_remover feature should be extracted"
    assert bg[0]["selected_template"] == "background-remover"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction.py -v`
预期：FAIL，`selected_template == 'ai-image'` 而非 `background-remover`。

- [ ] **步骤 3：修复映射**

`core/opportunity/feature_extraction.py:17-19`，把 `background_remover` 行的 template 由 `"ai-image"` 改为 `"background-remover"`：

```python
    ("background_remover", "Background remover", "背景去除",
     ["background remover", "remove background", "抠图", "背景去除", "cutout"],
     "background-remover", ["image_generation"], "easy", 88, 72),
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_feature_extraction.py -v`
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/feature_extraction.py core/opportunity/tests/test_feature_extraction.py
git commit -m "fix(opportunity): background_remover 映射到 background-remover 模板而非 ai-image

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### 任务 2：classifier 增加 template → ability/task 映射

**文件：**
- 修改：`core/opportunity/classifier.py`（在 `_TEMPLATE_THEME_LABEL` 后追加）
- 测试：`core/opportunity/tests/test_classifier.py`（若不存在则创建）

- [ ] **步骤 1：编写失败的测试**

创建/追加 `core/opportunity/tests/test_classifier.py`：

```python
from core.opportunity.classifier import template_to_ability_task


def test_known_templates_map_to_ability_task():
    assert template_to_ability_task("ai-image") == ("text2img", "generate_image")
    assert template_to_ability_task("background-remover") == ("img2img", "background_remove")


def test_unknown_template_maps_to_pending():
    # 不在 v1 白名单的模板 → text2img + pending（不自动上线）
    assert template_to_ability_task("avatar-viral") == ("text2img", "pending")
    assert template_to_ability_task("nonexistent") == ("text2img", "pending")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_classifier.py -v`
预期：FAIL，`ImportError: cannot import name 'template_to_ability_task'`。

- [ ] **步骤 3：实现映射函数**

`core/opportunity/classifier.py` 末尾追加：

```python
# template -> (ability, task)。ability 决定页面壳，task 决定后端意图。
# v1 白名单 task 只含已验证名副其实的两个；其余落 "pending"（不自动上线）。
_TEMPLATE_ABILITY_TASK = {
    "ai-image": ("text2img", "generate_image"),
    "background-remover": ("img2img", "background_remove"),
}


def template_to_ability_task(template: str) -> tuple[str, str]:
    """把 classifier 选出的 template 映射为合集渲染所需的 (ability, task)。

    不在 v1 白名单的 template -> ("text2img", "pending")：仍可渲染壳，
    但 task=pending 表示后端意图未经验证，registry 校验会拒绝其自动上线。
    """
    return _TEMPLATE_ABILITY_TASK.get(template, ("text2img", "pending"))
```

- [ ] **步骤 4：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/opportunity/tests/test_classifier.py -v`
预期：PASS。

- [ ] **步骤 5：Commit**

```bash
git add core/opportunity/classifier.py core/opportunity/tests/test_classifier.py
git commit -m "feat(opportunity): classifier 增加 template->ability/task 映射(含 pending 兜底)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### 任务 3：feature_registry 生成与校验（Python）

**文件：**
- 新建：`core/publisher/feature_registry.py`
- 测试：`core/publisher/tests/test_feature_registry.py`

- [ ] **步骤 1：编写失败的测试**

创建 `core/publisher/tests/test_feature_registry.py`：

```python
import json
from pathlib import Path

import pytest

from core.publisher.feature_registry import (
    build_feature_config,
    validate_feature,
    append_feature,
    ABILITY_WHITELIST,
    TASK_WHITELIST,
)


def test_build_from_app_and_selection():
    best_app = {"name_cn": "表情包", "description_cn": "一句话生成表情贴纸"}
    selection = {"selected_template": "ai-image", "theme": "image-tool"}
    feat = build_feature_config("app_store:com.x.sticker:sticker", best_app, selection)
    assert feat["id"] == "app-store-com-x-sticker-sticker"
    assert feat["ability"] == "text2img"
    assert feat["task"] == "generate_image"
    assert feat["title"] == "表情包"


def test_validate_rejects_unknown_task():
    feat = {"id": "x", "title": "t", "icon": "🎨", "ability": "img2img",
            "task": "restore", "subtitle": "s", "input": {"imageRequired": True},
            "params": {}, "ui": {"submitLabel": "go"}}
    ok, reason = validate_feature(feat)
    assert ok is False and "task" in reason


def test_validate_rejects_ability_input_mismatch():
    feat = {"id": "x", "title": "t", "icon": "🎨", "ability": "img2img",
            "task": "background_remove", "subtitle": "s",
            "input": {"imageRequired": False}, "params": {}, "ui": {"submitLabel": "go"}}
    ok, reason = validate_feature(feat)
    assert ok is False and "imageRequired" in reason


def test_append_skips_duplicate_id(tmp_path):
    reg = tmp_path / "features.generated.json"
    reg.write_text("[]", encoding="utf-8")
    feat = {"id": "dup", "title": "t", "icon": "🎨", "ability": "text2img",
            "task": "generate_image", "subtitle": "s",
            "input": {"textRequired": True}, "params": {"promptTemplate": "{input}"},
            "ui": {"submitLabel": "go"}}
    assert append_feature(reg, feat) is True
    assert append_feature(reg, feat) is False  # 同 id 跳过
    data = json.loads(reg.read_text(encoding="utf-8"))
    assert len(data) == 1
```

- [ ] **步骤 2：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/publisher/tests/test_feature_registry.py -v`
预期：FAIL，模块不存在。

- [ ] **步骤 3：实现 feature_registry 模块（第 1 段：常量 + slug + build）**

创建 `core/publisher/feature_registry.py`：

```python
"""core.publisher.feature_registry — 工厂产物 → 合集功能配置项。

职责：把抓到的 app + classifier 选择，转成合集 registry 的一条配置，
做 schema/白名单/能力兼容校验，append 到 features.generated.json（同 id 跳过）。
task 白名单是「已用真实后端验证过名副其实」的集合（设计 §5 铁律）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.opportunity.classifier import template_to_ability_task

ABILITY_WHITELIST = {"text2img", "img2img"}
TASK_WHITELIST = {"generate_image", "background_remove"}

_ICON_BY_ABILITY = {"text2img": "🖼", "img2img": "✂️"}


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "feature"


def build_feature_config(feature_key: str, best_app: dict, selection: dict) -> dict:
    """由 feature_key + app + classifier selection 构造一条 feature 配置。"""
    template = selection.get("selected_template", "")
    ability, task = template_to_ability_task(template)
    title = best_app.get("name_cn") or best_app.get("name") or "新功能"
    subtitle = (best_app.get("description_cn") or best_app.get("description") or title)[:40]
    if ability == "img2img":
        inp = {"imageRequired": True, "textRequired": False,
               "acceptedTypes": ["image/png", "image/jpeg", "image/webp"]}
        params = {"task": task, "outputMode": "edited_image"}
        ui = {"uploadLabel": "上传图片", "submitLabel": "开始处理", "resultTitle": title}
    else:
        inp = {"imageRequired": False, "textRequired": True}
        params = {"promptTemplate": "{input}", "outputMode": "generated_image"}
        ui = {"textPlaceholder": "描述你想要的画面", "submitLabel": "立即生成", "resultTitle": title}
    return {
        "id": _slug(feature_key),
        "title": title,
        "icon": _ICON_BY_ABILITY.get(ability, "✨"),
        "ability": ability,
        "task": task,
        "subtitle": subtitle,
        "input": inp,
        "params": params,
        "ui": ui,
        "source": {"type": "factory"},
    }
```

- [ ] **步骤 4：实现 feature_registry 模块（第 2 段：validate + append）**

`core/publisher/feature_registry.py` 末尾追加：

```python
_REQUIRED = ["id", "title", "icon", "ability", "task", "subtitle", "input", "params", "ui"]


def validate_feature(feat: dict) -> tuple[bool, str]:
    """校验一条 feature 配置。返回 (ok, reason)。reason 为空表示通过。"""
    for k in _REQUIRED:
        if k not in feat or feat[k] in (None, ""):
            return False, f"missing field: {k}"
    if not re.fullmatch(r"[a-z0-9-]+", feat["id"]):
        return False, "id not url-safe"
    if feat["ability"] not in ABILITY_WHITELIST:
        return False, f"ability not in whitelist: {feat['ability']}"
    if feat["task"] not in TASK_WHITELIST:
        return False, f"task not in whitelist: {feat['task']}"
    if not feat.get("ui", {}).get("submitLabel"):
        return False, "missing ui.submitLabel"
    inp = feat.get("input", {})
    if feat["ability"] == "img2img" and not inp.get("imageRequired"):
        return False, "img2img requires input.imageRequired=true"
    if feat["ability"] == "text2img" and not inp.get("textRequired"):
        return False, "text2img requires input.textRequired=true"
    return True, ""


def append_feature(registry_path: Path, feat: dict) -> bool:
    """append 一条 feature 到 generated registry。同 id 已存在则跳过返回 False。"""
    registry_path = Path(registry_path)
    if registry_path.exists():
        data = json.loads(registry_path.read_text(encoding="utf-8") or "[]")
    else:
        data = []
    if any(f.get("id") == feat["id"] for f in data):
        return False
    data.append(feat)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
```

- [ ] **步骤 5：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/publisher/tests/test_feature_registry.py -v`
预期：PASS（4 个用例）。

- [ ] **步骤 6：Commit**

```bash
git add core/publisher/feature_registry.py core/publisher/tests/test_feature_registry.py
git commit -m "feat(publisher): feature_registry 生成/校验(schema+白名单+能力兼容+同id跳过)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### 任务 4：前端 featureRegistry.ts + generated.json

**文件：**
- 新建：`apps/web/src/tg/registry/features.generated.json`（内容 `[]`）
- 新建：`apps/web/src/tg/registry/featureRegistry.ts`
- 测试：`apps/web/src/__tests__/featureRegistry.test.ts`

- [ ] **步骤 1：创建空 generated 注册表**

创建 `apps/web/src/tg/registry/features.generated.json`：

```json
[]
```

- [ ] **步骤 2：编写失败的测试**

创建 `apps/web/src/__tests__/featureRegistry.test.ts`：

```typescript
import { describe, it, expect } from 'vitest'
import { validateFeature, type FeatureConfig } from '../tg/registry/featureRegistry'

const base: FeatureConfig = {
  id: 'demo', title: '演示', icon: '🖼', ability: 'text2img',
  task: 'generate_image', subtitle: 's',
  input: { textRequired: true }, params: { promptTemplate: '{input}' },
  ui: { submitLabel: 'go' },
}

describe('validateFeature', () => {
  it('accepts a well-formed text2img feature', () => {
    expect(validateFeature(base).ok).toBe(true)
  })
  it('rejects task not in whitelist', () => {
    expect(validateFeature({ ...base, task: 'restore' as any }).ok).toBe(false)
  })
  it('rejects img2img without imageRequired', () => {
    const f = { ...base, ability: 'img2img' as const, task: 'background_remove' as const,
                input: { imageRequired: false } }
    expect(validateFeature(f).ok).toBe(false)
  })
})
```

- [ ] **步骤 3：运行测试验证失败**

运行：`cd apps/web && npx vitest run src/__tests__/featureRegistry.test.ts`
预期：FAIL，模块不存在。

- [ ] **步骤 4：实现 featureRegistry.ts**

创建 `apps/web/src/tg/registry/featureRegistry.ts`：

```typescript
import generated from './features.generated.json'

export type Ability = 'text2img' | 'img2img'
export type Task = 'generate_image' | 'background_remove'

export interface FeatureConfig {
  id: string
  title: string
  icon: string
  ability: Ability
  task: Task
  subtitle: string
  input: { imageRequired?: boolean; textRequired?: boolean; acceptedTypes?: string[] }
  params: { promptTemplate?: string; task?: string; outputMode?: string }
  ui: { textPlaceholder?: string; uploadLabel?: string; submitLabel: string; resultTitle?: string }
  source?: { type?: string; confidence?: number }
}

const ABILITY_WHITELIST = new Set<string>(['text2img', 'img2img'])
const TASK_WHITELIST = new Set<string>(['generate_image', 'background_remove'])

export function validateFeature(f: FeatureConfig): { ok: boolean; reason: string } {
  if (!f || !/^[a-z0-9-]+$/.test(f.id || '')) return { ok: false, reason: 'id not url-safe' }
  for (const k of ['title', 'icon', 'ability', 'task', 'subtitle'] as const) {
    if (!f[k]) return { ok: false, reason: `missing ${k}` }
  }
  if (!ABILITY_WHITELIST.has(f.ability)) return { ok: false, reason: 'ability' }
  if (!TASK_WHITELIST.has(f.task)) return { ok: false, reason: 'task' }
  if (!f.ui?.submitLabel) return { ok: false, reason: 'ui.submitLabel' }
  if (f.ability === 'img2img' && !f.input?.imageRequired) return { ok: false, reason: 'imageRequired' }
  if (f.ability === 'text2img' && !f.input?.textRequired) return { ok: false, reason: 'textRequired' }
  return { ok: true, reason: '' }
}

// 加载时过滤掉非法项，保证 UI 只见合法 feature（坏项不致整页崩）。
const _valid: FeatureConfig[] = (generated as FeatureConfig[]).filter(
  (f) => validateFeature(f).ok,
)

export function getGeneratedFeatures(): FeatureConfig[] {
  return _valid
}

export function getFeatureById(id: string): FeatureConfig | undefined {
  return _valid.find((f) => f.id === id)
}
```

- [ ] **步骤 5：运行测试验证通过**

运行：`cd apps/web && npx vitest run src/__tests__/featureRegistry.test.ts`
预期：PASS（3 个用例）。

- [ ] **步骤 6：类型检查 + Commit**

运行：`cd apps/web && npx vue-tsc -b`，预期 EXIT 0。

```bash
git add apps/web/src/tg/registry/ apps/web/src/__tests__/featureRegistry.test.ts
git commit -m "feat(tg): 合集功能注册表 featureRegistry(generated.json + 加载期校验)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### 任务 5：GeneratedFeaturePage 渲染器组件

**文件：**
- 新建：`apps/web/src/tg/GeneratedFeaturePage.vue`

复用 tgApi 的真实后端调用：text2img → `generateImage`，img2img → `editImage`。这是「真正能用」的保证——不是换皮，而是按 ability 走真实端点。

- [ ] **步骤 1：实现组件模板 + 脚本（第 1 段：template）**

创建 `apps/web/src/tg/GeneratedFeaturePage.vue`：

```vue
<!-- /tg/gen/{id}：工厂生成功能的通用渲染器。按 feature.ability 走真实后端。 -->
<template>
  <div class="page">
    <header class="top">
      <button class="back" @click="goHome">←</button>
      <div class="top-title">{{ feature?.title || '功能' }}</div>
      <div class="top-spacer"></div>
    </header>

    <section v-if="!feature" class="form">
      <div class="error-box"><div class="error-msg">功能不存在</div></div>
      <button class="generate-btn" @click="goHome">← 返回首页</button>
    </section>

    <section v-else-if="phase !== 'result'" class="form">
      <template v-if="feature.ability === 'img2img'">
        <label class="field-label">{{ feature.ui.uploadLabel || '上传图片' }}</label>
        <div class="uploader" :class="{ 'has-img': !!sourcePreview }" @click="pickFile">
          <img v-if="sourcePreview" :src="sourcePreview" class="src-preview" alt="原图" />
          <div v-else class="uploader-hint"><div class="up-icon">⬆️</div><div>点击选择图片</div></div>
        </div>
        <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp"
               class="file-hidden" @change="onFileChange" />
      </template>
      <template v-else>
        <label class="field-label">{{ feature.ui.textPlaceholder || '描述你想要的画面' }}</label>
        <textarea class="prompt-input" v-model="prompt" :maxlength="MAX_PROMPT_LEN"
                  :placeholder="feature.ui.textPlaceholder" rows="3"></textarea>
      </template>
      <button class="generate-btn" :disabled="phase === 'loading' || !canSubmit" @click="onSubmit">
        <span v-if="phase === 'loading'">生成中…</span>
        <span v-else>✨ {{ feature.ui.submitLabel }}</span>
      </button>
      <div v-if="phase === 'error'" class="error-box"><div class="error-msg">{{ errorMsg }}</div></div>
    </section>

    <section v-if="phase === 'loading'" class="loading">
      <div class="spinner"></div><div class="loading-text">正在处理，请稍候…</div>
    </section>

    <section v-if="phase === 'result' && display" class="result">
      <div class="result-card"><img class="result-img" :src="display.src" :alt="display.title" /></div>
      <button class="generate-btn" @click="backToForm">🔄 再来一次</button>
    </section>
  </div>
</template>
```

- [ ] **步骤 2：实现组件脚本（第 2 段：script）**

接着同一文件追加：

```vue
<script setup lang="ts">
import { ref, computed } from 'vue'
import { generateImage, editImage, toDisplayImage, MAX_PROMPT_LEN,
         runUntilImage } from './tgApi'
import { getFeatureById, type FeatureConfig } from './registry/featureRegistry'
import type { DisplayImage } from './types'

const props = defineProps<{ featureId: string }>()
const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

const feature = computed<FeatureConfig | undefined>(() => getFeatureById(props.featureId))
type Phase = 'form' | 'loading' | 'result' | 'error'
const phase = ref<Phase>('form')
const errorMsg = ref('')
const display = ref<DisplayImage | null>(null)
const prompt = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const sourceFile = ref<Blob | null>(null)
const sourcePreview = ref('')

const canSubmit = computed(() =>
  feature.value?.ability === 'img2img' ? !!sourceFile.value : !!prompt.value.trim())

function pickFile() { fileInput.value?.click() }
function onFileChange(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  sourceFile.value = f
  sourcePreview.value = URL.createObjectURL(f)
}

async function onSubmit() {
  if (!feature.value || !canSubmit.value) return
  phase.value = 'loading'; errorMsg.value = ''
  const f = feature.value
  const outcome = await runUntilImage(
    () => f.ability === 'img2img'
      ? editImage(sourceFile.value!, { task: f.params.task || f.task })
      : generateImage({ prompt: (f.params.promptTemplate || '{input}').replace('{input}', prompt.value), template_id: 'ai-image', style: '', aspect_ratio: '1:1' }),
    (r) => toDisplayImage(r),
    () => phase.value === 'loading',
  )
  if (outcome.kind === 'ok') { display.value = outcome.display; phase.value = 'result' }
  else if (outcome.kind === 'fatal') { errorMsg.value = outcome.message; phase.value = 'error' }
  else { errorMsg.value = '稍后再试'; phase.value = 'error' }
}

function backToForm() { phase.value = 'form'; display.value = null }
function goHome() { emit('navigate', '/tg') }
defineExpose({ feature, phase, onSubmit })
</script>
```

> 注：样式可复用现有页结构。最小可用：从 `BgRemovePage.vue` 拷贝 `<style scoped>` 块到本文件（同样的 .page/.top/.uploader/.generate-btn/.result 类名），保证视觉一致。

- [ ] **步骤 3：拷贝样式块**

把 `apps/web/src/tg/BgRemovePage.vue` 的整个 `<style scoped>...</style>` 块复制到 `GeneratedFeaturePage.vue` 末尾（类名已对齐）。

- [ ] **步骤 4：类型检查**

运行：`cd apps/web && npx vue-tsc -b`
预期：EXIT 0。若报 `generateImage` 入参类型不符，核对 `GenerateImageRequest`（types.ts）字段名后修正调用。

- [ ] **步骤 5：Commit**

```bash
git add apps/web/src/tg/GeneratedFeaturePage.vue
git commit -m "feat(tg): GeneratedFeaturePage 通用渲染器(按 ability 走真实后端)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### 任务 6：TgHome 追加卡片 + 路由接入

**文件：**
- 修改：`apps/web/src/tg/TgHome.vue`
- 修改：`apps/web/src/tg/route.ts`
- 修改：`apps/web/src/tg/TgApp.vue`

- [ ] **步骤 1：route.ts 支持 /tg/gen/{id}**

`apps/web/src/tg/route.ts`，在 `normalizeRoute` 的已有判断后、`return '/tg'` 前插入动态前缀放行（保持原有 5 条精确路由不变）：

```typescript
  if (p.startsWith('/tg/gen/')) return p as TgRoute
```

并把 `TgRoute` 类型放宽以容纳动态串（在 union 末尾追加）：

```typescript
  | `/tg/gen/${string}`
```

- [ ] **步骤 2：TgHome 现有卡片下方追加 registry 卡片**

`apps/web/src/tg/TgHome.vue`，在 `upcoming` 的 `v-for` 之前插入 generated 卡片循环：

```vue
      <button
        v-for="f in generatedFeatures"
        :key="f.id"
        class="card card-open"
        @click="emit('navigate', '/tg/gen/' + f.id)"
      >
        <div class="card-icon">{{ f.icon }}</div>
        <div class="card-body">
          <div class="card-title">{{ f.title }}</div>
          <div class="card-desc">{{ f.subtitle }}</div>
        </div>
        <div class="badge badge-new">新上线</div>
      </button>
```

并在 `<script setup>` 顶部引入：

```typescript
import { getGeneratedFeatures } from './registry/featureRegistry'
const generatedFeatures = getGeneratedFeatures()
```

- [ ] **步骤 3：TgApp 渲染 /tg/gen/{id}**

`apps/web/src/tg/TgApp.vue`，在 `<BgRemovePage ... />` 行后、`<TgHome v-else .../>` 前插入：

```vue
    <GeneratedFeaturePage
      v-else-if="route.startsWith('/tg/gen/')"
      :feature-id="route.replace('/tg/gen/', '')"
      @navigate="navigate"
    />
```

并 import：

```typescript
import GeneratedFeaturePage from './GeneratedFeaturePage.vue'
```

- [ ] **步骤 4：类型检查 + 现有测试不回归**

运行：`cd apps/web && npx vue-tsc -b && npx vitest run src/__tests__/tgPages.test.ts`
预期：EXIT 0，tgPages 全部 PASS（现有 5 页与卡片断言不受影响）。

- [ ] **步骤 5：Commit**

```bash
git add apps/web/src/tg/TgHome.vue apps/web/src/tg/route.ts apps/web/src/tg/TgApp.vue
git commit -m "feat(tg): TgHome 追加 registry 卡片 + /tg/gen/{id} 动态路由

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### 任务 7：telegram_deploy 改为「写注册表 → 构建合集 → 部署整站」

这是根治覆盖问题的核心。`deploy_telegram` 不再渲染单 HTML，而是把新功能 append 到合集 registry、构建合集、过安全门后部署整站。

**文件：**
- 修改：`core/publisher/telegram_deploy.py`（`deploy_telegram` 函数体；新增 helper）
- 测试：`core/publisher/tests/test_telegram_deploy.py`（已存在，追加用例）

- [ ] **步骤 1：新增路径常量与合集构建 helper（第 1 段）**

`core/publisher/telegram_deploy.py`，在 `TEMPLATE_DIR`/`DATA_DIR` 附近追加：

```python
WEB_APP_DIR = PROJECT_ROOT / "apps" / "web"
GENERATED_REGISTRY = WEB_APP_DIR / "src" / "tg" / "registry" / "features.generated.json"
WEB_DIST_DIR = WEB_APP_DIR / "dist"
```

- [ ] **步骤 2：新增 build_collection helper（第 2 段）**

`telegram_deploy.py` 追加（npx 解析沿用 deploy_to_cloudflare 里的写法）：

```python
def build_collection() -> None:
    """构建合集前端（npm run build）。失败抛 RuntimeError。"""
    import shutil
    import subprocess
    npx = shutil.which("npm") or "npm"
    result = subprocess.run(
        [npx, "run", "build"],
        cwd=str(WEB_APP_DIR),
        capture_output=True, text=True, timeout=300,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"collection build failed: {result.stderr or result.stdout}")


def count_registry_features() -> int:
    """generated registry 当前条数（部署安全门用）。"""
    if not GENERATED_REGISTRY.exists():
        return 0
    try:
        return len(json.loads(GENERATED_REGISTRY.read_text(encoding="utf-8") or "[]"))
    except Exception:
        return 0


def deploy_to_cloudflare_dir(dist_dir: Path) -> str:
    """部署一个已构建好的目录（合集 dist）到 Cloudflare Pages 生产分支。

    与 deploy_to_cloudflare(html) 区别：直接部署整站目录，不写临时单页。
    """
    import shutil
    import subprocess
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = CLOUDFLARE_API_TOKEN
    if CLOUDFLARE_ACCOUNT_ID:
        env["CLOUDFLARE_ACCOUNT_ID"] = CLOUDFLARE_ACCOUNT_ID
    cmd = [npx, "wrangler", "pages", "deploy", str(dist_dir),
           "--project-name", CLOUDFLARE_PROJECT_NAME,
           "--branch", CLOUDFLARE_PAGES_BRANCH, "--commit-dirty=true"]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env,
                            timeout=180, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"wrangler deploy failed: {result.stderr or result.stdout}")
    production_url = f"https://{CLOUDFLARE_PROJECT_NAME}.pages.dev"
    print(f"  [Cloudflare] Production: {production_url}")
    return production_url
```

- [ ] **步骤 3：编写失败的测试（registry append + skip 非白名单）**

`core/publisher/tests/test_telegram_deploy.py` 追加：

```python
def test_deploy_appends_to_registry_when_task_valid(tmp_path, monkeypatch):
    import core.publisher.telegram_deploy as td
    import core.publisher.feature_registry as fr
    reg = tmp_path / "features.generated.json"
    reg.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(td, "GENERATED_REGISTRY", reg)
    # 桩掉真实构建与部署，只验证 registry 合并逻辑
    monkeypatch.setattr(td, "build_collection", lambda: None)
    monkeypatch.setattr(td, "deploy_to_cloudflare", lambda *a, **k: "https://x.pages.dev")
    monkeypatch.setattr(td, "setup_telegram_bot", lambda *a, **k: {"bot_link": "t.me/x", "menu_button_set": True})
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    out = tmp_path / "job"
    out.mkdir()
    (out / "candidate.json").write_text('{"name_cn":"表情包"}', encoding="utf-8")
    (out / "template-selection.json").write_text('{"selected_template":"ai-image"}', encoding="utf-8")
    res = td.deploy_telegram("job-1", out, {"name_cn": "表情包"}, {"target_platforms": ["telegram"]})
    import json as _j
    data = _j.loads(reg.read_text(encoding="utf-8"))
    assert any(f["title"] == "表情包" for f in data)
    assert res["status"] in ("deployed", "partial")
```

- [ ] **步骤 4：运行测试验证失败**

运行：`.venv/bin/python -m pytest core/publisher/tests/test_telegram_deploy.py::test_deploy_appends_to_registry_when_task_valid -v`
预期：FAIL（deploy_telegram 仍是旧单页逻辑，registry 不会被写）。

- [ ] **步骤 5：重写 deploy_telegram 函数体（第 1 段：配置校验 + 生成 feature）**

替换 `deploy_telegram`（`core/publisher/telegram_deploy.py:296` 起）的函数体为：

```python
def deploy_telegram(job_id: str, output_dir: Path, app_info: dict, opportunity: dict) -> dict:
    """把工厂产物作为一条 feature 并入合集并部署整站（不再单页覆盖）。"""
    print(f"\n  [TG Deploy] 并入合集模式：生成 feature 配置...")

    # 凭据校验：部署整站需要 CF token + bot token；后端公网入口用于 img2img。
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not CLOUDFLARE_API_TOKEN:
        missing.append("CLOUDFLARE_API_TOKEN")
    if not WEBAPP_BACKEND_URL:
        missing.append("WEBAPP_BACKEND_URL")
    if missing:
        return {"status": "skipped", "reason": f"Missing config: {', '.join(missing)}",
                "automated": False}

    from core.publisher.feature_registry import (
        build_feature_config, validate_feature, append_feature)

    # 读 classifier 选择，构造 feature 配置
    sel_path = output_dir / "template-selection.json"
    selection = json.loads(sel_path.read_text(encoding="utf-8")) if sel_path.exists() else {}
    feature_key = opportunity.get("feature_key") or app_info.get("feature_key") \
        or app_info.get("name_cn") or job_id
    feat = build_feature_config(feature_key, app_info, selection)

    ok, reason = validate_feature(feat)
    if not ok:
        # task 不在白名单（如 pending）或 schema 不合规 → 不上线，进 pending 报告
        return {"status": "pending", "reason": f"feature 未通过校验，未上线: {reason}",
                "feature": feat, "automated": True}
```

- [ ] **步骤 6：重写 deploy_telegram 函数体（第 2 段：append + 安全门 + 构建部署）**

紧接上面，继续函数体：

```python
    before = count_registry_features()
    appended = append_feature(GENERATED_REGISTRY, feat)
    if not appended:
        print(f"  [TG Deploy] feature 已存在（id={feat['id']}），跳过 append")

    # 构建合集
    print(f"  [TG Deploy] 构建合集...")
    try:
        build_collection()
    except Exception as e:
        return {"status": "failed", "stage": "build", "error": str(e), "automated": True}

    # 安全门：构建产物存在 + registry 条数不减少（旧功能不丢）
    after = count_registry_features()
    if not WEB_DIST_DIR.exists() or after < before:
        return {"status": "failed", "stage": "smoke",
                "error": f"安全门失败 dist={WEB_DIST_DIR.exists()} before={before} after={after}",
                "automated": True}

    # 部署整站 dist（不是单页）
    print(f"  [TG Deploy] 部署合集整站到 Cloudflare...")
    try:
        webapp_url = deploy_to_cloudflare_dir(WEB_DIST_DIR)
    except Exception as e:
        return {"status": "failed", "stage": "cloudflare_deploy", "error": str(e),
                "automated": True}

    # 配置 Bot 菜单按钮指向合集首页 /tg
    try:
        tg_result = setup_telegram_bot(TELEGRAM_WEBAPP_URL or (webapp_url.rstrip("/") + "/tg"),
                                       app_info.get("name_cn", "合集"))
    except Exception as e:
        return {"status": "partial", "stage": "telegram_config", "error": str(e),
                "webapp_url": webapp_url, "automated": True}

    result = {"status": "deployed", "automated": True, "platform": "telegram",
              "job_id": job_id, "feature_id": feat["id"], "feature_title": feat["title"],
              "webapp_url": webapp_url, "bot_link": tg_result.get("bot_link", ""),
              "deployed_at": datetime.now().isoformat()}
    (output_dir / "telegram-deploy.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
```

- [ ] **步骤 7：运行测试验证通过**

运行：`.venv/bin/python -m pytest core/publisher/tests/test_telegram_deploy.py -v`
预期：新用例 PASS；其余既有用例不回归（若旧用例断言单页渲染/`render_image_template`，按新语义更新或标记 legacy）。

- [ ] **步骤 8：清理旧单页路径**

删除/弃用不再使用的 `render_image_template`、`render_template`、`put_cloudflare_secrets` 调用链与 `is_image`/`TELEGRAM_WEBAPP_KIND` 分支（保留函数定义但不再被 deploy_telegram 调用即可，避免误删被测试引用的符号）。`__main__` standalone 块改为调用新的 `deploy_telegram` 流程。

- [ ] **步骤 9：Commit**

```bash
git add core/publisher/telegram_deploy.py core/publisher/tests/test_telegram_deploy.py
git commit -m "feat(publisher): TG 部署改为并入合集(写注册表+构建+安全门+部署整站)

不再用单页 HTML 整站覆盖合集；新功能作为 feature 配置 append 进 registry。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### 任务 8：端到端验证 + 恢复合集

**文件：** 无（验证 + 运行）

- [ ] **步骤 1：全量测试**

```bash
.venv/bin/python -m pytest core -q
cd apps/web && npx vitest run && npx vue-tsc -b
```
预期：全 PASS，类型检查 EXIT 0。

- [ ] **步骤 2：本地构建合集确认 registry 卡片渲染**

```bash
cd apps/web && npm run build
```
预期：build 成功。`dist/` 生成。手动塞一条样例进 `features.generated.json`（text2img），重新 build，确认产物中包含该卡片逻辑（grep dist 资源或本地 preview）。验证后清空为 `[]`。

- [ ] **步骤 3：触发一次真实 auto pipeline（worker 需带 WEBAPP_BACKEND_URL/CF token 环境）**

```bash
curl -s -X POST http://localhost:8000/api/pipeline/start -H "Content-Type: application/json" \
  -d '{"mode":"auto","regions":"CN","platforms":"app_store","limit":3,"max_generate":1}'
```
监控任务到终态，检查 `data/outputs/<job>/telegram-deploy.json` 的 status：
- `deployed` → 新功能已并入合集
- `pending` → task 非白名单（如 restore），未上线（符合设计铁律）

- [ ] **步骤 4：验证线上合集未被覆盖、新增卡片可点**

```bash
curl -s https://miniforge-app.pages.dev/ | grep -oE '<title>[^<]*</title>|/assets/[^"]*\.js'
```
预期：仍是合集 SPA（有 `/assets/*.js` bundle），不是单页。`/tg/gen/{id}` 能打开新功能页并真实出图。

- [ ] **步骤 5：最终 commit（如有 registry/产物变更）**

```bash
git add -A
git commit -m "chore: 工厂并入合集端到端验证通过

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 验收标准

- 点「一键抓取并生产」后，新功能作为一张新卡片出现在合集首页，不覆盖既有功能。
- 命中 v1 白名单（generate_image / background_remove）的功能真实可用；非白名单进 pending 不上线。
- 线上 `miniforge-app.pages.dev` 始终是合集 SPA，部署安全门保证旧功能数不减少。
- 全量测试通过，类型检查 EXIT 0。











