"""
代理管理器 ProxyManager（全局单例）

目标：美国的 CoinDesk/Reuters/Bloomberg/CNBC 经常对中国大陆/云厂商 IP 做
403 / 空 RSS / 5s+ 延迟甚至直接 reset；一旦某源限流，系统就失去"新闻情绪打分"
这 30% 权重，等于瞎下单。所以本模块实现：

使用策略（严格对齐 Shop Monitor 系统 + 代理池系统的踩坑血泪经验）：
  1) 快速失败 + 直连降级：代理获取总超时 8s（默认），到点返回 None，爬虫直接直连
     —— 解决"默认开启代理后整个系统卡死"问题
  2) 业务失败 ≠ 代理失败：HTTP 200 但 RSS 内容空 / 解析不到条目 / 页数空，
     只做"同代理退避重试"，不 mark 代理死；
     只有明确是代理层异常（requests.exceptions.ProxyError / ConnectTimeout /
     ReadTimeout / SSLError 握手失败 / 407 鉴权失败）并且同一代理累计 ≥ 3 次，
     才把代理置 inactive —— 解决"代理池自激式耗尽"问题
  3) 寿命只一套口径：assigned_at + PROXY_DEFAULT_TTL_MINUTES（默认 25 分钟）。
     离到期 <1min 时不再分配新任务。不使用 expire_at 触发切换，避免多口径冲突
  4) 硬超时 + 进度日志：每次抓取 / 校验前打日志，避免用户体感"卡住"
  5) 两种注入方式（用户不改代码也能用）：
       - PROXY_HTTP_LIST 逗号分隔（最常用的静态列表）
       - PROXY_PROVIDER_URL 定时拉 txt/json
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

from backend.core.logging_config import logger
from backend.config import get_settings


# ---------- 把 requests 的异常名绑定起来（import 失败也不崩，调用方用字符串比较） ----------
try:
    import requests as _rq
    PROXY_LAYER_EXCEPTIONS = (
        _rq.exceptions.ProxyError,
        _rq.exceptions.ConnectTimeout,
        _rq.exceptions.SSLError,
        _rq.exceptions.ConnectionError,
    )
    _TIMEOUT_EXC = _rq.exceptions.Timeout
except Exception:
    PROXY_LAYER_EXCEPTIONS = tuple()  # type: ignore
    _TIMEOUT_EXC = Exception  # type: ignore


@dataclass
class ProxyEntry:
    url: str                                   # "http://user:pass@host:port"
    protocol: str                              # "http" / "https" / "socks5"
    is_active: bool = True
    consecutive_proxy_errors: int = 0          # 连续代理层错误计数（≥3 置 inactive）
    total_proxy_errors: int = 0
    total_business_retries: int = 0            # 业务空页 / 解析失败（不杀代理）
    assigned_at: Optional[datetime] = None     # 分配时刻（TTL 口径唯一来源）
    last_used_at: Optional[datetime] = None
    used_count: int = 0
    # 主动健康检测状态
    last_check_at: Optional[datetime] = None   # 最后检测时间
    last_check_ok: Optional[bool] = None       # True=正常(绿灯) False=失败(红灯) None=未检测
    check_latency_ms: Optional[int] = None     # 检测延迟(ms)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_expiring_soon(self, ttl_minutes: int) -> bool:
        """提前 1 分钟不分配新任务；到期则判过期"""
        if self.assigned_at is None:
            return False
        elapsed = (datetime.now() - self.assigned_at).total_seconds() / 60.0
        threshold = max(1, ttl_minutes - 1)
        return elapsed >= threshold


class ProxyManager:
    """全局单例：线程安全。可无代理时完全退化为直连，不会拖慢任何请求。"""

    _instance: Optional["ProxyManager"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ProxyManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = ProxyManager()
        return cls._instance

    def __init__(self):
        s = get_settings()
        self.enabled: bool = bool(getattr(s, "PROXY_ENABLED", True))
        self.list_conf: str = str(getattr(s, "PROXY_HTTP_LIST", "") or "").strip()
        self.provider_url: str = str(getattr(s, "PROXY_PROVIDER_URL", "") or "").strip()
        self.refresh_min: int = int(getattr(s, "PROXY_REFRESH_MINUTES", 20) or 20)
        self.ttl_min: int = int(getattr(s, "PROXY_DEFAULT_TTL_MINUTES", 25) or 25)
        self.fetch_timeout_sec: float = float(
            getattr(s, "PROXY_FETCH_TIMEOUT_SECONDS", 8) or 8
        )

        self._proxies: Dict[str, ProxyEntry] = {}   # key=url
        self._lock = threading.RLock()
        self._last_refresh_at: Optional[datetime] = None
        # 计数器（用于轮询分配，避免单个代理被打爆）
        self._rr_index = 0

        if self.enabled:
            # 初始化时立刻加载一次；失败也不抛异常，自动降级
            try:
                self._load_initial(force=True)
            except Exception as e:
                logger.warning(f"[ProxyManager] 初始化加载代理失败，降级为直连：{e}")
                self.enabled = False

    # ============== 对外核心 API ==============

    def acquire(self, host: str = "", prefer_us_ip: bool = True) -> Optional[str]:
        """
        获取一个代理 URL（用于 requests 的 proxies={"http":url,"https":url}）。
        返回 None 表示"此请求走直连"（无代理 / 代理全挂）。

        硬性边界：整体不会超过 fetch_timeout_sec，避免卡死。
        """
        t0 = time.monotonic()
        if not self.enabled:
            return None
        # 到点自动刷新
        try:
            self._refresh_if_due()
        except Exception:
            pass
        deadline = t0 + self.fetch_timeout_sec

        # 最多尝试 6 个"轮询候选"，都不行就直连
        for _attempt in range(6):
            if time.monotonic() > deadline:
                logger.debug("[ProxyManager] acquire 超时，降级直连")
                return None
            p = self._pick_next_rr()
            if p is None:
                # 完全没有可用代理 → 直连
                return None
            with p._lock:
                if not p.is_active:
                    continue
                if p.is_expiring_soon(self.ttl_min):
                    # 到期前 1 分钟不给新任务 → 再分配下一个
                    continue
                # 未分配过的 → 记录分配时刻（唯一寿命口径）
                if p.assigned_at is None:
                    p.assigned_at = datetime.now()
                p.last_used_at = datetime.now()
                p.used_count += 1
                return p.url
        return None

    def mark_proxy_layer_error(self, proxy_url: Optional[str], host: str = "",
                               exc: Optional[BaseException] = None) -> None:
        """
        明确的代理层错误（ProxyError/ConnectTimeout/SSLError 握手等）。
        连续 3 次 → 把代理从 active 池移除；避免自激式故障（198073 经验）。
        """
        if not proxy_url:
            return
        p = self._proxies.get(proxy_url)
        if not p:
            return
        with p._lock:
            p.consecutive_proxy_errors += 1
            p.total_proxy_errors += 1
            exc_name = exc.__class__.__name__ if exc else ""
            logger.warning(
                f"[ProxyManager] 代理层错误 {exc_name} host={host} "
                f"proxy={self._mask(proxy_url)} consecutive={p.consecutive_proxy_errors}"
            )
            if p.consecutive_proxy_errors >= 3:
                p.is_active = False
                logger.warning(f"[ProxyManager] 代理被置为 inactive：{self._mask(proxy_url)}")

    def mark_business_retry(self, proxy_url: Optional[str], host: str = "",
                            reason: str = "") -> None:
        """
        HTTP 200 但 RSS 空页 / 解析失败 —— 业务失败，不杀代理，只计数。
        （198073 #2 经验：空页≠代理坏，否则大量代理被快速打标 inactive → 代理池耗尽）
        """
        if not proxy_url:
            return
        p = self._proxies.get(proxy_url)
        if not p:
            return
        with p._lock:
            p.total_business_retries += 1
            logger.debug(
                f"[ProxyManager] 业务重试（不杀代理）host={host} "
                f"reason={reason[:80]} proxy={self._mask(proxy_url)}"
            )

    def mark_success(self, proxy_url: Optional[str], host: str = "") -> None:
        """请求成功（HTTP 200 + 解析 OK）→ 清连续错误计数"""
        if not proxy_url:
            return
        p = self._proxies.get(proxy_url)
        if not p:
            return
        with p._lock:
            p.last_used_at = datetime.now()
            if p.consecutive_proxy_errors > 0:
                p.consecutive_proxy_errors = 0

    # ============== 健康 / 自检报告 ==============

    def health_report(self) -> dict:
        """供 health_check.py 和前端 /api/health/proxy 使用"""
        with self._lock:
            all_list = list(self._proxies.values())
        active = [p for p in all_list if p.is_active]
        expiring = [p for p in active if p.is_expiring_soon(self.ttl_min)]
        urls_out: List[str] = []
        for p in active:
            with p._lock:
                urls_out.append(self._mask(p.url))
        inactive_list = [p for p in all_list if not p.is_active]
        inactive_out = []
        for p in inactive_list:
            with p._lock:
                inactive_out.append({
                    "url": self._mask(p.url),
                    "errors": p.consecutive_proxy_errors,
                    "total_errors": p.total_proxy_errors,
                    "used_count": p.used_count,
                })
        return {
            "enabled": self.enabled,
            "total": len(all_list),
            "active": len(active),
            "inactive": len(all_list) - len(active),
            "expiring_soon": len(expiring),
            "refresh_interval_minutes": self.refresh_min,
            "ttl_minutes": self.ttl_min,
            "last_refresh_at": self._last_refresh_at.isoformat() if self._last_refresh_at else None,
            "provider_url": bool(self.provider_url),
            "static_list_count": len([u for u in self.list_conf.split(",") if u.strip()]) if self.list_conf else 0,
            "active_proxies": urls_out,
            "inactive_proxies": inactive_out,
            "all_proxies_detail": [
                {
                    "url": self._mask(p.url),
                    "is_active": p.is_active,
                    "last_check_ok": p.last_check_ok,
                    "check_latency_ms": p.check_latency_ms,
                    "last_check_at": p.last_check_at.isoformat() if p.last_check_at else None,
                    "used_count": p.used_count,
                    "errors": p.consecutive_proxy_errors,
                }
                for p in all_list
            ],
        }

    def reload_from_db(self) -> bool:
        """从数据库 SystemConfig 重新加载代理配置（前端保存后调用）"""
        try:
            from backend.db.session import SessionLocal
            from backend.models.system_config import SystemConfig
            from sqlalchemy import inspect as sa_inspect
            from backend.db.session import engine_sync

            db = SessionLocal()
            try:
                insp = sa_inspect(engine_sync)
                if "system_configs" not in insp.get_table_names():
                    return False

                def _get(key, default=None):
                    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
                    if not row:
                        return default
                    if row.config_type == "bool":
                        return row.config_value.lower() in ("true", "1", "yes")
                    elif row.config_type == "int":
                        try:
                            return int(row.config_value)
                        except:
                            return default
                    return row.config_value or default

                self.enabled = bool(_get("proxy_enabled", False))
                self.list_conf = str(_get("proxy_http_list", "") or "").strip()
                self.provider_url = str(_get("proxy_provider_url", "") or "").strip()
                self.refresh_min = int(_get("proxy_refresh_minutes", 20) or 20)
                self.ttl_min = int(_get("proxy_ttl", 25) or 25)

                # 清空旧代理池，重新加载
                with self._lock:
                    self._proxies.clear()
                    self._rr_index = 0

                if self.enabled:
                    self._load_initial(force=True)
                    logger.info(f"[ProxyManager] 从DB重新加载: enabled={self.enabled}, proxies={len(self._proxies)}")
                else:
                    logger.info("[ProxyManager] 代理已禁用（DB配置）")
            finally:
                db.close()
            return True
        except Exception as e:
            logger.warning(f"[ProxyManager] 从DB重新加载失败: {e}")
            return False

    # ============== 主动健康检测 ==============

    _CHECK_URL = "https://httpbin.org/ip"
    _CHECK_TIMEOUT = 8

    def check_single_proxy(self, proxy_url: str) -> dict:
        """检测单个代理连通性：发请求到 httpbin.org/ip，返回检测结果"""
        import time as _time
        t0 = _time.monotonic()
        try:
            import requests as _rq
            resp = _rq.get(
                self._CHECK_URL,
                proxies={"http": proxy_url, "https": proxy_url},
                timeout=self._CHECK_TIMEOUT,
                headers={"User-Agent": "ProxyCheck/1.0"},
            )
            latency = int((_time.monotonic() - t0) * 1000)
            ok = resp.status_code == 200
            ip = ""
            try:
                ip = resp.json().get("origin", "")
            except Exception:
                pass
            return {"ok": ok, "latency_ms": latency, "ip": ip, "error": None if ok else f"HTTP_{resp.status_code}"}
        except _TIMEOUT_EXC as e:
            latency = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "ip": "", "error": f"timeout:{e.__class__.__name__}"}
        except PROXY_LAYER_EXCEPTIONS as e:
            latency = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "ip": "", "error": f"proxy:{e.__class__.__name__}"}
        except Exception as e:
            latency = int((_time.monotonic() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "ip": "", "error": f"other:{e.__class__.__name__}"}

    def check_all_proxies(self) -> dict:
        """并发检测所有代理，更新 last_check_ok/last_check_at/check_latency_ms"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with self._lock:
            all_entries = list(self._proxies.items())

        if not all_entries:
            return {"total": 0, "ok": 0, "failed": 0, "results": []}

        results = []
        def _check_one(url, entry):
            r = self.check_single_proxy(url)
            with entry._lock:
                entry.last_check_at = datetime.now()
                entry.last_check_ok = r["ok"]
                entry.check_latency_ms = r["latency_ms"]
                if r["ok"]:
                    entry.consecutive_proxy_errors = 0
                    if not entry.is_active:
                        entry.is_active = True
                else:
                    entry.consecutive_proxy_errors += 1
                    if entry.consecutive_proxy_errors >= 3:
                        entry.is_active = False
            return {
                "url": self._mask(url),
                "ok": r["ok"],
                "latency_ms": r["latency_ms"],
                "ip": r["ip"],
                "error": r["error"],
                "last_check_at": entry.last_check_at.isoformat() if entry.last_check_at else None,
            }

        with ThreadPoolExecutor(max_workers=min(10, len(all_entries))) as ex:
            futures = {ex.submit(_check_one, url, entry): url for url, entry in all_entries}
            for fu in as_completed(futures):
                try:
                    results.append(fu.result())
                except Exception as e:
                    url = futures[fu]
                    results.append({"url": self._mask(url), "ok": False, "latency_ms": 0, "ip": "", "error": str(e), "last_check_at": None})

        ok_count = sum(1 for r in results if r["ok"])
        failed_count = len(results) - ok_count
        logger.info(f"[ProxyManager] 健康检测完成: {ok_count}/{len(results)} 正常")
        return {
            "total": len(results),
            "ok": ok_count,
            "failed": failed_count,
            "results": results,
        }

    # ============== 内部：加载 / 刷新 / 轮询 ==============

    def _load_initial(self, force: bool = False) -> None:
        added = 0
        # 方式 1：PROXY_HTTP_LIST 静态列表
        if self.list_conf:
            for raw in self.list_conf.split(","):
                u = raw.strip()
                if u and self._add(u):
                    added += 1
        # 方式 2：PROXY_PROVIDER_URL 远程拉
        if self.provider_url:
            got = self._fetch_provider_list()
            for u in got:
                if self._add(u):
                    added += 1
        self._last_refresh_at = datetime.now()
        logger.info(
            f"[ProxyManager] 初始化完成，可用代理 {self._active_count_now()}/{len(self._proxies)} "
            f"(本次新增 {added})"
        )

    def _refresh_if_due(self) -> None:
        if not (self.provider_url or self.list_conf):
            return
        with self._lock:
            if (self._last_refresh_at and
                    (datetime.now() - self._last_refresh_at).total_seconds()
                    < self.refresh_min * 60):
                return
        # 重新加载（保留已有状态，仅把新加的加进去）
        added = 0
        if self.list_conf:
            for raw in self.list_conf.split(","):
                u = raw.strip()
                if u and self._add(u):
                    added += 1
        if self.provider_url:
            for u in self._fetch_provider_list():
                if self._add(u):
                    added += 1
        self._last_refresh_at = datetime.now()
        logger.info(f"[ProxyManager] 刷新完成，新增 {added} 个候选")

    def _fetch_provider_list(self) -> List[str]:
        """从订阅URL拉代理，支持：纯文本/JSON/Base64编码/Clash YAML"""
        if not self.provider_url:
            return []
        try:
            import requests as _rq
            resp = _rq.get(
                self.provider_url,
                timeout=min(10, max(5, self.fetch_timeout_sec)),
                headers={"User-Agent": "Mozilla/5.0 ClashforWindows/0.20.39"},
            )
            resp.raise_for_status()
            text = (resp.text or "").strip()
        except Exception as e:
            logger.warning(f"[ProxyManager] 拉取订阅 {self.provider_url} 失败：{e}")
            return []
        if not text:
            return []

        # 1. 尝试 Base64 解码（V2Ray/SS 订阅常用格式）
        if not text.startswith("[") and not text.startswith("{") and not text.startswith("<"):
            try:
                import base64
                # 清理可能的 padding 问题
                padded = text + "=" * (4 - len(text) % 4) if len(text) % 4 else text
                decoded = base64.b64decode(padded).decode("utf-8", errors="ignore").strip()
                if decoded and (":" in decoded or "://" in decoded or "\n" in decoded):
                    text = decoded
                    logger.info(f"[ProxyManager] 订阅内容Base64解码成功，长度={len(text)}")
            except Exception:
                pass

        # 2. JSON 格式
        if text.startswith("[") or text.startswith("{"):
            try:
                import json as _json
                obj = _json.loads(text)
                if isinstance(obj, list):
                    arr = obj
                elif isinstance(obj, dict):
                    for k in ("data", "proxies", "result", "items", "list"):
                        if isinstance(obj.get(k), list):
                            arr = obj[k]; break
                    else:
                        arr = []
                else:
                    arr = []
                out: List[str] = []
                for x in arr:
                    if isinstance(x, str):
                        out.append(x)
                    elif isinstance(x, dict):
                        for k in ("proxy", "url", "addr", "address", "host"):
                            if isinstance(x.get(k), str) and x[k]:
                                out.append(x[k]); break
                result = [self._normalize(x) for x in out if self._normalize(x)]
                if result:
                    return result
            except Exception:
                pass

        # 3. Clash YAML 格式（proxies: 段）
        if "proxies:" in text and ("server:" in text or "type:" in text):
            return self._parse_clash_yaml(text)

        # 4. 纯文本一行一个（含 ss:// vmess:// 等协议前缀的也尝试提取）
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        out = []
        for ln in lines:
            n = self._normalize(ln)
            if n:
                out.append(n)
        return out

    def _parse_clash_yaml(self, text: str) -> List[str]:
        """解析 Clash YAML 格式的 proxies 段，提取 http/socks5 代理"""
        out: List[str] = []
        in_proxies = False
        current: dict = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 段落标记
            if stripped == "proxies:" or stripped.startswith("proxies:"):
                in_proxies = True
                continue
            if not in_proxies:
                continue
            # 新段开始（非 proxies 段）
            if not line.startswith(" ") and not line.startswith("\t") and not stripped.startswith("-"):
                in_proxies = False
                continue
            # 解析 key: value
            if stripped.startswith("- "):
                # 新代理项
                if current:
                    url = self._clash_entry_to_url(current)
                    if url:
                        out.append(url)
                current = {}
                rest = stripped[2:].strip()
                if ":" in rest:
                    k, v = rest.split(":", 1)
                    current[k.strip()] = v.strip().strip('"').strip("'")
            elif ":" in stripped:
                k, v = stripped.split(":", 1)
                current[k.strip()] = v.strip().strip('"').strip("'")
        # 最后一条
        if current:
            url = self._clash_entry_to_url(current)
            if url:
                out.append(url)
        logger.info(f"[ProxyManager] Clash YAML解析: 提取 {len(out)} 个代理")
        return out

    @staticmethod
    def _clash_entry_to_url(d: dict) -> Optional[str]:
        """把 Clash 代理条目转为 requests 可用的 URL"""
        server = d.get("server", "").strip()
        port = d.get("port", "").strip()
        ptype = d.get("type", "").strip().lower()
        username = d.get("username", "").strip()
        password = d.get("password", "").strip()
        if not server or not port:
            return None
        # 只支持 http 和 socks5 类型（ss/vmess/trojan 需要本地客户端转换）
        if ptype in ("http", "https"):
            scheme = "https" if ptype == "https" else "http"
        elif ptype in ("socks5", "socks4", "socks5"):
            scheme = "socks5"
        else:
            return None
        auth = f"{username}:{password}@" if username and password else ""
        url = f"{scheme}://{auth}{server}:{port}"
        return ProxyManager._normalize(url)

    def _add(self, url: str) -> bool:
        url = self._normalize(url)
        if not url:
            return False
        with self._lock:
            if url in self._proxies:
                # 已存在：仅把 inactive 复活（如果之前被打死）
                p = self._proxies[url]
                if not p.is_active and p.consecutive_proxy_errors >= 3:
                    p.is_active = True
                    p.consecutive_proxy_errors = 0
                    return True
                return False
            proto = self._guess_proto(url)
            self._proxies[url] = ProxyEntry(url=url, protocol=proto)
            return True

    def _pick_next_rr(self) -> Optional[ProxyEntry]:
        with self._lock:
            items = list(self._proxies.values())
            n = len(items)
            if n == 0:
                return None
            for _ in range(n):
                self._rr_index = (self._rr_index + 1) % n
                return items[self._rr_index]
            return None

    def _active_count_now(self) -> int:
        return sum(1 for p in self._proxies.values() if p.is_active)

    # ============== 工具 ==============

    @staticmethod
    def _normalize(url: str) -> str:
        if not url:
            return ""
        u = url.strip()
        if not u:
            return ""
        # 允许 user:pass@host:port → 自动补 http://
        if "://" not in u and "@" in u and ":" in u.split("@", 1)[1]:
            u = "http://" + u
        elif "://" not in u and ":" in u:
            # 只剩 host:port
            u = "http://" + u
        try:
            p = urlparse(u)
            if p.scheme not in ("http", "https", "socks5", "socks4", "socks5h"):
                return ""
            if not p.hostname:
                return ""
            return u
        except Exception:
            return ""

    @staticmethod
    def _guess_proto(url: str) -> str:
        try:
            return urlparse(url).scheme or "http"
        except Exception:
            return "http"

    @staticmethod
    def _mask(url: str) -> str:
        """日志里把 user:pass 打码，避免明文泄露"""
        try:
            p = urlparse(url)
            if p.username or p.password:
                auth = "***:***@"
            else:
                auth = ""
            port = f":{p.port}" if p.port else ""
            return f"{p.scheme}://{auth}{p.hostname}{port}{p.path}"
        except Exception:
            return "***"


