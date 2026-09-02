#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略交易系统 · onepress 一键部署 zip 打包脚本（WordPress 式体验）

使用：
  # 1) 先构建前端 dist（如果要带前端，zip 更完整；不带前端也能用，/docs /api /install 都 OK）
  cd frontend
  npm install
  npm run build
  cd ..
  # 2) 打包
  python deploy/make_onepress_zip.py

输出：
  桌面 / 当前目录下生成： strategy-trade-onepress-v1.0.0-YYYYMMDD-HHMMSS.zip

宝塔用户把 zip 上传到站点根（例如 /www/wwwroot/trade.xxx.com/），解压，
访问域名会自动跳 /install → 3 步向导 → 复制 1 行命令启动即可。
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]  # deploy/../ = 项目根
OUTPUT_PREFIX = "strategy-trade-onepress-v1.0.0"
INCLUDE_PATTERNS = [
    # 后端核心
    "main.py",
    "requirements.txt",
    ".env.example",
    "backend/**",
    "deploy/**",                     # 含 deploy/01_部署教程/*.md、onepress-install.sh、Nginx 片段等
    "StrategyTradeLauncher/**",
    # 前端（如果已构建 dist，直接带进去，免用户 npm install/build）
    "frontend/dist/**",
    # 导航文档（用户第一次打开站点根会看到）
    "0_宝塔WordPress式一键搭建说明.htm",
    # 桌面双击打包器（给其他机器上的开发者/运维方便）
    "0_一键打包_双击我→zip自动出现在桌面.pyw",
]
EXCLUDE_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".git", ".venv", "venv", "logs", "runtime", "dist.zip",
    "_zip_build",
}
EXCLUDE_EXTS = {
    ".pyc", ".pyo", ".pyd", ".log", ".pid", ".sock",
    ".zip", ".tar", ".tar.gz", ".bak", ".tmp",
    ".local", ".db-shm", ".db-wal",
}
# 绝对排除敏感/用户自定义文件（不要把自己的 .env / DB / 密钥打进 zip）
EXCLUDE_EXACT_NAMES = {
    ".env", ".installed", "trading_system.db", "trading_system.db-journal",
}
# 部署目录里不对外（只给开发者本机用的脚本）排除
EXCLUDE_REL_NAMES = {
    "deploy/make_onepress_zip.py",  # 打 zip 不需要把打 zip 的脚本也放进去（上面根目录那个桌面 .pyw 已包含）
}


def _should_include(rel_path: Path) -> bool:
    # 1) 目录名黑名单
    parts = rel_path.parts
    if any(p in EXCLUDE_DIR_NAMES for p in parts):
        return False
    # 2) 扩展名黑名单
    if rel_path.suffix.lower() in EXCLUDE_EXTS:
        return False
    # 3) 文件名精确黑名单
    if rel_path.name in EXCLUDE_EXACT_NAMES:
        return False
    # 4) .env.xxx 但保留 .env.example
    if rel_path.name.startswith(".env") and rel_path.name != ".env.example":
        return False
    return True


def _matches_any_pattern(rel_path: Path, patterns: list[str]) -> bool:
    """只把需要的 pattern 打进 zip，避免把外层垃圾文件带进去"""
    for pat in patterns:
        if "**" in pat:
            prefix = pat.split("**", 1)[0].rstrip("/\\")
            if prefix == "" or str(rel_path).startswith(prefix):
                return True
        else:
            try:
                if rel_path.match(pat):
                    return True
            except Exception:
                pass
    return False


