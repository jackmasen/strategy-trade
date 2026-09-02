# -*- coding: utf-8 -*-
"""
策略交易系统 · 纯 Python 自包含后端启动器（.pyw 无黑框版本）
- 100% 不依赖 .bat/.vbs/.ps1，不受 PowerShell ExecutionPolicy / AppLocker 对脚本文件的拦截
- 在纯 Python 内完成：找解释器 -> 建 venv -> 装依赖 -> 杀 8000 占用 -> 启 uvicorn -> 轮询 /health -> 打开浏览器
"""
import os
import re
import sys
import time
import pathlib
import logging
import tempfile
import threading
import subprocess
import urllib.request
from typing import Optional

# ============== 基础常量 ==============
PROJECT_ROOT = pathlib.Path(r"C:\Users\AI\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\work-mode-projects\6a6da3890eac9824cd4457aa")
assert PROJECT_ROOT.exists(), f"项目根不存在: {PROJECT_ROOT}"
os.chdir(str(PROJECT_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_DIR = PROJECT_ROOT
LOG_LAUNCH = LOG_DIR / "_logs_backend_launcher.log"
LOG_BACKEND = LOG_DIR / "_logs_backend.log"
VENV_DIR = PROJECT_ROOT / ".venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
EMBED_PY = PROJECT_ROOT / "_python" / "python.exe"
REQUIREMENTS_TXT = PROJECT_ROOT / "requirements.txt"
HEALTH_URL = "http://127.0.0.1:8000/health"
DOCS_URL = "http://127.0.0.1:8000/docs"

handlers = [logging.FileHandler(str(LOG_LAUNCH), encoding="utf-8")]
try:
    if sys.stdout is not None and getattr(sys.stdout, "fileno", lambda: None)() is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
except Exception:
    pass
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=handlers,
)
log = logging.getLogger("backend_launcher")


def log_and_print(msg: str):
    log.info(msg)


def find_host_python() -> Optional[str]:
    if VENV_PY.exists():
        log_and_print(f"[Python] 已存在 venv: {VENV_PY}")
        return str(VENV_PY)
    if EMBED_PY.exists():
        log_and_print(f"[Python] 找到 embeddable 免安装版: {EMBED_PY}")
        return str(EMBED_PY)
    try:
        from shutil import which
        for exe in ("python", "python3"):
            p = which(exe)
            if p:
                log_and_print(f"[Python] 系统 PATH: {p}")
                return p
    except Exception:
        pass
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Python\PythonCore",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k0:
            for i in range(256):
                try:
                    ver = winreg.EnumKey(k0, i)
                    with winreg.OpenKey(k0, f"{ver}\\InstallPath") as k1:
                        install, _ = winreg.QueryValueEx(k1, None)
                    py = pathlib.Path(install) / "python.exe"
                    if py.exists():
                        log_and_print(f"[Python] 注册表 InstallPath: {py}")
                        return str(py)
                except OSError:
                    break
    except Exception:
        pass
    return None


def create_venv_if_needed(host_py: str) -> str:
    if VENV_PY.exists():
        return str(VENV_PY)
    log_and_print("[VENV] 不存在，正在创建...")
    t0 = time.time()
    r = subprocess.run(
        [host_py, "-m", "venv", "--without-pip", "--clear", str(VENV_DIR)],
        capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False,
    )
    if r.returncode != 0:
        r2 = subprocess.run(
            [host_py, "-m", "venv", "--clear", str(VENV_DIR)],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False,
        )
        if r2.returncode != 0:
            log_and_print(f"[VENV] 创建失败 stderr:\n{r2.stderr}\nstdout:\n{r2.stdout}")
            raise RuntimeError("venv 创建失败")
    log_and_print(f"[VENV] 完成，耗时 {time.time()-t0:.1f}s")
    return str(VENV_PY)


def bootstrap_pip_in_venv(venv_py: str) -> None:
    r = subprocess.run([venv_py, "-m", "pip", "--version"],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False)
    if r.returncode == 0:
        return
    log_and_print("[PIP] venv 内 pip 缺失，ensurepip 修复...")
    r2 = subprocess.run([venv_py, "-m", "ensurepip", "--upgrade"],
                        capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False)
    if r2.returncode == 0:
        return
    log_and_print(f"[PIP] ensurepip exit={r2.returncode}，继续尝试 pip install（可能自举）")


def pip_install_requirements(venv_py: str) -> None:
    try:
        import importlib
        modules_to_try = {"fastapi","uvicorn","sqlalchemy","pydantic","redis","celery",
                          "jinja2","pandas","numpy","requests","websockets","aiosqlite"}
        misses = []
        for m in modules_to_try:
            try:
                importlib.import_module(m if m != "python-jose" else "jose")
            except Exception:
                misses.append(m)
        if not misses:
            log_and_print("[PIP] 核心依赖均已就绪，跳过 pip install")
            return
        log_and_print(f"[PIP] 缺以下模块，开始安装: {misses}")
    except Exception as e:
        log_and_print(f"[PIP] 预检查跳过: {e}")

    log_and_print("[PIP] 升级 pip + 装 requirements（清华镜像优先）...")
    commands = [
        [venv_py, "-m", "pip", "install", "--upgrade", "pip",
         "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
        [venv_py, "-m", "pip", "install", "-r", str(REQUIREMENTS_TXT),
         "--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple"],
    ]
    ok = True
    last_out = ""
    for cmd in commands:
        t = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False)
        log_and_print(f"[PIP] exit={r.returncode} 耗时 {time.time()-t:.1f}s cmd={' '.join(cmd[:5])}")
        last_out = (r.stderr or "") + "\n" + (r.stdout or "")
        if r.returncode != 0:
            log_and_print(f"[PIP] FAIL 尾部: {last_out[-1200:]}")
            ok = False
            break
    if ok:
        return

    log_and_print("[PIP] 镜像失败，回退默认源...")
    for cmd in ([venv_py, "-m", "pip", "install", "--upgrade", "pip"],
                [venv_py, "-m", "pip", "install", "-r", str(REQUIREMENTS_TXT)]):
        t = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False)
        log_and_print(f"[PIP] retry exit={r.returncode} 耗时 {time.time()-t:.1f}s")
        if r.returncode != 0:
            last_out = (r.stderr or "") + "\n" + (r.stdout or "")
    r_ok = subprocess.run(
        [venv_py, "-c", "import fastapi,uvicorn,sqlalchemy;print('OK')"],
        capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False,
    )
    if r_ok.returncode != 0:
        log_and_print(f"[PIP] 仍然失败：无法 import fastapi/uvicorn/sqlalchemy。尾部:\n{last_out[-1500:]}")