# ---------- 一个 requests 包装：自动用 ProxyManager + 自动区分业务失败/代理失败 ----------
def requests_get_with_proxy(url: str, *, params=None, headers=None, timeout=15,
                            host: str = "", as_json: bool = False,
                            expect_nonempty_html: bool = False,
                            retries_if_business_empty: int = 1,
                            session=None):
    """
    爬虫侧"一键走代理"的包装。

    - 参数与 requests.get 几乎一致
    - 自动从 ProxyManager.acquire() 拿代理
    - 代理层错误 → mark_proxy_layer_error，然后拿新的代理重试 1 次，最后直连
    - 业务空页（HTTP200 但内容 < 200 字节 / RSS 0 条目）→ mark_business_retry，不杀代理
    - expect_nonempty_html=True 时如果内容太短就判业务空
    """
    import requests as _rq
    if not host:
        try:
            host = urlparse(url).hostname or url
        except Exception:
            host = url

    def _do(use_proxy: Optional[str]) -> tuple[object, Optional[str], Optional[str]]:
        """返回 (response_or_parsed_json, proxy_url_used, error_reason)"""
        if use_proxy:
            proxies = {"http": use_proxy, "https": use_proxy}
        else:
            proxies = None  # 直连
        sess = session or _rq
        try:
            resp = sess.get(
                url, params=params, headers=headers, timeout=timeout,
                proxies=proxies,
                allow_redirects=True,
            )
        except PROXY_LAYER_EXCEPTIONS as e:
            # 代理层错误：计数，下一轮切代理/直连
            ProxyManager.get_instance().mark_proxy_layer_error(use_proxy, host, e)
            return None, use_proxy, f"proxy_error:{e.__class__.__name__}"
        except _TIMEOUT_EXC as e:
            ProxyManager.get_instance().mark_proxy_layer_error(use_proxy, host, e)
            return None, use_proxy, f"timeout:{e.__class__.__name__}"
        except Exception as e:
            return None, use_proxy, f"other:{e.__class__.__name__}"

        # 403 / 429 等限流 —— 经验上是源站对代理 IP 的拒绝，算代理层
        if resp.status_code in (403, 429, 407, 502, 503, 504):
            ProxyManager.get_instance().mark_proxy_layer_error(
                use_proxy, host,
                RuntimeError(f"HTTP_{resp.status_code}")
            )
            return None, use_proxy, f"http_{resp.status_code}"

        try:
            resp.raise_for_status()
        except Exception:
            return None, use_proxy, f"http_{resp.status_code}"

        # 业务空页判定（HTTP200 但内容过短）
        text = ""
        try:
            text = resp.text or ""
        except Exception:
            text = ""
        if expect_nonempty_html and len(text) < 200:
            ProxyManager.get_instance().mark_business_retry(
                use_proxy, host, reason=f"content_too_short:{len(text)}"
            )
            return None, use_proxy, "content_too_short"

        ProxyManager.get_instance().mark_success(use_proxy, host)

        if as_json:
            try:
                return resp.json(), use_proxy, None
            except Exception as e:
                ProxyManager.get_instance().mark_business_retry(
                    use_proxy, host, reason=f"json_decode:{e}"
                )
                return None, use_proxy, f"json_decode:{e.__class__.__name__}"
        return resp, use_proxy, None

    # 候选顺序：代理A → 代理B（上次代理失败就换）→ 直连
    candidates: List[Optional[str]] = []
    pm = ProxyManager.get_instance()
    first_proxy = pm.acquire(host)
    if first_proxy:
        candidates.append(first_proxy)
        # 再给一个备选代理（如果 A 出代理层错误，再试 B 一次）
        second = pm.acquire(host)
        if second and second != first_proxy:
            candidates.append(second)
    # 最后一定走直连兜底
    candidates.append(None)

    last_reason = None
    for cand in candidates:
        obj, used, err = _do(cand)
        if obj is not None:
            return obj
        last_reason = err
        # 业务级空页：再用同一代理多试 retries_if_business_empty 次（不换IP）
        if (err and err.startswith("content") and retries_if_business_empty > 0
                and cand is not None):
            for _i in range(retries_if_business_empty):
                obj2, used2, err2 = _do(cand)
                if obj2 is not None:
                    return obj2
                last_reason = err2
    return None
