"""core.generator.codegen — 小程序代码生成（唯一执行真源 · Python）。

架构决策（最终版）：
  miniapp 代码生成的**唯一执行真源 = 本模块**（core.generator.codegen）。
  - 主链路（apps/api → core/pipeline/runner.py）只调用 generate_miniapp()，
    runner 不再自己 re-author 任何生成逻辑。
  - 模板事实源 = core/generator/src/templates（base + ai-* + *-viral）。
  - Node 侧 core/generator/src/codegen/page-builder.ts 退化为「同规则的
    parity/兼容壳」，仅供 Node 生态/测试使用，不在主链路执行；其 token 契约、
    模板选择规则必须与本模块保持一致（见 page-builder.ts 顶部说明）。

generate_miniapp 做四件事：
  1. 复制 base 模板（完整可构建骨架）
  2. 叠加题材模板 overlay（avatar-viral / sticker-viral / pet-talk-viral 等）
  3. 数据注入（token 契约 __APP_NAME__ 等）
  4. 写 App 相关非骨架内容（package.json 元信息、manifest/pages 标题、docs 文案）

新增页面/改骨架/加模板 → 改 core/generator/src/templates，不要改这里的正文。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

# token 契约（与 Node page-builder.ts 共享，必须一致）
TOKEN_APP_NAME = "__APP_NAME__"
TOKEN_APP_SUBTITLE = "__APP_SUBTITLE__"
TOKEN_APP_FEATURES_JSON = "__APP_FEATURES_JSON__"
TOKEN_APP_FEATURE_TITLE = "__APP_FEATURE_TITLE__"
TOKEN_APP_TEMPLATE = "__APP_TEMPLATE__"

TEMPLATES_DIR = Path(__file__).resolve().parent / "src" / "templates"


def _write(path: Path, content: str) -> None:
    """写文件。.md 用 utf-8-sig（Windows 友好），其余 utf-8（JSON/TS/Vue 不能带 BOM）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if path.suffix == ".md" else "utf-8"
    with open(path, "w", encoding=encoding) as f:
        f.write(content)


