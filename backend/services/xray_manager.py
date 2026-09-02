"""
Xray-core 管理模块
- 解析 VLESS/VMess/Trojan/SS 订阅链接
- 为每个节点生成 Xray 配置并启动本地进程
- 本地监听 SOCKS5 端口，转换为 socks5://127.0.0.1:port
- 进程生命周期管理（启动/停止/健康检测/自动重启）
"""
from __future__ import annotations

import os
import sys
import json
import time
import signal
import socket
import subprocess
import threading
import base64
import urllib.parse
import zipfile
import shutil
import urllib.request
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from backend.core.logging_config import logger

# Xray 可执行文件路径（优先使用源码内置，其次用户目录）
_project_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "bin")
_xray_home = os.environ.get("XRAY_HOME", str(Path.home() / "xray"))
_project_xray = os.path.join(_project_bin, "xray.exe" if sys.platform == "win32" else "xray")
_home_xray = os.path.join(_xray_home, "xray.exe" if sys.platform == "win32" else "xray")
XRAY_EXE = _project_xray if os.path.isfile(_project_xray) else _home_xray
CONFIG_DIR = os.path.join(_xray_home, "configs")
PID_DIR = os.path.join(_xray_home, "pids")

# 端口范围
PORT_START = 20000
PORT_END = 20099

# 健康检测 URL
HEALTH_CHECK_URL = "https://api.ipify.org?format=json"
HEALTH_TIMEOUT = 10

# Xray 下载源（按优先级排序，国内镜像优先）
XRAY_VERSION = "v26.7.11"
XRAY_PLATFORMS = {
    "win32": "Xray-windows-64.zip",
    "darwin": "Xray-macos-64.zip",
    "linux": "Xray-linux-64.zip",
}
XRAY_DOWNLOAD_SOURCES = [
    "https://ghfast.top/https://github.com/XTLS/Xray-core/releases/download/{ver}/{pkg}",
    "https://gh.noki.icu/https://github.com/XTLS/Xray-core/releases/download/{ver}/{pkg}",
    "https://github.moeyy.xyz/https://github.com/XTLS/Xray-core/releases/download/{ver}/{pkg}",
    "https://ghproxy.com/https://github.com/XTLS/Xray-core/releases/download/{ver}/{pkg}",
    "https://github.com/XTLS/Xray-core/releases/download/{ver}/{pkg}",
]