def main() -> int:
    ts = time.strftime("%Y%m%d-%H%M%S")
    zip_name = f"{OUTPUT_PREFIX}-{ts}.zip"
    # 优先输出到桌面（开发时方便直接拖），没桌面 fallback 到项目根
    home = Path.home()
    desktop = home / "Desktop"
    if not desktop.exists():
        desktop = home / "桌面"
    out_dir = desktop if desktop.exists() else BASE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / zip_name

    # 先收集文件
    file_list: list[tuple[Path, Path]] = []  # (src, arcname)
    for root, dirs, files in os.walk(BASE_DIR):
        root_p = Path(root)
        # 提前 prune 目录名黑名单，加速 walk
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES]
        for fn in files:
            src = root_p / fn
            try:
                rel = src.relative_to(BASE_DIR)
            except Exception:
                continue
            if not _should_include(rel):
                continue
            # 5) 相对路径精确排除（deploy/make_onepress_zip.py 这种）
            if str(rel).replace("\\", "/") in EXCLUDE_REL_NAMES:
                continue
            if not _matches_any_pattern(rel, INCLUDE_PATTERNS):
                # 单独允许顶层几个文件（即使 pattern 没精确到）
                if rel.parts and rel.parts[0] not in {
                    "main.py", "requirements.txt", ".env.example",
                    "backend", "deploy", "StrategyTradeLauncher", "frontend",
                    "0_宝塔WordPress式一键搭建说明.htm",
                    "0_一键打包_双击我→zip自动出现在桌面.pyw",
                }:
                    continue
            # 目录黑名单再检查一次（因为我们会 prune，但前端 node_modules 这种也保险）
            if any(p in EXCLUDE_DIR_NAMES for p in rel.parts):
                continue
            file_list.append((src, rel))

    # 前端 dist 兜底：如果没构建 frontend/dist，至少把 index.html 入口不存在的情况让
    # onepress 安装向导知道 → zip 里给个空占位（让解压后目录就是 zip 包的 onepress 约定结构）
    # 这里不做 dummy，直接提示用户需要 build。
    frontend_dist_ok = any(
        str(arc).startswith("frontend/dist") for _, arc in file_list
    )

    # 写 zip
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # ====================================================================
        # 🚀 WordPress 式核心补丁：把 deploy/_onepress_wordpress_entry.html 作为 zip 根 index.html
        #     这样用户「宝塔添加网站 → 上传 zip → 解压 → 点击域名」
        #     Nginx 默认 index.html 立刻命中 → 直接看到安装向导，
        #     不需要用户先启动 uvicorn / 配置反代。
        # ====================================================================
        entry_src = BASE_DIR / "deploy" / "_onepress_wordpress_entry.html"
        if entry_src.exists():
            zf.write(str(entry_src), arcname="index.html")

        # 额外塞一个 README.txt 说明（就一句话，像 WordPress 的 readme.html）
        zf.writestr(
            "README-onepress.txt",
            "策略交易系统 onepress 一键部署包（WordPress 式 Famous 5 分钟）\n"
            "==============================================================\n\n"
            "宝塔部署（真·WordPress 式）：\n"
            "  1) 宝塔 → 网站 → 添加站点（PHP/数据库 全选『不创建』）\n"
            "  2) 站点根上传本 zip → 解压（⚠️ main.py 必须在根下，不能嵌在二级目录）\n"
            "  3) ✅ 点击域名立刻看到安装向导（不需要先启动后端）\n"
            "  4) 向导页没启动后端会出现 1 行命令 → 复制粘贴宝塔终端回车\n"
            "     （自动建 venv / 清华源 pip install / nohup 后台起 uvicorn:8000）\n"
            "  5) 后端起来后向导页变绿 → 点【▶️ 进入完整安装向导 /install】→ 勾 SQLite → 填管理员 → 运行安装\n"
            "  6) 第 ③ 步复制 Nginx 片段粘贴宝塔站点配置文件 → 完成\n\n"
            "配套图文教程（强烈推荐第一次照着点就行）：\n"
            "  👉 打开 deploy/01_部署教程/策略交易系统·WordPress式宝塔一键部署图文教程.md\n"
            "  👉 双击 0_宝塔WordPress式一键搭建说明.htm（彩色图文版，不用开编辑器）\n\n"
            f"打包时间：{ts}\n"
            f"Python 要求：3.10+\n"
            f"是否包含前端 dist：{'是（解压即可看到前端登录页）' if frontend_dist_ok else '否（/install /docs /api /health 都能正常用，前端可后续 cd frontend && npm run build）'}\n"
        )
        for src, arc in file_list:
            try:
                if not src.is_file():
                    continue
                # 避免 walk 到的根 index.html 覆盖我们上面打的静态入口
                if str(arc).replace("\\", "/") == "index.html":
                    continue
                zf.write(src, arcname=str(arc))
            except Exception as e:
                print(f"[WARN] skip {src}: {e}", file=sys.stderr)
        # 加一个 .htaccess/nginx 片段占位（避免 Nginx 直接展示目录）
        zf.writestr(
            "deploy/onepress-index-placeholder.html",
            "<!doctype html><meta charset='utf-8'/><title>解压成功</title>"
            "<body style='margin:0;padding:40px;font-family:Microsoft YaHei,sans-serif;background:#0b1220;color:#e2e8f0'>"
            "<h2>✅ onepress zip 解压成功</h2>"
            "<p>下一步：回到域名根路径（就是本目录）会自动显示 WordPress 式安装向导。</p>"
            "<p>如果后端已经启动：<a style='color:#93c5fd' href='/install'>直接进入 /install 向导</a>；<br/>"
            "后端没启动：在当前目录宝塔终端运行 <code style='background:#0b1120;border:1px solid #334155;padding:2px 8px;border-radius:6px'>bash deploy/onepress-install.sh</code> 即可。</p>"
            "<p>临时入口：<a style='color:#93c5fd' href='/health'>/health</a> · <a style='color:#93c5fd' href='/docs'>/docs</a> · <a style='color:#93c5fd' href='/install'>/install</a></p>"
            "</body>",
        )

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"\n✅ onepress 打包完成：{zip_path}")
    print(f"   文件数：{len(file_list)}，大小：{size_mb:.2f} MB")
    print(f"   前端 dist：{'已包含' if frontend_dist_ok else '未包含（用户后续可自行 build，不影响核心功能）'}")
    print(f"\n下一步：")
    print(f"   宝塔用户：把 {zip_path.name} 上传到站点根 → 解压 → 访问域名进入 /install 向导。")
    print(f"   本地用户：解压后 python main.py（或双击 StrategyTradeLauncher/Step0_一键启动后端_8000_HTA启动器.hta）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