def generate_miniapp(app: dict, prd_json: dict, output_dir: Path, template: str = "ai-tool") -> tuple[Path, dict]:
    """生成 uni-app 小程序项目。返回 (miniapp_dir, gen_source)。"""
    miniapp_dir = output_dir / "miniapp"
    base_template = TEMPLATES_DIR / "base"

    gen_source = {
        "source": "core.generator.codegen",
        "template": "base",
        "fallback_used": False,
        "generated_files_count": 0,
    }

    # --- 1. 复制 base 模板（唯一骨架源）---
    if not (base_template.exists() and (base_template / "package.json").exists()):
        raise FileNotFoundError(
            f"canonical base 模板缺失: {base_template}\n"
            f"miniapp generation 单一事实源不可用，已中止生成。"
        )
    if miniapp_dir.exists():
        shutil.rmtree(str(miniapp_dir))
    shutil.copytree(str(base_template), str(miniapp_dir))

    # --- 1b. 叠加题材模板 overlay ---
    overlay_applied = "base"
    if template and template != "base":
        overlay_dir = TEMPLATES_DIR / template
        if overlay_dir.exists():
            shutil.copytree(str(overlay_dir), str(miniapp_dir), dirs_exist_ok=True)
            overlay_applied = template
        else:
            gen_source["fallback_used"] = True
    gen_source["template"] = overlay_applied

    src_dir = miniapp_dir / "src"
    docs_dir = miniapp_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    app_name = app["name_cn"]
    app_name_en = app["name"].lower().replace(" ", "-")
    features_cn = app.get("features_cn") or []
    feature_title = features_cn[0] if features_cn else "功能"

    # --- 2. token 注入 ---
    tokens = {
        TOKEN_APP_NAME: app_name,
        TOKEN_APP_SUBTITLE: app["description_cn"][:40],
        TOKEN_APP_FEATURES_JSON: json.dumps(features_cn, ensure_ascii=False),
        TOKEN_APP_FEATURE_TITLE: feature_title,
        TOKEN_APP_TEMPLATE: overlay_applied,
    }
    # index/form 填展示类 token；config/template.ts 填模板标识 token。
    for rel in (
        "src/pages/index/index.vue",
        "src/pages/form/form.vue",
        "src/config/template.ts",
    ):
        f = miniapp_dir / rel
        if f.exists():
            text = f.read_text(encoding="utf-8")
            for k, v in tokens.items():
                text = text.replace(k, v)
            _write(f, text)

    # --- 3a. package.json：deps/scripts 来自模板，仅覆盖 App 元信息 ---
    pkg = json.loads((base_template / "package.json").read_text(encoding="utf-8-sig"))
    pkg["name"] = app_name_en
    pkg["version"] = "1.0.0"
    pkg["description"] = app["description_cn"]
    _write(miniapp_dir / "package.json", json.dumps(pkg, ensure_ascii=False, indent=2))

    # --- 3b. README.md ---
    _write(miniapp_dir / "README.md", _readme(app, prd_json))

    # --- 3c. manifest.json：结构基线来自模板，仅填名称/描述 ---
    manifest = json.loads((base_template / "src" / "manifest.json").read_text(encoding="utf-8-sig"))
    manifest["name"] = app_name
    manifest["description"] = app["description_cn"]
    _write(src_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    # --- 3d. pages.json：路由基线来自模板 + 注册 overlay 签名页 ---
    pages_config = json.loads((base_template / "src" / "pages.json").read_text(encoding="utf-8-sig"))
    for pg in pages_config.get("pages", []):
        if pg.get("path") == "pages/form/form":
            pg.setdefault("style", {})["navigationBarTitleText"] = feature_title
    registered = {pg.get("path") for pg in pages_config.get("pages", [])}
    pages_root = src_dir / "pages"
    if pages_root.exists():
        for page_dir in sorted(p for p in pages_root.iterdir() if p.is_dir()):
            page_path = f"pages/{page_dir.name}/{page_dir.name}"
            if (page_dir / f"{page_dir.name}.vue").exists() and page_path not in registered:
                pages_config["pages"].append({
                    "path": page_path,
                    "style": {"navigationBarTitleText": app_name},
                })
                registered.add(page_path)
    _write(src_dir / "pages.json", json.dumps(pages_config, ensure_ascii=False, indent=2))

    # --- 4. 法务/上架 docs（属生成项目的一部分）---
    _write(docs_dir / "privacy-policy.md", _privacy_policy(app))
    _write(docs_dir / "user-agreement.md", _user_agreement(app))
    _write(docs_dir / "publish-guide.md", _publish_guide(app))

    gen_source["generated_files_count"] = len([f for f in miniapp_dir.rglob("*") if f.is_file()])
    return miniapp_dir, gen_source


def _readme(app: dict, prd_json: dict) -> str:
    return f"""# {app['name_cn']}

{app['description_cn']}

## 技术栈
- uni-app + Vue 3 + TypeScript
- 目标平台：{'、'.join(prd_json['target_platforms'])}

## 开发
```bash
npm install
npm run dev
```

## 构建
```bash
npm run build:mp-weixin
npm run build:mp-alipay
```
"""


def _privacy_policy(app: dict) -> str:
    return f"""# {app['name_cn']} 隐私政策

更新日期：{datetime.now().strftime('%Y年%m月%d日')}

## 信息收集

本小程序收集以下信息：
- 您主动输入的文本内容（仅用于 AI 处理，处理后不保留）
- 微信授权的昵称和头像（用于个人中心展示）
- 设备信息和操作日志（用于故障排查）

## 信息使用

收集的信息仅用于：
- 提供 AI 处理服务
- 改善产品体验
- 安全保障

## 信息存储

- 用户输入内容在处理完成后立即删除，不做存储
- 账户信息加密存储于中国大陆服务器
- 数据保留期限：账户注销后 30 天内彻底删除

## 第三方共享

我们不会将您的个人信息出售或提供给第三方。

## 用户权利

您有权：
- 查看、更正个人信息
- 删除账户及所有数据
- 撤回授权

## 联系我们

如有疑问，请通过小程序内「意见反馈」联系我们。
"""


def _user_agreement(app: dict) -> str:
    return f"""# {app['name_cn']} 用户服务协议

更新日期：{datetime.now().strftime('%Y年%m月%d日')}

## 服务说明

{app['name_cn']}是一款 AI 辅助工具类小程序，提供{app['description_cn'][:20]}等功能。

## 使用规范

用户不得：
- 输入违法违规内容
- 利用本服务生成虚假信息
- 对服务进行逆向工程
- 超出合理使用频率

## 免责声明

- AI 生成内容仅供参考，不构成专业建议
- 因网络原因导致的服务中断，不承担责任
- 用户对自身输入和使用行为负责

## 知识产权

- 本小程序的代码和设计归开发者所有
- 用户通过本服务生成的内容归用户所有

## 协议变更

我们有权对本协议进行修改，修改后将通过小程序内通知。
"""


def _publish_guide(app: dict) -> str:
    return f"""# {app['name_cn']} 上架操作指南

## 微信小程序上架步骤

1. 登录 [微信公众平台](https://mp.weixin.qq.com)
2. 进入「开发管理」→「开发设置」获取 AppID
3. 打开微信开发者工具，导入本项目
4. 填写 AppID 至 manifest.json 的 mp-weixin.appid
5. 点击「上传」将代码上传至管理后台
6. 回到微信公众平台，进入「版本管理」
7. 将上传的代码提交审核
8. 审核通过后点击「发布」

## 支付宝小程序上架步骤

1. 登录 [支付宝开放平台](https://open.alipay.com)
2. 创建小程序应用，获取 AppID
3. 使用支付宝小程序开发者工具上传代码
4. 提交审核

## 抖音小程序上架步骤

1. 登录 [抖音开放平台](https://developer.open-douyin.com)
2. 创建小程序，获取 AppID
3. 使用抖音开发者工具上传
4. 提交审核
"""
