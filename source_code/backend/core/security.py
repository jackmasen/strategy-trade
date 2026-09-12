"""
统一安全模块：API Key 对称加密 / 解密 / 脱敏
遵循 936341 经验：全局唯一加密模块，禁止在其他文件重复实现算法
算法：cryptography.fernet (AES-128-CBC + HMAC-SHA256)
密钥：APP_SECRET_KEY 经 SHA-256 → 32 字节 → URL-safe base64（Fernet 标准格式）

延迟派生：Fernet key 不在模块加载时固化，而是每次调用时从 get_settings() 读取，
支持 APP_SECRET_KEY 热变更（.env 修改后无需重启即可用新密钥加解密）。
"""
import hashlib
import base64
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.config import get_settings


def _build_fernet_key(app_secret: str) -> bytes:
    """将任意长度的 APP_SECRET_KEY 映射为 Fernet 需要的 32B base64 key（确定性）"""
    digest = hashlib.sha256(app_secret.encode("utf-8")).digest()  # 32 bytes
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    """每次调用时从当前配置派生 Fernet 实例，支持 APP_SECRET_KEY 热变更"""
    settings = get_settings()
    return Fernet(_build_fernet_key(settings.APP_SECRET_KEY))


def encrypt_api_key(raw: Optional[str]) -> str:
    """加密明文 API Key；空值返回空串（与 DB 空串兼容）"""
    if not raw:
        return ""
    try:
        token = _get_fernet().encrypt(raw.encode("utf-8"))
        return token.decode("utf-8")
    except Exception:
        # 加密失败时不抛业务异常（避免 Key 泄露），返回占位并让上层视为"无效"
        return ""


def decrypt_api_key(encrypted: Optional[str]) -> str:
    """解密密文；空值/非法密文返回空串（不抛出，避免影响接口）"""
    if not encrypted:
        return ""
    try:
        raw = _get_fernet().decrypt(encrypted.encode("utf-8"))
        return raw.decode("utf-8")
    except InvalidToken:
        # APP_SECRET_KEY 变化导致旧密文失效（降级安全路径）
        return ""
    except Exception:
        return ""


def mask_api_key(raw: Optional[str]) -> str:
    """脱敏显示 Key：前4位 + ****。空值返回空。不会暴露明文。"""
    if not raw:
        return ""
    if len(raw) <= 4:
        return "*" * len(raw)
    return raw[:4] + "****"
