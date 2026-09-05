"""
邮件发送工具
基于系统配置的 SMTP 参数发送邮件（用于大资金预警、风控告警等）
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from email.header import Header
from typing import Optional

from backend.config import get_settings
from backend.core.logging_config import logger
from backend.core.security import decrypt_api_key


def _get_smtp_config() -> dict:
    """优先从数据库 system_configs 读取管理员配置的 SMTP，兜底回 .env"""
    smtp = {
        "host": "",
        "port": 465,
        "user": "",
        "password": "",
        "to": "",
        "ssl": True,
    }

    # 1) 尝试从数据库读取（管理员在设置页面配置的）
    try:
        from backend.db.session import SessionLocal
        from backend.models.system_config import SystemConfig

        db = SessionLocal()
        try:
            row = db.query(SystemConfig).filter(SystemConfig.config_key == "notify_smtp_host").first()
            if row and row.config_value:
                smtp["host"] = row.config_value
            row = db.query(SystemConfig).filter(SystemConfig.config_key == "notify_smtp_port").first()
            if row and row.config_value:
                smtp["port"] = int(row.config_value)
            row = db.query(SystemConfig).filter(SystemConfig.config_key == "notify_smtp_user").first()
            if row and row.config_value:
                smtp["user"] = row.config_value
            row = db.query(SystemConfig).filter(SystemConfig.config_key == "notify_smtp_pwd").first()
            if row and row.config_value:
                smtp["password"] = decrypt_api_key(row.config_value)
            row = db.query(SystemConfig).filter(SystemConfig.config_key == "notify_smtp_to").first()
            if row and row.config_value:
                smtp["to"] = row.config_value
            row = db.query(SystemConfig).filter(SystemConfig.config_key == "notify_smtp_ssl").first()
            if row and row.config_value:
                smtp["ssl"] = row.config_value.lower() in ("true", "1", "yes")
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[Email] 读取数据库SMTP配置失败，回退到.env: {e}")

    # 2) 数据库没有的字段，用 .env 兜底
    settings = get_settings()
    if not smtp["host"]:
        smtp["host"] = settings.SMTP_HOST
    if smtp["port"] == 465 and not settings.SMTP_HOST == "":
        pass  # 保持默认
    if not smtp["user"]:
        smtp["user"] = settings.SMTP_USER
        smtp["password"] = settings.SMTP_PASSWORD
    if not smtp["to"]:
        smtp["to"] = settings.SMTP_TO

    return smtp


def send_email(
    subject: str,
    body: str,
    to_addr: Optional[str] = None,
    is_html: bool = False,
) -> bool:
    """
    发送邮件

    Args:
        subject: 邮件主题
        body: 邮件正文
        to_addr: 收件人（留空则使用系统配置的 SMTP_TO）
        is_html: 是否为 HTML 格式

    Returns:
        bool: 是否发送成功
    """
    smtp = _get_smtp_config()
    smtp_host = smtp["host"]
    smtp_port = smtp["port"]
    smtp_pwd = smtp["password"]
    use_ssl = smtp["ssl"]

    # Sanitize ALL SMTP config fields: non-breaking spaces (U+00A0) and other
    # invisible Unicode whitespace can sneak in via copy-paste and break
    # smtplib's ASCII encoding (formataddr validates addresses as ASCII).
    smtp_host = smtp_host.replace("\xa0", " ").strip()
    smtp_user = smtp["user"].replace("\xa0", " ").strip()
    smtp_to = (to_addr or smtp["to"]).replace("\xa0", " ").strip()
    smtp_pwd = smtp_pwd.replace("\xa0", " ").strip()

    if not smtp_host or not smtp_user or not smtp_pwd or not smtp_to:
        logger.debug("[Email] SMTP 配置不完整，跳过邮件发送")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = formataddr(("策略交易系统", smtp_user))
        msg["To"] = smtp_to
        msg["Subject"] = Header(subject, "utf-8")

        content_type = "html" if is_html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        if use_ssl or smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            server.starttls()

        server.login(smtp_user, smtp_pwd)
        server.sendmail(smtp_user, [a.strip() for a in smtp_to.split(",") if a.strip()], msg.as_string())
        server.quit()

        logger.info(f"[Email] 邮件发送成功: {subject} -> {smtp_to}")
        return True

    except Exception as e:
        logger.error(f"[Email] 邮件发送失败: {e}")
        return False


def send_whale_alert_email(
    symbol: str,
    side: str,          # "buy" or "sell"
    price: float,
    quote_qty: float,
    timestamp_ms: int,
) -> bool:
    """
    发送大资金异动预警邮件

    Args:
        symbol: 交易对
        side: 方向 buy/sell
        price: 价格
        quote_qty: 成交金额(USDT)
        timestamp_ms: 时间戳(毫秒)
    """
    from datetime import datetime

    dt = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
    side_cn = "大单买入" if side == "buy" else "大单卖出"
    emoji = "📈" if side == "buy" else "📉"
    color = "#25D07D" if side == "buy" else "#EF4444"

    subject = f"{emoji} {side_cn}预警 - {symbol} ${quote_qty:,.0f}"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0F172A; padding: 24px; border-radius: 12px; color: #E2E8F0;">
        <div style="text-align: center; padding: 20px 0; border-bottom: 1px solid #1E293B;">
            <div style="font-size: 48px; margin-bottom: 12px;">{emoji}</div>
            <div style="font-size: 24px; font-weight: bold; color: {color};">{side_cn}预警</div>
            <div style="font-size: 14px; color: #94A3B8; margin-top: 8px;">{symbol}</div>
        </div>

        <div style="padding: 24px 0;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 12px 0; color: #94A3B8; border-bottom: 1px solid #1E293B;">成交价格</td>
                    <td style="padding: 12px 0; text-align: right; font-weight: bold; border-bottom: 1px solid #1E293B;">{price:,.4f} USDT</td>
                </tr>
                <tr>
                    <td style="padding: 12px 0; color: #94A3B8; border-bottom: 1px solid #1E293B;">成交金额</td>
                    <td style="padding: 12px 0; text-align: right; font-weight: bold; font-size: 18px; color: {color}; border-bottom: 1px solid #1E293B;">${quote_qty:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 12px 0; color: #94A3B8; border-bottom: 1px solid #1E293B;">发生时间</td>
                    <td style="padding: 12px 0; text-align: right; border-bottom: 1px solid #1E293B;">{dt}</td>
                </tr>
            </table>
        </div>

        <div style="text-align: center; padding: 16px; background: #1E293B; border-radius: 8px; font-size: 12px; color: #64748B;">
            此邮件由策略交易系统自动发送，请勿直接回复
        </div>
    </div>
    """

    return send_email(subject, html, is_html=True)