def ensure_xray_installed() -> dict:
    """自动下载安装 Xray-core。返回 {installed: bool, path: str, error: str}"""
    if os.path.isfile(XRAY_EXE):
        return {"installed": True, "path": XRAY_EXE, "error": None, "message": "Xray已安装"}

    os.makedirs(_xray_home, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(PID_DIR, exist_ok=True)

    pkg = XRAY_PLATFORMS.get(sys.platform, XRAY_PLATFORMS["linux"])
    zip_path = os.path.join(_xray_home, "xray.zip")
    last_error = None

    for url_template in XRAY_DOWNLOAD_SOURCES:
        url = url_template.format(ver=XRAY_VERSION, pkg=pkg)
        try:
            logger.info(f"[XrayManager] 正在下载 Xray: {url}")
            with urllib.request.urlopen(url, timeout=120) as resp:
                with open(zip_path, "wb") as f:
                    f.write(resp.read())

            if os.path.getsize(zip_path) < 100000:
                last_error = f"下载文件过小，可能不是有效zip: {url}"
                continue

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(_xray_home)

            os.remove(zip_path)

            if os.path.isfile(XRAY_EXE):
                if sys.platform != "win32":
                    os.chmod(XRAY_EXE, 0o755)
                logger.info(f"[XrayManager] Xray安装成功: {XRAY_EXE}")
                return {"installed": True, "path": XRAY_EXE, "error": None, "message": "Xray安装成功"}
            else:
                exe_name = "xray.exe" if sys.platform == "win32" else "xray"
                possible = [f for f in os.listdir(_xray_home) if "xray" in f.lower()]
                last_error = f"解压后未找到 {exe_name}，目录内文件: {possible}"
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[XrayManager] 下载失败 {url}: {e}")
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass
            continue

    return {"installed": False, "path": XRAY_EXE, "error": last_error, "message": f"Xray下载失败: {last_error}"}


@dataclass
class XrayNode:
    """一个 Xray 节点（VLESS/VMess/Trojan/SS）"""
    raw_link: str                    # 原始链接 vless://... / vmess://... / trojan://... / ss://...
    protocol: str                    # vless / vmess / trojan / shadowsocks
    server: str                      # 服务器地址
    port: int                        # 服务器端口
    uuid_or_password: str            # UUID 或密码
    extra: dict = field(default_factory=dict)  # 额外参数（sni, path, host, security, type 等）
    name: str = ""                   # 节点名称
    local_port: int = 0              # 本地 SOCKS5 监听端口
    process: Optional[subprocess.Popen] = None  # Xray 进程
    status: str = "stopped"         # stopped / running / error
    last_check_ok: Optional[bool] = None
    last_check_at: Optional[str] = None
    check_latency_ms: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def local_proxy_url(self) -> str:
        """返回本地 SOCKS5 代理 URL"""
        return f"socks5://127.0.0.1:{self.local_port}" if self.local_port else ""

    @property
    def masked_name(self) -> str:
        """脱敏显示名称"""
        if self.name:
            return self.name
        return f"{self.protocol}:{self.server}:{self.port}"


class XrayManager:
    """Xray 进程管理器（单例）"""

    _instance: Optional["XrayManager"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._nodes: List[XrayNode] = []
        self._port_pool: set = set()  # 已分配端口
        self._enabled = False
        self._xray_available = os.path.isfile(XRAY_EXE)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(PID_DIR, exist_ok=True)

    @classmethod
    def get_instance(cls) -> "XrayManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = XrayManager()
        return cls._instance

    # ============== 链接解析 ==============

    @staticmethod
    def parse_subscription(text: str) -> List[XrayNode]:
        """解析订阅内容，返回节点列表。支持 Base64 编码、纯文本、JSON"""
        text = text.strip()
        if not text:
            return []

        # 尝试 Base64 解码
        if not text.startswith("[") and not text.startswith("{") and not "<" in text[:10]:
            try:
                padded = text + "=" * (4 - len(text) % 4) if len(text) % 4 else text
                decoded = base64.b64decode(padded).decode("utf-8", errors="ignore").strip()
                if decoded and "://" in decoded:
                    text = decoded
                    logger.info(f"[XrayManager] Base64解码成功，长度={len(text)}")
            except Exception:
                pass

        # 按行解析
        nodes = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            node = XrayManager._parse_single_link(line)
            if node:
                nodes.append(node)

        logger.info(f"[XrayManager] 解析订阅: 共 {len(nodes)} 个节点")
        return nodes

    @staticmethod
    def _parse_single_link(link: str) -> Optional[XrayNode]:
        """解析单个 vless:// vmess:// trojan:// ss:// 链接"""
        try:
            if link.startswith("vless://"):
                return XrayManager._parse_vless(link)
            elif link.startswith("vmess://"):
                return XrayManager._parse_vmess(link)
            elif link.startswith("trojan://"):
                return XrayManager._parse_trojan(link)
            elif link.startswith("ss://"):
                return XrayManager._parse_ss(link)
        except Exception as e:
            logger.warning(f"[XrayManager] 解析链接失败: {e}")
        return None

    @staticmethod
    def _parse_vless(link: str) -> Optional[XrayNode]:
        """解析 vless://uuid@server:port?params#name"""
        body = link[len("vless://"):]
        # 提取 name
        name = ""
        if "#" in body:
            body, name = body.split("#", 1)
            name = urllib.parse.unquote(name)
        # 提取 query
        params = {}
        if "?" in body:
            body, query = body.split("?", 1)
            for pair in query.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
        # 提取 uuid@server:port
        if "@" not in body:
            return None
        uuid_part, server_part = body.rsplit("@", 1)
        if ":" not in server_part:
            return None
        server, port_str = server_part.rsplit(":", 1)
        port = int(port_str)
        return XrayNode(
            raw_link=link,
            protocol="vless",
            server=server,
            port=port,
            uuid_or_password=uuid_part,
            extra=params,
            name=name,
        )

    @staticmethod
    def _parse_vmess(link: str) -> Optional[XrayNode]:
        """解析 vmess://base64json"""
        body = link[len("vmess://"):]
        try:
            padded = body + "=" * (4 - len(body) % 4) if len(body) % 4 else body
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            obj = json.loads(decoded)
            return XrayNode(
                raw_link=link,
                protocol="vmess",
                server=obj.get("add", ""),
                port=int(obj.get("port", 0)),
                uuid_or_password=obj.get("id", ""),
                extra={
                    "security": obj.get("scy", "auto"),
                    "sni": obj.get("sni", ""),
                    "host": obj.get("host", ""),
                    "path": obj.get("path", "/"),
                    "type": obj.get("net", "tcp"),
                    "aid": str(obj.get("aid", "0")),
                },
                name=obj.get("ps", ""),
            )
        except Exception as e:
            logger.warning(f"[XrayManager] VMess解析失败: {e}")
            return None

    @staticmethod
    def _parse_trojan(link: str) -> Optional[XrayNode]:
        """解析 trojan://password@server:port?params#name"""
        body = link[len("trojan://"):]
        name = ""
        if "#" in body:
            body, name = body.split("#", 1)
            name = urllib.parse.unquote(name)
        params = {}
        if "?" in body:
            body, query = body.split("?", 1)
            for pair in query.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[urllib.parse.unquote(k)] = urllib.parse.unquote(v)
        if "@" not in body:
            return None
        pwd, server_part = body.rsplit("@", 1)
        if ":" not in server_part:
            return None
        server, port_str = server_part.rsplit(":", 1)
        port = int(port_str)
        return XrayNode(
            raw_link=link,
            protocol="trojan",
            server=server,
            port=port,
            uuid_or_password=pwd,
            extra=params,
            name=name,
        )

    @staticmethod
    def _parse_ss(link: str) -> Optional[XrayNode]:
        """解析 ss://base64(method:password)@server:port#name"""
        body = link[len("ss://"):]
        name = ""
        if "#" in body:
            body, name = body.split("#", 1)
            name = urllib.parse.unquote(name)
        # SS 链接格式: base64(method:password)@server:port 或 base64(method:password@server:port)
        if "@" in body:
            method_pwd_b64, server_part = body.rsplit("@", 1)
            try:
                padded = method_pwd_b64 + "=" * (4 - len(method_pwd_b64) % 4) if len(method_pwd_b64) % 4 else method_pwd_b64
                method_pwd = base64.b64decode(padded).decode("utf-8", errors="ignore")
            except Exception:
                method_pwd = "aes-256-gcm:password"
            if ":" not in server_part:
                return None
            server, port_str = server_part.rsplit(":", 1)
            port = int(port_str)
            method, password = method_pwd.split(":", 1) if ":" in method_pwd else ("aes-256-gcm", method_pwd)
            return XrayNode(
                raw_link=link,
                protocol="shadowsocks",
                server=server,
                port=port,
                uuid_or_password=password,
                extra={"method": method},
                name=name,
            )
        return None

    # ============== Xray 配置生成 ==============

    @staticmethod
    def _generate_config(node: XrayNode, local_port: int) -> dict:
        """为节点生成 Xray JSON 配置"""
        inbound = {
            "port": local_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True},
        }

        outbound = XrayManager._build_outbound(node)

        return {
            "log": {"loglevel": "warning"},
            "inbounds": [inbound],
            "outbounds": [outbound],
        }

    @staticmethod
    def _build_outbound(node: XrayNode) -> dict:
        """根据协议构建 outbound 配置"""
        extra = node.extra or {}
        stream = XrayManager._build_stream(node)

        if node.protocol == "vless":
            vless_settings = {
                "vnext": [{
                    "address": node.server,
                    "port": node.port,
                    "users": [{"id": node.uuid_or_password, "encryption": "none"}],
                }]
            }
            if extra.get("flow"):
                vless_settings["vnext"][0]["users"][0]["flow"] = extra["flow"]
            return {"protocol": "vless", "settings": vless_settings, "streamSettings": stream}

        elif node.protocol == "vmess":
            return {
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": node.server,
                        "port": node.port,
                        "users": [{
                            "id": node.uuid_or_password,
                            "alterId": int(extra.get("aid", 0)),
                            "security": extra.get("security", "auto"),
                        }],
                    }]
                },
                "streamSettings": stream,
            }

        elif node.protocol == "trojan":
            return {
                "protocol": "trojan",
                "settings": {
                    "servers": [{
                        "address": node.server,
                        "port": node.port,
                        "password": node.uuid_or_password,
                    }]
                },
                "streamSettings": stream,
            }

        elif node.protocol == "shadowsocks":
            return {
                "protocol": "shadowsocks",
                "settings": {
                    "servers": [{
                        "address": node.server,
                        "port": node.port,
                        "method": extra.get("method", "aes-256-gcm"),
                        "password": node.uuid_or_password,
                    }]
                },
                "streamSettings": stream,
            }

        return {"protocol": "freedom"}

    @staticmethod
    def _build_stream(node: XrayNode) -> dict:
        """构建 streamSettings"""
        extra = node.extra or {}
        net_type = extra.get("type", extra.get("net", "tcp"))
        security = extra.get("security", "none")
        sni = extra.get("sni", "")
        host = extra.get("host", "")
        path = extra.get("path", "/")
        fp = extra.get("fp", "chrome")

        stream: dict = {"network": net_type}

        if security == "tls":
            stream["security"] = "tls"
            tls_settings: dict = {}
            if sni:
                tls_settings["serverName"] = sni
            if fp:
                tls_settings["fingerprint"] = fp
            if host and not sni:
                tls_settings["serverName"] = host
            stream["tlsSettings"] = tls_settings
        elif security == "reality":
            stream["security"] = "reality"
            reality_settings: dict = {
                "serverName": sni or host,
                "fingerprint": fp,
            }
            if extra.get("publicKey"):
                reality_settings["publicKey"] = extra["publicKey"]
            if extra.get("shortId"):
                reality_settings["shortId"] = extra["shortId"]
            stream["realitySettings"] = reality_settings

        if net_type == "ws":
            stream["wsSettings"] = {
                "path": path,
                "headers": {"Host": host} if host else {},
            }
        elif net_type == "grpc":
            stream["grpcSettings"] = {
                "serviceName": extra.get("serviceName", ""),
                "multiMode": extra.get("mode", "gun") == "multi",
            }
        elif net_type == "tcp" and host and security == "tls":
            stream["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "headers": {"Host": [host]},
                        "path": [path],
                    },
                }
            }

        return stream

    # ============== 端口管理 ==============

    def _alloc_port(self) -> int:
        """分配一个可用端口"""
        for port in range(PORT_START, PORT_END + 1):
            if port in self._port_pool:
                continue
            # 检查端口是否被占用
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    self._port_pool.add(port)
                    return port
                except OSError:
                    continue
        return 0

    def _release_port(self, port: int):
        self._port_pool.discard(port)

    # ============== 进程管理 ==============

    def start_node(self, node: XrayNode) -> bool:
        """启动单个节点的 Xray 进程"""
        with node._lock:
            if node.process and node.process.poll() is None:
                return True  # 已在运行

            port = self._alloc_port()
            if port == 0:
                logger.error("[XrayManager] 无可用端口")
                node.status = "error"
                return False
            node.local_port = port

            config = self._generate_config(node, port)
            config_path = os.path.join(CONFIG_DIR, f"node_{port}.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

            try:
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NO_WINDOW

                node.process = subprocess.Popen(
                    [XRAY_EXE, "run", "-config", config_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=creation_flags,
                )
                time.sleep(1)
                if node.process.poll() is None:
                    node.status = "running"
                    logger.info(f"[XrayManager] 节点 {node.masked_name} 启动成功，端口 {port}")
                    return True
                else:
                    err = node.process.stderr.read().decode("utf-8", errors="ignore") if node.process.stderr else ""
                    logger.error(f"[XrayManager] 节点 {node.masked_name} 启动失败: {err[:200]}")
                    node.status = "error"
                    self._release_port(port)
                    return False
            except Exception as e:
                logger.error(f"[XrayManager] 启动进程异常: {e}")
                node.status = "error"
                self._release_port(port)
                return False

    def stop_node(self, node: XrayNode):
        """停止单个节点"""
        with node._lock:
            if node.process:
                try:
                    node.process.terminate()
                    node.process.wait(timeout=5)
                except Exception:
                    try:
                        node.process.kill()
                    except Exception:
                        pass
                node.process = None
            if node.local_port:
                self._release_port(node.local_port)
            node.status = "stopped"
            logger.info(f"[XrayManager] 节点 {node.masked_name} 已停止")

    def start_all(self) -> dict:
        """启动所有节点"""
        if not self._xray_available:
            result = ensure_xray_installed()
            if result["installed"]:
                self._xray_available = True
            else:
                return {"error": f"Xray未安装: {result.get('error', '')}", "started": 0, "total": len(self._nodes)}

        started = 0
        for node in self._nodes:
            if self.start_node(node):
                started += 1
        self._enabled = True
        logger.info(f"[XrayManager] 批量启动: {started}/{len(self._nodes)} 成功")
        return {"started": started, "total": len(self._nodes)}

    def stop_all(self):
        """停止所有节点"""
        for node in self._nodes:
            self.stop_node(node)
        self._enabled = False
        logger.info("[XrayManager] 所有节点已停止")

    # ============== 订阅管理 ==============

    def load_subscription(self, url: str) -> dict:
        """从订阅URL拉取并解析节点"""
        import requests as _rq
        try:
            resp = _rq.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 ClashforWindows/0.20.39"},
            )
            resp.raise_for_status()
            text = resp.text.strip()
        except Exception as e:
            return {"error": f"拉取失败: {e}", "parsed": 0}

        # 如果URL本身包含vless://等链接，直接解析URL参数
        if "vless://" in url or "vmess://" in url or "trojan://" in url or "ss://" in url:
            # URL参数中包含节点链接
            parsed_url = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed_url.query)
            for key, values in params.items():
                for v in values:
                    if "://" in v:
                        text = urllib.parse.unquote(v)
                        break

        nodes = self.parse_subscription(text)
        self._nodes = nodes
        return {
            "parsed": len(nodes),
            "nodes": [{"name": n.masked_name, "protocol": n.protocol, "server": n.server, "port": n.port} for n in nodes],
        }

    def load_subscription_from_link(self, link: str) -> dict:
        """直接从节点链接加载（不通过订阅URL）"""
        node = self._parse_single_link(link)
        if node:
            self._nodes = [node]
            return {"parsed": 1, "nodes": [{"name": node.masked_name, "protocol": node.protocol, "server": node.server, "port": node.port}]}
        return {"error": "解析失败", "parsed": 0}

    # ============== 健康检测 ==============

    def check_all_nodes(self) -> dict:
        """检测所有运行中节点的连通性"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        running = [n for n in self._nodes if n.status == "running"]
        if not running:
            return {"total": 0, "ok": 0, "failed": 0, "results": []}

        def _check(node):
            return self._check_single(node)

        with ThreadPoolExecutor(max_workers=min(5, len(running))) as ex:
            futures = {ex.submit(_check, n): n for n in running}
            for fu in as_completed(futures):
                results.append(fu.result())

        ok_count = sum(1 for r in results if r["ok"])
        return {"total": len(results), "ok": ok_count, "failed": len(results) - ok_count, "results": results}

    def _check_single(self, node: XrayNode) -> dict:
        """检测单个节点"""
        import time as _time
        import requests as _rq
        t0 = _time.monotonic()
        try:
            resp = _rq.get(
                HEALTH_CHECK_URL,
                proxies={"http": node.local_proxy_url, "https": node.local_proxy_url},
                timeout=HEALTH_TIMEOUT,
                headers={"User-Agent": "XrayCheck/1.0"},
            )
            latency = int((_time.monotonic() - t0) * 1000)
            ok = resp.status_code == 200
            ip = ""
            try:
                ip = resp.json().get("origin", "")
            except Exception:
                pass
            with node._lock:
                node.last_check_ok = ok
                node.last_check_at = datetime.now().isoformat()
                node.check_latency_ms = latency
            return {
                "name": node.masked_name,
                "port": node.local_port,
                "ok": ok,
                "latency_ms": latency,
                "ip": ip,
                "error": None if ok else f"HTTP_{resp.status_code}",
            }
        except Exception as e:
            latency = int((_time.monotonic() - t0) * 1000)
            with node._lock:
                node.last_check_ok = False
                node.last_check_at = datetime.now().isoformat()
                node.check_latency_ms = latency
            return {
                "name": node.masked_name,
                "port": node.local_port,
                "ok": False,
                "latency_ms": latency,
                "ip": "",
                "error": e.__class__.__name__,
            }

    # ============== 状态报告 ==============

    def status_report(self) -> dict:
        """获取所有节点状态"""
        nodes_info = []
        for n in self._nodes:
            with n._lock:
                is_running = n.process is not None and (n.process.poll() is None if n.process else False)
                nodes_info.append({
                    "name": n.masked_name,
                    "protocol": n.protocol,
                    "server": n.server,
                    "port": n.port,
                    "local_port": n.local_port,
                    "local_proxy": n.local_proxy_url,
                    "status": "running" if is_running else n.status,
                    "last_check_ok": n.last_check_ok,
                    "check_latency_ms": n.check_latency_ms,
                    "last_check_at": n.last_check_at,
                })
        running = sum(1 for n in nodes_info if n["status"] == "running")
        return {
            "xray_available": self._xray_available,
            "xray_path": XRAY_EXE,
            "enabled": self._enabled,
            "total_nodes": len(nodes_info),
            "running": running,
            "stopped": len(nodes_info) - running,
            "nodes": nodes_info,
        }

    def get_proxy_urls(self) -> List[str]:
        """获取所有运行中节点的本地代理URL（供 ProxyManager 使用）"""
        urls = []
        for n in self._nodes:
            with n._lock:
                if n.process and n.process.poll() is None and n.local_port:
                    urls.append(n.local_proxy_url)
        return urls
