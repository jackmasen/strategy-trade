"""
Telegram Bot 消息推送
通过 Telegram Bot API 发送告警消息，支持 Markdown 格式和分级告警
"""
import time
import httpx
from typing import Optional

from backend.config import get_settings
from backend.core.logging_config import logger

_last_tg_error_time: float = 0.0
TG_ERROR_THROTTLE_SEC = 300

API_BASE = "https://api.telegram.org"


def _get_tg_config() -> dict:
    """从数据库 system_configs 读取 Telegram 配置，兜底回 .env"""
    cfg = {"bot_token": "", "chat_id": "", "enabled": True}
    try:
        from backend.db.session import SessionLocal
        from backend.models.system_config import SystemConfig

        db = SessionLocal()
        try:
            for key, field in [
                ("notify_tg_bot_token", "bot_token"),
                ("notify_tg_chat_id", "chat_id"),
                ("notify_tg_enabled", "enabled"),
            ]:
                row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
                if row and row.config_value:
                    if field == "enabled":
                        cfg[field] = row.config_value.lower() in ("true", "1", "yes")
                    else:
                        cfg[field] = row.config_value
        finally:
            db.close()
    except Exception:
        pass

    settings = get_settings()
    if not cfg["bot_token"]:
        cfg["bot_token"] = settings.TELEGRAM_BOT_TOKEN
    if not cfg["chat_id"]:
        cfg["chat_id"] = settings.TELEGRAM_CHAT_ID
    return cfg


def send_telegram(
    text: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    disable_preview: bool = True,
) -> bool:
    """
    发送 Telegram 消息

    Args:
        text: 消息内容（支持 HTML/Markdown 格式）
        chat_id: 目标 chat_id（留空使用系统配置）
        parse_mode: 解析模式 HTML / Markdown / 空
        disable_preview: 是否禁用链接预览
    """
    cfg = _get_tg_config()
    if not cfg.get("enabled", True):
        return False

    bot_token = cfg["bot_token"]
    target_chat = chat_id or cfg["chat_id"]
    if not bot_token or not target_chat:
        logger.debug("[Telegram] 配置不完整，跳过发送")
        return False

    url = f"{API_BASE}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info(f"[Telegram] 消息发送成功 -> {target_chat}")
                return True
            else:
                logger.warning(f"[Telegram] 发送失败 HTTP {resp.status_code}: {resp.text[:200]}")
                return False
    except Exception as e:
        global _last_tg_error_time
        now = time.time()
        if now - _last_tg_error_time > TG_ERROR_THROTTLE_SEC:
            logger.error(f"[Telegram] 发送异常: {e}")
            _last_tg_error_time = now
        else:
            logger.debug(f"[Telegram] 发送异常(限流): {e}")
        return False