def kill_port_8000() -> None:
    log_and_print("[PORT] 检查 8000 端口占用...")
    try:
        r = subprocess.run(["netstat.exe", "-ano"],
                           capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False)
        if r.returncode != 0:
            return
        found = False
        for line in (r.stdout or "").splitlines():
            m = re.search(r"\s:8000\s.*LISTENING\s+(\d+)\s*$", line)
            pid = None
            if m:
                pid = m.group(1)
            elif ":8000" in line and "LISTENING" in line:
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pid = parts[-1]
            if pid:
                found = True
                log_and_print(f"[PORT] 8000 占用 PID={pid}，taskkill /F")
                r2 = subprocess.run(["taskkill.exe", "/PID", pid, "/F"],
                                    capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=False)
                log_and_print(f"[PORT] taskkill exit={r2.returncode} out={(r2.stdout or '').strip()}")
        if not found:
            log_and_print("[PORT] 8000 未被占用")
        else:
            time.sleep(1.5)
    except Exception as e:
        log_and_print(f"[PORT] 清理异常: {e}")


def health_probe_and_open_browser(max_wait: int = 180) -> bool:
    deadline = time.time() + max_wait
    last_err = ""
    i = 0
    while time.time() < deadline:
        i += 1
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                body = resp.read()
            if resp.status == 200:
                log_and_print(f"[HEALTH] 第 {i} 次探测成功 status=200 body={body[:200]}")
                try:
                    import webbrowser
                    webbrowser.open(DOCS_URL, new=2)
                    log_and_print(f"[BROWSER] 已自动打开 {DOCS_URL}")
                except Exception as e:
                    log_and_print(f"[BROWSER] 自动打开失败，请手动访问 {DOCS_URL}（{e}）")
                return True
            last_err = f"status={resp.status} body={body[:200]}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if i % 10 == 0:
            log_and_print(f"[HEALTH] 第 {i} 次仍未成功，最近错误: {last_err}")
        time.sleep(2)
    log_and_print(f"[HEALTH] 超时未成功，最近一次错误: {last_err}")
    return False


