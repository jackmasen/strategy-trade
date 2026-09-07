"""
系统配置路由
- 系统配置 CRUD（key-value模式）
- SMTP 邮件配置 + 测试
- AI 连接测试
"""
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr
from email.header import Header
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.core.auth import get_current_user, require_admin
from backend.core.exceptions import ParameterException, success
from backend.core.logging_config import logger
from backend.core.security import encrypt_api_key, decrypt_api_key, mask_api_key
from backend.models.user import User
from backend.models.system_config import SystemConfig
from backend.models.ai_config import AIConfig
from backend.services.ai_client import AIClient

router = APIRouter(prefix="/settings", tags=["系统配置"])


# ============= 工具函数 =============

def _ensure_table(db: Session):
    """确保 system_configs 表存在"""
    from sqlalchemy import inspect as sa_inspect
    from backend.db.session import engine_sync
    insp = sa_inspect(engine_sync)
    if "system_configs" not in insp.get_table_names():
        SystemConfig.__table__.create(bind=engine_sync, checkfirst=True)
        logger.info("[Settings] 自动创建 system_configs 表成功")


def _get_config(db: Session, key: str) -> Optional[SystemConfig]:
    _ensure_table(db)
    return db.query(SystemConfig).filter(SystemConfig.config_key == key).first()


def _get_config_value(db: Session, key: str, default: Any = None) -> Any:
    cfg = _get_config(db, key)
    if not cfg:
        return default
    if cfg.config_type == "json":
        try:
            return json.loads(cfg.config_value) if cfg.config_value else default
        except:
            return default
    elif cfg.config_type == "int":
        try:
            return int(cfg.config_value)
        except:
            return default
    elif cfg.config_type == "bool":
        return cfg.config_value.lower() in ("true", "1", "yes")
    elif cfg.config_type == "encrypted":
        return decrypt_api_key(cfg.config_value) if cfg.config_value else ""
    return cfg.config_value or default


def _set_config(db: Session, key: str, value: Any, config_type: str = "string",
                category: str = "general", description: str = "", user_id: int = None):
    """设置配置项（不存在则创建，存在则更新）"""
    _ensure_table(db)
    cfg = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()

    # 根据类型序列化值
    if config_type == "json":
        stored_value = json.dumps(value, ensure_ascii=False)
    elif config_type == "encrypted":
        stored_value = encrypt_api_key(value) if value else ""
    elif config_type == "bool":
        stored_value = "true" if value else "false"
    else:
        stored_value = str(value) if value is not None else ""

    if cfg:
        cfg.config_value = stored_value
        cfg.config_type = config_type
        cfg.category = category
        cfg.description = description or cfg.description
        cfg.updated_by = user_id
    else:
        cfg = SystemConfig(
            config_key=key,
            config_value=stored_value,
            config_type=config_type,
            category=category,
            description=description,
            updated_by=user_id,
        )
        db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def _get_category_configs(db: Session, category: str) -> Dict[str, Any]:
    """获取某分类下的所有配置"""
    _ensure_table(db)
    rows = db.query(SystemConfig).filter(SystemConfig.category == category).all()
    result = {}
    for r in rows:
        if r.config_type == "json":
            try:
                result[r.config_key] = json.loads(r.config_value) if r.config_value else None
            except:
                result[r.config_key] = None
        elif r.config_type == "int":
            try:
                result[r.config_key] = int(r.config_value)
            except:
                result[r.config_key] = 0
        elif r.config_type == "bool":
            result[r.config_key] = r.config_value.lower() in ("true", "1", "yes")
        elif r.config_type == "encrypted":
            # 加密字段返回 mask + has_value
            plain = decrypt_api_key(r.config_value) if r.config_value else ""
            result[r.config_key] = {
                "has_value": bool(plain),
                "masked": mask_api_key(plain),
            }
        else:
            result[r.config_key] = r.config_value or ""
    return result


# ============= Pydantic 模型 =============

class NotifyConfigUpdate(BaseModel):
    dingtalk: str = ""
    feishu: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pwd: str = ""  # 空串=不修改
    smtp_to: str = ""
    smtp_ssl: bool = True
    events: List[str] = Field(default_factory=lambda: ["tp", "sl", "risk", "daily"])


