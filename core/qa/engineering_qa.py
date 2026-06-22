"""core.qa.engineering_qa — 工程质量验证（build/dist/编码/结构）。

单一事实源：工程 QA 逻辑只在这里。runner 调用 run_engineering_qa：真跑 npm install + build:mp-weixin，
断言真实 dist 产物（app.js/app.json/app.wxss + 页面 js），三层乱码检测。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


GARBLED_PATTERNS = ["鈹", "鍥", "绋", "鐢", "涓", "鍙", "杩", "閰", "椤"]


def run_engineering_qa(miniapp_dir: Path, output_dir: Path) -> dict:
    """验证项目完整性、编码、路径、内容，并自动执行 npm install + build。"""
    import shutil
    import subprocess as sp

    issues = []

    # --- 1. 文件存在性检查 ---
    required_files = [
        "package.json", "README.md", "tsconfig.json", "index.html",
        "src/manifest.json", "src/pages.json", "src/main.ts", "src/App.vue",
        "src/pages/index/index.vue", "src/pages/form/form.vue",
        "src/pages/result/result.vue", "src/pages/profile/profile.vue",
        "src/utils/request.ts",
        "docs/privacy-policy.md", "docs/user-agreement.md", "docs/publish-guide.md",
    ]
    file_checks = []
    files_pass = True
    for f in required_files:
        exists = (miniapp_dir / f).exists()
        file_checks.append({"file": f, "exists": exists})
        if not exists:
            files_pass = False
            issues.append(f"文件缺失: {f}")
    # Canonical config is vite.config.ts (see generator for the .mjs->.ts
    # CJS/ESM interop rationale). A stray .mjs would silently break the build,
    # so QA requires the .ts and flags a leftover .mjs.
    vite_ts = (miniapp_dir / "vite.config.ts").exists()
    vite_mjs = (miniapp_dir / "vite.config.mjs").exists()
    vite_config_exists = vite_ts
    file_checks.append({"file": "vite.config.ts", "exists": vite_config_exists})
    if not vite_config_exists:
        files_pass = False
        issues.append("文件缺失: vite.config.ts")
    if vite_mjs:
        files_pass = False
        issues.append("检测到 vite.config.mjs（应为 vite.config.ts，.mjs 会导致 uni is not a function 构建失败）")

    # --- 2. 中文乱码检查（三层：严格 UTF-8 / U+FFFD / 模式）---
    encoding_pass = True
    garbled_files = []
    all_text_files = [f for f in miniapp_dir.rglob("*") if f.is_file() and f.suffix in (".json", ".md", ".vue", ".ts") and "node_modules" not in str(f)]
    output_text_files = [f for f in output_dir.iterdir() if f.is_file() and f.suffix in (".json", ".md")]
    for f in list(all_text_files) + list(output_text_files):
        try:
            raw = f.read_bytes()
        except Exception as e:
            encoding_pass = False
            garbled_files.append(str(f.name))
            issues.append(f"乱码检测: 无法读取 {f.name}: {e}")
            continue
        if raw[:3] == b"\xef\xbb\xbf":
            raw = raw[3:]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            encoding_pass = False
            garbled_files.append(str(f.name))
            issues.append(f"乱码检测: {f.name} 非 UTF-8 编码 ({e.reason})")
            continue
        if "�" in content:
            encoding_pass = False
            garbled_files.append(str(f.name))
            issues.append(f"乱码检测: {f.name} 含替换字符 U+FFFD（解码丢失）")
            continue
        for pattern in GARBLED_PATTERNS:
            if pattern in content:
                encoding_pass = False
                garbled_files.append(str(f.name))
                issues.append(f"乱码检测: {f.name} 包含 '{pattern}'")
                break

    # --- 3. human-actions.md 路径检查 ---
    path_pass = True
    human_actions_file = output_dir / "human-actions.md"
    if human_actions_file.exists():
        ha_content = human_actions_file.read_text(encoding="utf-8-sig")
        expected_path = str(output_dir / "generated" / "miniapp").replace("\\", "/")
        expected_path_win = str(output_dir / "generated" / "miniapp")
        if expected_path not in ha_content and expected_path_win not in ha_content:
            path_pass = False
            issues.append("human-actions.md 中小程序导入路径不正确")
    else:
        path_pass = False
        issues.append("human-actions.md 不存在")

    # --- 4. listing-materials.md 必要字段检查 ---
    listing_pass = True
    listing_file = output_dir / "listing-materials.md"
    required_listing_fields = ["中文名", "英文名", "一句话简介", "服务类目", "关键词", "隐私政策", "审核备注"]
    if listing_file.exists():
        listing_content = listing_file.read_text(encoding="utf-8-sig")
        for field in required_listing_fields:
            if field not in listing_content:
                listing_pass = False
                issues.append(f"listing-materials.md 缺少字段: {field}")
    else:
        listing_pass = False
        issues.append("listing-materials.md 不存在")

    # --- 5. README 必要步骤检查 ---
    readme_pass = True
    readme_file = miniapp_dir / "README.md"
    if readme_file.exists():
        readme_content = readme_file.read_text(encoding="utf-8-sig")
        for keyword in ["npm install", "npm run"]:
            if keyword not in readme_content:
                readme_pass = False
                issues.append(f"README.md 缺少: {keyword}")
    else:
        readme_pass = False
        issues.append("README.md 不存在")

    # --- 6. package.json build 脚本检查 ---
    build_scripts_pass = True
    pkg_file = miniapp_dir / "package.json"
    if pkg_file.exists():
        try:
            pkg = json.loads(pkg_file.read_text(encoding="utf-8-sig"))
            scripts = pkg.get("scripts", {})
            if "build:mp-weixin" not in scripts and "build" not in scripts:
                build_scripts_pass = False
                issues.append("package.json 缺少 build 脚本")
        except Exception:
            build_scripts_pass = False
            issues.append("package.json 无法解析")
    else:
        build_scripts_pass = False

    # --- 7. JSON 合法性检查 ---
    json_valid = True
    for json_file in ["package.json", "src/manifest.json", "src/pages.json"]:
        try:
            json.loads((miniapp_dir / json_file).read_text(encoding="utf-8-sig"))
        except Exception:
            json_valid = False
            issues.append(f"JSON 格式无效: {json_file}")

    # --- 8. 包大小检查（不含 node_modules） ---
    src_files = [f for f in miniapp_dir.rglob("*") if f.is_file() and "node_modules" not in str(f) and "dist" not in str(f)]
    total_size = sum(f.stat().st_size for f in src_files)
    size_check = total_size < 2 * 1024 * 1024

    # --- 9. 自动执行 npm install ---
    install_verified = False
    install_passed = False
    install_command = "npm install"
    install_duration_ms = 0
    install_error = ""

    npm_path = shutil.which("npm")
    install_timeout = int(os.environ.get("QA_INSTALL_TIMEOUT", "180"))
    build_timeout = int(os.environ.get("QA_BUILD_TIMEOUT", "180"))
    # 在 repo 内可控目录构建，避免使用系统 AppData\Local\Temp。
    # 某些 Windows 环境下，vite/esbuild 在 Temp 下构建时会向上递归读目录
    # （"../../../../.."）命中无权限目录，报 "Access is denied" 导致 build 失败。
    # 用 output_dir/.qa-build/miniapp（已被 .gitignore 忽略）规避该问题。
    build_tmp_root = (output_dir / ".qa-build").resolve()
    shutil.rmtree(build_tmp_root, ignore_errors=True)
    build_tmp_root.mkdir(parents=True, exist_ok=True)
    build_work_dir = build_tmp_root / "miniapp"
    shutil.copytree(
        str(miniapp_dir),
        str(build_work_dir),
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("node_modules", ".npm-cache", "dist"),
    )
    npm_env = os.environ.copy()
    npm_cache_dir = build_tmp_root / ".npm-cache"
    npm_cache_dir.mkdir(parents=True, exist_ok=True)
    npm_env.setdefault("NPM_CONFIG_CACHE", str(npm_cache_dir))
    if not npm_path:
        issues.append("npm 不可用，无法执行 install 和 build")
        install_error = "npm not found in PATH"
    else:
        install_verified = True
        t_start = time.time()
        try:
            result = sp.run(
                [npm_path, "install"],
                cwd=str(build_work_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=npm_env,
                timeout=install_timeout,
            )
            install_duration_ms = int((time.time() - t_start) * 1000)
            if result.returncode == 0:
                install_passed = True
            else:
                install_passed = False
                install_error = (result.stderr or result.stdout)[-500:]
                issues.append(f"npm install 失败 (exit {result.returncode}): {install_error[:200]}")
        except sp.TimeoutExpired:
            install_duration_ms = install_timeout * 1000
            install_error = f"npm install timed out ({install_timeout}s)"
            issues.append(install_error)
        except Exception as e:
            install_error = str(e)
            issues.append(f"npm install 异常: {e}")

    # --- 10. 自动执行 npm run build:mp-weixin ---
    build_verified = False
    build_passed = False
    build_command = "npm run build:mp-weixin"
    build_duration_ms = 0
    build_output_summary = ""
    build_error_summary = ""
    dist_path = ""

    if install_passed and npm_path:
        build_verified = True
        dist_dir = build_work_dir / "dist" / "build" / "mp-weixin"
        t_start = time.time()
        try:
            result = sp.run(
                [npm_path, "run", "build:mp-weixin"],
                cwd=str(build_work_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=npm_env,
                timeout=build_timeout,
            )
            build_duration_ms = int((time.time() - t_start) * 1000)
            output_text = result.stdout + result.stderr
            build_output_summary = output_text[-500:]
            # Success is determined by exit code + real build artifacts,
            # NOT by matching log text like "Build complete".
            key_files = [dist_dir / "app.json", dist_dir / "app.js", dist_dir / "app.wxss"]
            has_key_files = any(f.exists() for f in key_files) or (
                dist_dir.exists() and any(dist_dir.iterdir())
            )
            if result.returncode == 0 and dist_dir.exists() and has_key_files:
                build_passed = True
                final_dist_dir = miniapp_dir / "dist" / "build" / "mp-weixin"
                if final_dist_dir.exists():
                    shutil.rmtree(final_dist_dir)
                final_dist_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(str(dist_dir), str(final_dist_dir), dirs_exist_ok=True)
                dist_path = str(final_dist_dir)
            else:
                build_passed = False
                build_error_summary = output_text[-500:]
                issues.append(f"build 失败 (exit {result.returncode}): {build_error_summary[:200]}")
        except sp.TimeoutExpired:
            build_duration_ms = build_timeout * 1000
            build_error_summary = f"npm run build:mp-weixin timed out ({build_timeout}s)"
            issues.append(build_error_summary)
        except Exception as e:
            build_error_summary = str(e)
            issues.append(f"build 异常: {e}")

    # 清理构建工作目录。用 ignore_errors=True：Windows 下 npm 的 .npm-cache
    # 可能被占用句柄锁住而删不掉，残留也无妨——它在 .gitignore 忽略的 .qa-build 下。
    shutil.rmtree(build_tmp_root, ignore_errors=True)

    # --- 11. 验证 dist 目录存在且含真实构建产物 ---
    dist_exists = Path(dist_path).exists() if dist_path else False
    dist_artifacts_ok = False
    dist_missing_artifacts: list[str] = []
    if dist_exists:
        dist_root = Path(dist_path)
        required_artifacts = ["app.js", "app.json", "app.wxss"]
        for art in required_artifacts:
            if not (dist_root / art).exists():
                dist_missing_artifacts.append(art)
        page_js = list((dist_root / "pages").rglob("*.js")) if (dist_root / "pages").exists() else []
        if not page_js:
            dist_missing_artifacts.append("pages/**/*.js")
        dist_artifacts_ok = not dist_missing_artifacts
        if not dist_artifacts_ok:
            issues.append(f"dist 缺少关键构建产物: {', '.join(dist_missing_artifacts)}")
    dist_exists = dist_exists and dist_artifacts_ok
    if build_passed and not dist_exists:
        build_passed = False
        if not dist_missing_artifacts:
            issues.append("build 报告成功但 dist 目录不存在")

    # --- 综合判定 ---
    passed = all([
        files_pass,
        encoding_pass,
        path_pass,
        listing_pass,
        readme_pass,
        build_scripts_pass,
        json_valid,
        size_check,
        install_passed,
        build_verified,
        build_passed,
        dist_exists,
    ])

    return {
        "passed": passed,
        "total_files": len(src_files),
        "total_size_bytes": total_size,
        "total_size_readable": f"{total_size / 1024:.1f} KB",
        "checks": {
            "files_exist": files_pass,
            "encoding_passed": encoding_pass,
            "path_passed": path_pass,
            "listing_fields_passed": listing_pass,
            "readme_passed": readme_pass,
            "build_scripts_passed": build_scripts_pass,
            "json_valid": json_valid,
            "size_within_limit": size_check,
            "install_verified": install_verified,
            "install_passed": install_passed,
            "install_command": install_command,
            "install_duration_ms": install_duration_ms,
            "build_verified": build_verified,
            "build_passed": build_passed,
            "build_command": build_command,
            "build_duration_ms": build_duration_ms,
            "build_output_summary": build_output_summary,
            "build_error_summary": build_error_summary,
            "dist_path": dist_path,
            "dist_exists": dist_exists,
            "dist_artifacts_ok": dist_artifacts_ok,
            "dist_missing_artifacts": dist_missing_artifacts,
        },
        "file_checks": file_checks,
        "garbled_files": garbled_files,
        "issues": issues,
    }
