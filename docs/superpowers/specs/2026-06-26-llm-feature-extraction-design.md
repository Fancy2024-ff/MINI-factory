# 功能拆分智能化 — LLM 驱动拆分器 + FeatureSpec 契约（Claude B↔C 接口）

日期：2026-06-26
作者：Claude B（功能拆分）
状态：设计待审

## 1. 背景与目标

**问题**：当前 [core/opportunity/feature_extraction.py](../../../core/opportunity/feature_extraction.py) 的
`_DOABLE_FEATURES` 是 14 个预设功能的关键词匹配表。App 描述命中关键词就贴预设标签，
App 独特功能拆不出来，产物与原 App 必然对不上。

**目标**：换成用 LLM 对 App 真实信息做语义抽取，动态产出贴合该 App 的**功能规格
（FeatureSpec）**。保留规则版作为 LLM 不可用时的全量 fallback。

**本设计的核心交付**：定义 B↔C 的数据契约 FeatureSpec，并设计 LLM 拆分器。这是接口，
定错全盘返工，所以契约部分已逐字段与现有下游代码核验对齐。

## 2. 关键设计决策（已与协调方确认）

| 决策点 | 选择 | 理由 |
|---|---|---|
| ability_type 枚举 | 抽象语义集（封闭枚举） | LLM 自由抽语义，C 端逐步接入落地 |
| LLM 调用位置 | 独立 enrichment 步骤 | 不污染 runner「不依赖 LLM」主链路 |
| 每 App 功能数 | Top-N 可落地优先（≤5） | 控成本/队列长度，优先可落地 |
| LLM 不可用 fallback | 规则版全量兜底 | 永不断流，产物打 data_source 区分 |
| buildable=false 处理 | 记录但不入队 | 保留市场信号与能力缺口清单，仅入复盘 |
| buildable 语义 | 双布尔（见 §4） | 消解「模板在白名单但 task=pending」矛盾态 |

## 3. FeatureSpec 契约（B↔C 核心接口）

每个拆出的功能是一条 FeatureSpec。字段分三层：语义层（B 产，LLM 抽）、落地层
（C 控，ability_map 判定）、血缘/运营层。

```jsonc
{
  // —— 血缘（继承父 App，B 填）——
  "feature_key": "capcut:auto-captions",   // = "<parent_key>:<slug(feature_name)>"
  "parent_app_key": "capcut",
  "parent_app_name": "CapCut",

  // —— 语义层：LLM 抽取，贴合该 App 真实功能 ——
  "feature_name": "Auto Captions",
  "feature_name_cn": "自动字幕",
  "description": "为上传视频自动识别语音并生成时间轴字幕",
  "ability_type": "video-edit",            // 封闭枚举，见 §4
  "input_modality": ["video"],             // text|image|video|audio|multi-field
  "output_modality": "video",              // text|image|video|audio
  "complexity": "hard",                    // easy|medium|hard
  "extraction_confidence": 0.82,           // LLM 对该功能真实存在的置信度 0~1
                                           // ⚠ 与 opportunity_brief.confidence_score
                                           //   (0~100, 证据充分度) 是两回事，不可互用

  // —— 落地层：ability_map 判定，B 不拍脑袋 ——
  "buildable": false,                      // 能否产出可渲染小程序（见 §4 双布尔）
  "auto_publishable": false,               // 后端 task 是否在 TASK_WHITELIST
  "selected_template": "",                 // buildable=true 才填，来自 ability_map
  "required_capabilities": ["video_asr", "video_render"],  // 抽象能力，非白名单
  "unsupported_reasons": ["缺视频 ASR provider", "长视频转码成本高"],

  // —— 运营层 ——
  "miniapp_fit_score": 35,
  "viral_score": 60,
  "production_recommended": false,         // = buildable && fit 达标（见 §4 门控）
  "reason": ["..."],
  "data_source": "llm"                     // llm | rule_fallback
}
```

### 3.1 与现有代码冲突点的收口（三处必改，已核验）