class SmtpTestReq(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pwd: str
    smtp_to: str
    smtp_ssl: bool = True


class AITestReq(BaseModel):
    provider: str = "custom"
    model_name: str = "gpt-4o"
    api_endpoint: str = ""
    api_key: str = ""


# ============= 系统配置 - 告警推送 =============

@router.get("/notify")
def get_notify_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取告警推送配置（SMTP密码加密返回mask）"""
    cfgs = _get_category_configs(db, "notify")

    # 返回结构
    result = {
        "dingtalk": cfgs.get("notify_dingtalk", "") or "",
        "feishu": cfgs.get("notify_feishu", "") or "",
        "smtp_host": cfgs.get("notify_smtp_host", "") or "",
        "smtp_port": cfgs.get("notify_smtp_port", 465) or 465,
        "smtp_user": cfgs.get("notify_smtp_user", "") or "",
        "smtp_pwd": cfgs.get("notify_smtp_pwd", {"has_value": False, "masked": ""}) or {"has_value": False, "masked": ""},
        "smtp_to": cfgs.get("notify_smtp_to", "") or "",
        "smtp_ssl": cfgs.get("notify_smtp_ssl", True) if isinstance(cfgs.get("notify_smtp_ssl"), bool) else True,
        "events": cfgs.get("notify_events", ["tp", "sl", "risk", "daily"]) or ["tp", "sl", "risk", "daily"],
    }
    return success(result)


# ============= 演示API配置（币安公共行情，用于演示） =============

class DemoApiUpdate(BaseModel):
    enabled: bool = False
    exchange: str = "binance"  # binance / okx
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    api_endpoint: str = ""


class DemoApiTestReq(BaseModel):
    exchange: str = "binance"
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True


@router.get("/demo-api")
def get_demo_api_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取演示API配置（敏感字段加密返回mask）"""
    cfgs = _get_category_configs(db, "demo_api")
    pwd_info = cfgs.get("demo_api_secret", {"has_value": False, "masked": ""})
    if not isinstance(pwd_info, dict):
        pwd_info = {"has_value": False, "masked": ""}
    result = {
        "enabled": cfgs.get("demo_api_enabled", False) if isinstance(cfgs.get("demo_api_enabled"), bool) else False,
        "exchange": cfgs.get("demo_api_exchange", "binance") or "binance",
        "api_key": cfgs.get("demo_api_key", "") or "",
        "api_secret_has_value": pwd_info.get("has_value", False),
        "api_secret_masked": pwd_info.get("masked", ""),
        "testnet": cfgs.get("demo_api_testnet", True) if isinstance(cfgs.get("demo_api_testnet"), bool) else True,
        "api_endpoint": cfgs.get("demo_api_endpoint", "") or "",
    }
    return success(result)


@router.put("/demo-api")
def update_demo_api_config(
    req: DemoApiUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新演示API配置"""
    _set_config(db, "demo_api_enabled", req.enabled,
                "bool", "demo_api", "是否启用演示API", user.id)
    _set_config(db, "demo_api_exchange", req.exchange or "binance",
                "string", "demo_api", "演示API交易所", user.id)
    _set_config(db, "demo_api_key", req.api_key or "",
                "string", "demo_api", "演示API Key", user.id)
    # Secret：空串或mask值不修改
    if req.api_secret and not req.api_secret.startswith("****"):
        _set_config(db, "demo_api_secret", req.api_secret,
                    "encrypted", "demo_api", "演示API Secret(加密)", user.id)
    _set_config(db, "demo_api_testnet", req.testnet,
                "bool", "demo_api", "是否测试网", user.id)
    _set_config(db, "demo_api_endpoint", req.api_endpoint or "",
                "string", "demo_api", "自定义API端点", user.id)

    # 启用后刷新 MarketManager 的演示 client
    if req.enabled:
        try:
            from backend.exchanges.market import MarketManager
            mm = MarketManager.get_instance()
            mm.reload_demo_client()
        except Exception as e:
            logger.warning(f"[Settings] 刷新演示API客户端失败: {e}")

    logger.info(f"[Settings] 管理员 {user.username} 更新了演示API配置, enabled={req.enabled}")
    return success(message="演示API配置已保存")


@router.post("/demo-api/test")
def test_demo_api(
    req: DemoApiTestReq,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试演示API连通性（拉取BTC最新价验证）"""
    # 如果 secret 是特殊标记，用已保存的
    secret_plain = req.api_secret.strip() if req.api_secret else ""
    if secret_plain == "__USE_EXISTING__":
        saved = _get_config_value(db, "demo_api_secret", "")
        secret_plain = saved or ""
        if not secret_plain:
            raise ParameterException("当前没有保存的API Secret，请先输入并保存")

    if not req.api_key:
        raise ParameterException("请输入 API Key")
    if not secret_plain:
        raise ParameterException("请输入 API Secret")

    try:
        from backend.exchanges.base import ExchangeClientBase
        client = ExchangeClientBase.create(
            exchange=1 if req.exchange == "binance" else 2,
            api_key=req.api_key,
            api_secret=secret_plain,
            passphrase="",
            testnet=req.testnet,
            exchange_account_id=0,
        )
        client.connect()
        ticker = client.fetch_ticker("BTC")
        client.close()
        return success({
            "success": True,
            "symbol": "BTC",
            "last_price": ticker.last_price,
            "exchange": req.exchange,
        }, message=f"连接成功！BTC 最新价: {ticker.last_price}")
    except Exception as e:
        logger.error(f"[Settings] 演示API测试失败: {e}")
        raise ParameterException(f"连接测试失败: {str(e)[:200]}")


@router.put("/notify")
def update_notify_config(
    req: NotifyConfigUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新告警推送配置"""
    _set_config(db, "notify_dingtalk", req.model_dump().get("dingtalk", "") or "",
                "string", "notify", "钉钉机器人Webhook", user.id)
    _set_config(db, "notify_feishu", req.model_dump().get("feishu", "") or "",
                "string", "notify", "飞书机器人Webhook", user.id)
    _set_config(db, "notify_smtp_host", req.smtp_host,
                "string", "notify", "SMTP服务器地址", user.id)
    _set_config(db, "notify_smtp_port", req.smtp_port,
                "int", "notify", "SMTP端口", user.id)
    _set_config(db, "notify_smtp_user", req.smtp_user,
                "string", "notify", "SMTP账号", user.id)
    # 密码：空串表示不改（前端传mask值时不覆盖）
    if req.smtp_pwd and not req.smtp_pwd.startswith("****"):
        _set_config(db, "notify_smtp_pwd", req.smtp_pwd,
                    "encrypted", "notify", "SMTP密码/授权码(加密)", user.id)
    _set_config(db, "notify_smtp_to", req.smtp_to,
                "string", "notify", "默认收件人(逗号分隔)", user.id)
    _set_config(db, "notify_smtp_ssl", req.smtp_ssl,
                "bool", "notify", "是否使用SSL/TLS", user.id)
    _set_config(db, "notify_events", req.model_dump().get("events", ["tp", "sl", "risk", "daily"]) or ["tp", "sl", "risk", "daily"],
                "json", "notify", "推送事件类型", user.id)

    logger.info(f"[Settings] 管理员 {user.username} 更新了告警推送配置")
    return success(message="告警配置已保存")


@router.post("/notify/test-smtp")
def test_smtp(
    req: SmtpTestReq,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试SMTP邮件发送

    smtp_pwd 特殊值:
    - __USE_EXISTING__: 使用数据库中已保存的密码
    """
    from backend.core.exceptions import build_response

    if not req.smtp_host:
        return build_response(1, "SMTP服务器地址不能为空", None)
    if not req.smtp_user:
        return build_response(1, "SMTP账号不能为空", None)
    if not req.smtp_to:
        return build_response(1, "收件人不能为空", None)

    # 处理密码
    pwd_plain = req.smtp_pwd.strip() if req.smtp_pwd else ""
    if pwd_plain == "__USE_EXISTING__":
        pwd_plain = _get_config_value(db, "notify_smtp_pwd", "")
        if not pwd_plain:
            return build_response(1, "当前没有保存的SMTP密码，请先输入并保存", None)

    if not pwd_plain:
        return build_response(1, "请输入SMTP密码/授权码", None)

    # 清洗密码中的非断空格等不可见字符
    pwd_plain = pwd_plain.replace("\xa0", " ").replace("\u200b", "").strip()
    # Gmail 应用密码含空格，smtplib 不需要去除，但需确保是 ASCII
    pwd_plain = pwd_plain.encode("ascii", errors="ignore").decode("ascii")

    try:
        smtp_user = req.smtp_user.replace("\xa0", " ").strip()
        smtp_to = req.smtp_to.replace("\xa0", " ").strip()

        msg = MIMEText(
            "这是一封来自策略交易系统的测试邮件。\n\n"
            "如果您收到这封邮件，说明SMTP配置正确。\n\n"
            "—— 策略交易系统",
            "plain", "utf-8"
        )
        msg["From"] = formataddr(("策略交易系统", smtp_user))
        msg["To"] = smtp_to
        msg["Subject"] = Header("【测试】策略交易系统 - SMTP配置验证", "utf-8")

        timeout = 30
        if req.smtp_ssl:
            server = smtplib.SMTP_SSL(req.smtp_host, req.smtp_port, timeout=timeout)
        else:
            server = smtplib.SMTP(req.smtp_host, req.smtp_port, timeout=timeout)
            server.starttls()

        server.login(smtp_user, pwd_plain)
        recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
        server.sendmail(smtp_user, recipients, msg.as_string())
        server.quit()

        logger.info(f"[Settings] SMTP测试成功: {req.smtp_host}")
        return success(message=f"测试邮件已发送至 {smtp_to}，请查收")
    except smtplib.SMTPAuthenticationError:
        return build_response(1, "SMTP认证失败，请检查账号和密码/授权码是否正确", None)
    except smtplib.SMTPConnectError as e:
        return build_response(1, f"无法连接SMTP服务器：{e}", None)
    except Exception as e:
        logger.error(f"[Settings] SMTP测试失败: {e}")
        return build_response(1, f"SMTP测试失败: {str(e)}", None)


# ============= AI 连接测试 =============

@router.post("/ai/test")
def test_ai_connection(
    req: AITestReq,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试AI API连接（用当前配置发一个简单请求）

    api_key 特殊值:
    - __USE_EXISTING__: 使用数据库中已保存的Key（前端测试时不传明文）
    """
    if not req.model_name:
        raise ParameterException("请输入模型名称")

    # 处理 Key
    api_key_plain = req.api_key.strip() if req.api_key else ""
    if api_key_plain == "__USE_EXISTING__":
        # 从数据库读取现有Key
        from backend.models.ai_config import AIConfig as _AICfg
        from backend.routers.analytics import _ensure_ai_config_table_and_row
        existing_cfg = _ensure_ai_config_table_and_row(db)
        api_key_plain = decrypt_api_key(existing_cfg.api_key_encrypted or "")
        if not api_key_plain:
            raise ParameterException("当前没有保存的API Key，请先输入并保存")

    if not api_key_plain:
        raise ParameterException("请输入有效的 API Key")

    try:
        # 构造一个临时 AIConfig
        cfg = AIConfig()
        cfg.provider = AIConfig.name_to_provider(req.provider)
        cfg.model_name = req.model_name.strip()
        cfg.api_endpoint = req.api_endpoint.strip()
        cfg.api_key_encrypted = encrypt_api_key(api_key_plain)
        cfg.temperature = 3
        cfg.max_tokens = 200
        cfg.request_timeout_sec = 15
        cfg.max_retries = 1

        client = AIClient(cfg)
        result = client.analyze(
            analysis_type="test",
            symbol="TEST",
            timeframe="1h",
            manual_prompt="请回复'连接成功'三个字，用于测试API连通性。",
            candles_snapshot="",
        )

        if result.success:
            # 测试成功，更新 last_verified_at
            from backend.models.ai_config import AIConfig as _AICfg2
            from backend.routers.analytics import _ensure_ai_config_table_and_row
            existing_cfg = _ensure_ai_config_table_and_row(db)
            existing_cfg.last_verified_at = datetime.utcnow()
            existing_cfg.last_error = ""
            db.commit()

            return success({
                "success": True,
                "response": result.reason[:200],
                "latency_ms": result.latency_ms,
            }, message="AI接口连接成功！")
        else:
            raise ParameterException(f"AI调用失败: {result.error_msg or '未知错误'}")
    except ParameterException:
        raise
    except Exception as e:
        logger.error(f"[Settings] AI连接测试失败: {e}")
        raise ParameterException(f"连接测试失败: {str(e)[:200]}")


# ============= 通用配置读取（其他分类按需添加） =============

@router.get("/general")
def get_general_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取通用配置"""
    cfgs = _get_category_configs(db, "general")
    result = {
        "app_name": cfgs.get("general_app_name", "策略交易系统") or "策略交易系统",
        "timezone": cfgs.get("general_timezone", "Asia/Shanghai") or "Asia/Shanghai",
        "ip_whitelist": cfgs.get("general_ip_whitelist", "") or "",
        "session_minutes": cfgs.get("general_session_minutes", 1440) or 1440,
        "audit_enabled": cfgs.get("general_audit_enabled", True) if isinstance(cfgs.get("general_audit_enabled"), bool) else True,
        "max_login_fail": cfgs.get("general_max_login_fail", 5) or 5,
    }
    return success(result)


# ============= 代理配置 =============

class ProxyConfigReq(BaseModel):
    enabled: bool = False
    http_list: str = ""
    provider_url: str = ""
    refresh_minutes: int = Field(default=20, ge=5, le=120)
    ttl: int = Field(default=25, ge=5, le=120)

@router.get("/proxy")
def get_proxy_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取代理配置"""
    enabled = _get_config_value(db, "proxy_enabled", False)
    http_list = _get_config_value(db, "proxy_http_list", "")
    provider_url = _get_config_value(db, "proxy_provider_url", "")
    refresh_minutes = _get_config_value(db, "proxy_refresh_minutes", 20)
    ttl = _get_config_value(db, "proxy_ttl", 25)
    return success({
        "enabled": bool(enabled),
        "http_list": http_list or "",
        "provider_url": provider_url or "",
        "refresh_minutes": int(refresh_minutes) if refresh_minutes else 20,
        "ttl": int(ttl) if ttl else 25,
    })

@router.put("/proxy")
def save_proxy_config(
    req: ProxyConfigReq,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """保存代理配置（含订阅URL），自动热重载代理池"""
    _set_config(db, "proxy_enabled", req.enabled, "bool", "proxy", "启用代理")
    _set_config(db, "proxy_http_list", req.http_list, "string", "proxy", "代理列表")
    _set_config(db, "proxy_provider_url", req.provider_url, "string", "proxy", "订阅URL")
    _set_config(db, "proxy_refresh_minutes", req.refresh_minutes, "int", "proxy", "刷新间隔分钟")
    _set_config(db, "proxy_ttl", req.ttl, "int", "proxy", "代理TTL分钟")
    db.commit()
    logger.info(f"[Settings] 代理配置已更新: enabled={req.enabled}, list_len={len(req.http_list)}, provider_url={'有' if req.provider_url else '无'}, ttl={req.ttl}")
    # 热重载代理池
    try:
        from backend.core.proxy_manager import ProxyManager
        pm = ProxyManager.get_instance()
        pm.reload_from_db()
    except Exception as e:
        logger.warning(f"[Settings] 代理热重载失败: {e}")
    return success({"message": "代理配置已保存并热重载"})

@router.get("/proxy/health")
def get_proxy_health(
    user: User = Depends(get_current_user),
):
    """获取代理池实时状态"""
    try:
        from backend.core.proxy_manager import ProxyManager
        pm = ProxyManager.get_instance()
        return success(pm.health_report())
    except Exception as e:
        return success({"enabled": False, "total": 0, "active": 0, "error": str(e)})

@router.post("/proxy/refresh")
def refresh_proxies_now(
    user: User = Depends(require_admin),
):
    """手动触发立即拉取订阅节点"""
    try:
        from backend.core.proxy_manager import ProxyManager
        pm = ProxyManager.get_instance()
        if not pm.enabled:
            return success({"message": "代理未启用", "added": 0})
        added = 0
        if pm.list_conf:
            for raw in pm.list_conf.split(","):
                u = raw.strip()
                if u and pm._add(u):
                    added += 1
        if pm.provider_url:
            fetched = pm._fetch_provider_list()
            for u in fetched:
                if pm._add(u):
                    added += 1
            pm._last_refresh_at = datetime.utcnow()
        logger.info(f"[Settings] 手动刷新代理: 新增 {added} 个")
        report = pm.health_report()
        return success({
            "message": f"刷新完成，新增 {added} 个代理",
            "added": added,
            "pool": report,
        })
    except Exception as e:
        return success({"message": f"刷新失败: {e}", "added": 0})

@router.post("/proxy/check-all")
def check_all_proxies(
    user: User = Depends(require_admin),
):
    """主动检测所有代理节点连通性（绿灯/红灯）"""
    try:
        from backend.core.proxy_manager import ProxyManager
        pm = ProxyManager.get_instance()
        if not pm.enabled:
            return success({"message": "代理未启用", "total": 0, "ok": 0, "failed": 0, "results": []})
        result = pm.check_all_proxies()
        logger.info(f"[Settings] 代理健康检测: {result['ok']}/{result['total']} 正常")
        return success(result)
    except Exception as e:
        return success({"message": f"检测失败: {e}", "total": 0, "ok": 0, "failed": 0, "results": []})

class TestFetchReq(BaseModel):
    url: str = ""

@router.post("/proxy/test-fetch")
def test_fetch_subscription(
    req: TestFetchReq,
    user: User = Depends(require_admin),
):
    """测试订阅URL拉取效果（不加入代理池，仅返回拉取到的节点列表）"""
    try:
        import requests as _rq
        import base64
        resp = _rq.get(
            req.url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 ClashforWindows/0.20.39"},
        )
        resp.raise_for_status()
        text = (resp.text or "").strip()
        raw_len = len(text)
        content_type = resp.headers.get("content-type", "")
        encoding = resp.encoding or ""

        # 尝试Base64解码
        decoded = False
        if not text.startswith("[") and not text.startswith("{") and not text.startswith("<"):
            try:
                padded = text + "=" * (4 - len(text) % 4) if len(text) % 4 else text
                d = base64.b64decode(padded).decode("utf-8", errors="ignore").strip()
                if d and (":" in d or "://" in d or "\n" in d):
                    text = d
                    decoded = True
            except Exception:
                pass

        # 用 ProxyManager 解析
        from backend.core.proxy_manager import ProxyManager
        pm = ProxyManager.get_instance()
        old_url = pm.provider_url
        pm.provider_url = req.url
        fetched = pm._fetch_provider_list()
        pm.provider_url = old_url

        return success({
            "raw_length": raw_len,
            "decoded": decoded,
            "content_type": content_type,
            "fetched_count": len(fetched),
            "proxies": [pm._mask(u) for u in fetched[:20]],
            "preview": text[:500],
        })
    except Exception as e:
        return success({"error": str(e), "fetched_count": 0, "proxies": []})


# ============= Xray 节点管理 =============

class XraySubReq(BaseModel):
    url: str = ""
    link: str = ""

@router.post("/xray/load-subscription")
def xray_load_subscription(
    req: XraySubReq,
    user: User = Depends(require_admin),
):
    """从订阅URL或节点链接加载Xray节点"""
    try:
        from backend.services.xray_manager import XrayManager
        mgr = XrayManager.get_instance()

        if req.link:
            result = mgr.load_subscription_from_link(req.link)
        elif req.url:
            result = mgr.load_subscription(req.url)
        else:
            return success({"error": "请提供订阅URL或节点链接", "parsed": 0})

        if "error" in result:
            return success(result)
        return success(result)
    except Exception as e:
        return success({"error": str(e), "parsed": 0})

@router.post("/xray/install")
def xray_install(user: User = Depends(require_admin)):
    """自动下载安装 Xray-core"""
    try:
        from backend.services.xray_manager import ensure_xray_installed
        result = ensure_xray_installed()
        return success(result)
    except Exception as e:
        return success({"installed": False, "error": str(e)})


@router.post("/xray/start-all")
def xray_start_all(user: User = Depends(require_admin)):
    """启动所有Xray节点"""
    try:
        from backend.services.xray_manager import XrayManager
        mgr = XrayManager.get_instance()
        result = mgr.start_all()
        # 启动后自动将本地代理加入 ProxyManager
        try:
            from backend.core.proxy_manager import ProxyManager
            pm = ProxyManager.get_instance()
            for url in mgr.get_proxy_urls():
                pm._add(url)
            logger.info(f"[Settings] Xray代理已加入ProxyManager: {len(mgr.get_proxy_urls())}个")
        except Exception as e:
            logger.warning(f"[Settings] 加入ProxyManager失败: {e}")
        return success(result)
    except Exception as e:
        return success({"error": str(e), "started": 0})

@router.post("/xray/stop-all")
def xray_stop_all(user: User = Depends(require_admin)):
    """停止所有Xray节点"""
    try:
        from backend.services.xray_manager import XrayManager
        mgr = XrayManager.get_instance()
        mgr.stop_all()
        return success({"message": "所有节点已停止"})
    except Exception as e:
        return success({"error": str(e)})

@router.get("/xray/status")
def xray_status(user: User = Depends(get_current_user)):
    """获取Xray所有节点状态"""
    try:
        from backend.services.xray_manager import XrayManager
        mgr = XrayManager.get_instance()
        return success(mgr.status_report())
    except Exception as e:
        return success({"error": str(e), "nodes": []})

@router.post("/xray/check-all")
def xray_check_all(user: User = Depends(require_admin)):
    """检测所有Xray节点连通性"""
    try:
        from backend.services.xray_manager import XrayManager
        mgr = XrayManager.get_instance()
        result = mgr.check_all_nodes()
        return success(result)
    except Exception as e:
        return success({"error": str(e), "total": 0, "ok": 0, "failed": 0, "results": []})