def start_uvicorn(venv_py: str) -> subprocess.Popen:
    log_and_print("[UVICORN] 启动 FastAPI :8000，日志 -> _logs_backend.log")
    fh = open(str(LOG_BACKEND), "a", encoding="utf-8")
    fh.write("\n\n============== 新一次启动 " + time.strftime("%Y-%m-%d %H:%M:%S") + " ==============\n")
    fh.flush()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PROJECT_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    launch_py = PROJECT_ROOT / "_launch_backend.py"
    if launch_py.exists():
        args = [venv_py, str(launch_py)]
    else:
        args = [venv_py, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
    try:
        p = subprocess.Popen(
            args, cwd=str(PROJECT_ROOT), stdout=fh, stderr=fh,
            shell=False, env=env, close_fds=False,
        )
    except TypeError:
        p = subprocess.Popen(
            args, cwd=str(PROJECT_ROOT), stdout=fh, stderr=fh,
            shell=False, env=env,
        )
    log_and_print(f"[UVICORN] 启动成功，后端 PID={p.pid}")
    return p


def pyw_keep_alive_foreground() -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main() -> None:
    log_and_print("=" * 60)
    log_and_print("策略交易系统 · 纯 Python 一键启动后端 8000（新版 .pyw）")
    log_and_print(f"项目根: {PROJECT_ROOT}")
    log_and_print("=" * 60)

    host = find_host_python()
    if not host:
        msg = (
            "[FATAL] 未找到 Python 解释器！\n\n"
            "方案 A（推荐 · 免安装绿色版，无需管理员权限）：\n"
            "  下载 https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64-embed-amd64.zip\n"
            "  解压到: " + str(PROJECT_ROOT / "_python") + "\n"
            "  解压后确保 " + str(EMBED_PY) + " 存在\n\n"
            "方案 B（常规安装版）：\n"
            "  安装 Python 3.10+ 安装包（https://www.python.org/downloads/）\n"
            "  安装时务必勾选『Add Python to PATH』\n\n"
            "完成后再次双击本文件即可。\n\n"
            "日志路径：\n  - 启动日志: " + str(LOG_LAUNCH) + "\n  - 后端日志: " + str(LOG_BACKEND) + "\n"
        )
        log_and_print(msg)
        try:
            tmp = pathlib.Path(tempfile.gettempdir()) / "strategytrade_no_python_hint.txt"
            tmp.write_text(msg, encoding="utf-8")
            subprocess.Popen(["notepad.exe", str(tmp)], shell=False)
        except Exception:
            pass
        return

    try:
        venv_py = create_venv_if_needed(host)
        bootstrap_pip_in_venv(venv_py)
        pip_install_requirements(venv_py)
    except Exception as e:
        log_and_print(f"[ENV] 环境准备失败: {e}")
        return

    kill_port_8000()

    threading.Thread(target=health_probe_and_open_browser, daemon=True).start()
    try:
        proc = start_uvicorn(venv_py)
    except Exception as e:
        log_and_print(f"[UVICORN] 启动异常: {e}")
        return

    try:
        code = proc.wait()
        log_and_print(f"[UVICORN] 子进程退出 code={code}；请查看 _logs_backend.log 定位原因")
    except KeyboardInterrupt:
        log_and_print("[UVICORN] 用户停止")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.exception("启动崩溃: %s", e)
    pyw_keep_alive_foreground()