**修正 1：feature_key 不含 ability_type。**
[processed_apps.py](../../../core/opportunity/processed_apps.py) 的 `is_processed`/`retry_count`
按 feature_key 字符串精确去重。ability_type 来自 LLM、不稳定，放进主键会让去重失效、
对不上历史 processed 记录。
→ `feature_key = "<parent_key>:<slug(feature_name)>"`，ability_type 独立字段。
slug 复用 [feature_registry.py](../../../core/publisher/feature_registry.py) 的实现
（非 ASCII 走稳定哈希兜底），保证同 App 同功能多次抽取 key 恒定。

**修正 2：confidence 改名为 extraction_confidence。**
[opportunity_brief.py](../../../core/opportunity/opportunity_brief.py) 已有
`confidence_score`（0~100，证据充分度），`decide_recommendation` 用它做 ≥60/≥40 门槛。
LLM 的 0~1 置信度同名异义异量纲，误用即全员卡门槛被 skip。
→ 改名 `extraction_confidence`，注释写明不可与 confidence_score 互用。

**修正 3：buildable 门控接入（见 §4）。**

## 4. ability_map：枚举集 + 映射表（C 维护的唯一真源）

新建 [core/opportunity/ability_map.py](../../../core/opportunity/ability_map.py)，B 与 C 都
import，杜绝并行枚举。LLM 只能产下面封闭枚举的 ability_type（超出 = schema 失败 → fallback）。

| ability_type | selected_template | ∈_KNOWN_TEMPLATES | (ability, task) | buildable | auto_publishable |
|---|---|---|---|---|---|
| image-gen | ai-image | ✅ | text2img / generate_image | ✅ | ✅ |
| image-edit | ai-image | ✅ | text2img / generate_image | ✅ | ✅ |
| bg-remove | background-remover | ✅ | img2img / background_remove | ✅ | ✅ |
| watermark-remove | watermark-remover | ✅ | img2img / watermark_remove | ✅ | ✅ |
| avatar-gen | avatar-viral | ✅ | text2img / pending | ✅ | ❌ |
| sticker-gen | sticker-viral | ✅ | text2img / pending | ✅ | ❌ |
| pet-talk | pet-talk-viral | ✅ | text2img / pending | ✅ | ❌ |
| blessing | blessing-video-viral | ✅ | text2img / pending | ✅ | ❌ |
| funny-video | funny-video-viral | ✅ | text2img / pending | ✅ | ❌ |
| text-gen | ai-tool | ✅ | text2img / pending | ✅ | ❌ |
| video-edit | "" | — | — | ❌ | ❌ |
| audio-edit | "" | — | — | ❌ | ❌ |
| realtime-camera | "" | — | — | ❌ | ❌ |
| 3d-ar | "" | — | — | ❌ | ❌ |
| multi-step | "" | — | — | ❌ | ❌ |

对齐核验：所有 buildable=true 的 selected_template 均 ∈
[classifier._KNOWN_TEMPLATES](../../../core/opportunity/classifier.py)；(ability, task) 与
`_TEMPLATE_ABILITY_TASK` 一致；task 白名单与
[feature_registry.TASK_WHITELIST](../../../core/publisher/feature_registry.py) 一致。

### 4.1 双布尔语义（消解矛盾态）

avatar/sticker 等模板在 `_KNOWN_TEMPLATES`（能渲染壳），但 task=pending，而
`TASK_WHITELIST` 只认 {generate_image, background_remove, watermark_remove}，
`validate_feature` 会拒绝 pending 自动上线。单布尔会出现「判 true 进队列 → 生成成功 →
registry 拒绝上线」的断裂（正是 Claude D 业务 QA 要拦的假绿灯）。故拆两层：

- **buildable**（= buildable_skeleton）：能否产出可渲染小程序（模板 ∈ _KNOWN_TEMPLATES）。
  avatar 类 = true，入队是对的。
