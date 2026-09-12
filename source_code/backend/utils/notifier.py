"""
统一告警通知管理器
分级告警策略：
  - severity 1 (Info):    Telegram 推送
  - severity 2 (Warning): Telegram + Email
  - severity 3 (Critical): Telegram + Email + DingTalk + Feishu（全渠道）
"""
from datetime import datetime
from typing import Optional

from backend.config import get_settings
from backend.core.logging_config import logger

SEVERITY_INFO = 1
SEVERITY_WARNING = 2
SEVERITY_CRITICAL = 3

_SEVERITY_LABELS = {1: "ℹ️ Info", 2: "⚠️ Warning", 3: "🚨 Critical"}
_SEVERITY_EMOJIS = {1: "ℹ️", 2: "⚠️", 3: "🚨"}


def _format_tg_message(severity: int, title: str, detail: str) -> str:
    label = _SEVERITY_LABELS.get(severity, "ℹ️ Info")
    emoji = _SEVERITY_EMOJIS.get(severity, "ℹ️")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"{emoji} <b>{label}</b>\n"
        f"<b>{title}</b>\n"
        f"<pre>{detail}</pre>\n"
        f"<i>{now_str}</i>"
    )


def _format_email_body(severity: int, title: str, detail: str) -> str:
    label = _SEVERITY_LABELS.get(severity, "Info")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    color = {1: "#3B82F6", 2: "#F59E0B", 3: "#EF4444"}.get(severity, "#3B82F6")
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0F172A;padding:24px;border-radius:12px;color:#E2E8F0;">
        <div style="text-align:center;padding:20px 0;border-bottom:1px solid #1E293B;">
            <div style="font-size:24px;font-weight:bold;color:{color};">{label}</div>
        </div>
        <div style="padding:24px 0;">
            <h2 style="color:#F1F5F9;">{title}</h2>
            <div style="background:#1E293B;padding:16px;border-radius:8px;color:#CBD5E1;font-size:14px;line-height:1.6;">
                {detail}
            </div>
        </div>
        <div style="text-align:center;padding:16px;background:#1E293B;border-radius:8px;font-size:12px;color:#64748B;">
            {now_str} · 策略交易系统自动告警
        </div>
    </div>
    """


def send_dingtalk(text: str) -> bool:
    """发送钉钉 webhook 告警"""
    settings = get_settings()
    webhook = settings.DINGTALK_WEBHOOK
    if not webhook:
        return False
    try:
        import httpx
        with httpx.Client(timeout=10) as client:
            resp = client.post(webhook, json={
                "msgtype": "text",
                "text": {"content": text},
            })
            return resp.status_code == 200
    except Exception as e:
        logger.debug(f"[DingTalk] 发送失败: {e}")
        return False


def send_feishu(text: str) -> bool:
    """发送飞书 webhook 告警"""
    settings = get_settings()
    webhook = settings.FEISHU_WEBHOOK
    if not webhook:
        return False
    try:
        import httpx
        with httpx.Client(timeout=10) as client:
            resp = client.post(webhook, json={
                "msg_type": "text",
                "content": {"text": text},
            })
            return resp.status_code == 200
    except Exception as e:
        logger.debug(f"[Feishu] 发送失败: {e}")
        return False


def notify(
    title: str,
    detail: str,
    severity: int = SEVERITY_INFO,
    channels: Optional[list] = None,
) -> dict:
    """
    统一告警入口：根据 severity 自动选择渠道

    Args:
        title: 告警标题
        detail: 告警详情
        severity: 1=Info 2=Warning 3=Critical
        channels: 自定义渠道列表，如 ["telegram","email"]；留空按 severity 自动选择

    Returns:
        dict: 各渠道发送结果
    """
    results = {}

    if channels is None:
        if severity >= SEVERITY_CRITICAL:
            channels = ["telegram", "email", "dingtalk", "feishu"]
        elif severity == SEVERITY_WARNING:
            channels = ["telegram", "email"]
        else:
            channels = ["telegram"]

    tg_msg = _format_tg_message(severity, title, detail)
    email_html = _format_email_body(severity, title, detail)
    plain_text = f"[{_SEVERITY_LABELS.get(severity, 'Info')}] {title}\n{detail}"
    email_subject = f"[{_SEVERITY_LABELS.get(severity, 'Info')}] {title}"

    for ch in channels:
        try:
            if ch == "telegram":
                from backend.utils.telegram_util import send_telegram
                results["telegram"] = send_telegram(tg_msg)
            elif ch == "email":
                from backend.utils.email_util import send_email
                results["email"] = send_email(email_subject, email_html, is_html=True)
            elif ch == "dingtalk":
                results["dingtalk"] = send_dingtalk(plain_text)
            elif ch == "feishu":
                results["feishu"] = send_feishu(plain_text)
        except Exception as e:
            logger.warning(f"[Notifier] 渠道 {ch} 发送失败: {e}")
            results[ch] = False

    succeeded = [k for k, v in results.items() if v]
    logger.info(f"[Notifier] 告警已发送 severity={severity} channels={succeeded}/{channels}")
    return results


def notify_risk_event(
    symbol: str,
    event_type: str,
    severity: int,
    detail: str,
    pos_id: Optional[int] = None,
) -> dict:
    """便捷方法：发送风控事件告警"""
    title = f"{symbol} {event_type}"
    if pos_id:
        detail = f"持仓ID: {pos_id}\n{detail}"
    return notify(title, detail, severity=severity)