- **auto_publishable**（= buildable_live）：后端 task 是否 ∈ TASK_WHITELIST，名副其实可自动
  上线。pending 的 = false，入队但标 `review_required`，走人工，不自动上线。

### 4.2 门控接入方案（无歧义）

过滤链有两道独立闸门：
- 闸门 A（[ranking.py:63,136](../../../core/opportunity/ranking.py)）：`production_recommended=false`
  的 feature 不进 `rank_features`，连分都不打。
- 闸门 B（[opportunity_queue.py:65](../../../core/opportunity/opportunity_queue.py)）：
  `recommendation=="skip"` 的不入队。`decide_recommendation` 只看 final_score+confidence_score，
  不知道 buildable。

**接法：buildable 在闸门 A 源头掐断，不留给闸门 B。**

```
production_recommended := buildable AND (miniapp_fit_score >= fit_threshold)
```

理由：production_recommended=false 在 ranking.py:136 直接跳过 → 该 feature 不进 ranked →
不会生成 brief（briefs 只对 ranked 生成，见 crawl_runner.py:257）→ decide_recommendation
永远看不到它。「final_score 高却判 produce」的矛盾路径根本走不到。decide_recommendation
无需改、无需接 buildable——最小且无矛盾。与现有 `_HARD_FEATURES`（本就
production_recommended=False）走同一既有路径，零新增分支。

auto_publishable=false 不影响入队（buildable 类照常入队），它在 brief/queue 层标
review_required，由现有人工闸门兜住后端上线。

## 5. 拆分器架构

模块结构（方案 A 独立模块 + C 两阶段语义）：

- **ability_map.py**（新建）：ABILITY_TYPES 枚举 + 映射表，C 维护的唯一真源。
- **feature_extraction_llm.py**（新建）：LLM 抽取器。注入 App 真实
  name/description/features/category → 强制 JSON schema 输出功能列表 → schema 严格校验
  → 经 ability_map 回填落地层 → Top-N（buildable 优先，≤5）。
- **feature_extraction.py**（改）：`extract_all(candidates, enrich=False)` 改为门面。
  enrich=True 走 LLM；任何失败（超时/不可用/schema 失败）整体回退现有规则版；产物打
  data_source。签名向后兼容，[crawl_runner.py:247](../../../core/opportunity/crawl_runner.py)
  无需改动。
- **调用位置**：独立 enrichment 开关，crawl 主链路仍产规则版候选，enrich 作为可开关步骤，
  不破坏 runner「不依赖 LLM」约定。

LLM 接入：复用 [core/integrations/llm.py](../../../core/integrations/llm.py) `get_llm()`
（最新 Claude 模型）。稳定性：超时（默认 30s）+ 重试（2 次）+ pydantic schema 严格校验，
脏数据不进队列；每 App 一次调用，按 canonical_key 缓存避免重复花钱。

## 6. 验证（§5 任务）

用真实复杂 App 端到端测：
- **CapCut**：应拆出 视频剪辑(video-edit, buildable=false) / 自动字幕(video-edit, false) /
  背景去除(bg-remove, true+auto_publishable) / 头像(avatar-gen, buildable=true,
  auto_publishable=false)。
- **Notion**：text-gen / multi-step(false)。

断言：
1. 拆出功能贴合 App 真实、非千篇一律的 14 个。
2. buildable=false 不进 ranked（闸门 A）。
3. avatar 类入队但 auto_publishable=false、标 review_required，不自动上线。
4. LLM 关闭时规则版全量兜底，不断流，data_source=rule_fallback。
5. 同 App 同功能两次抽取 feature_key 恒定（去重不失效）。
6. ability_type 越界 / schema 不合法时整体回退，不产脏数据。

## 7. 不做（YAGNI）

- 不改 decide_recommendation、不改 confidence_score 语义。
- 不新增模板、不改 _KNOWN_TEMPLATES（C 接入新能力时再扩 ability_map）。
- 不为 buildable=false 功能生成模板/PRD（仅复盘记录）。
- 不做无关重构。
