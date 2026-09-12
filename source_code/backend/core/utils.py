"""
通用工具函数合集
- 确定性哈希（避免Python内置hash漂移）
- 密码哈希/校验（BCrypt）
- JWT Token 生成/解码
- 字符串/数字/日期辅助
"""
import hashlib
import uuid
import secrets
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
from decimal import Decimal, ROUND_HALF_UP

import jwt
import bcrypt

from backend.config import get_settings

settings = get_settings()

# ============== 密码哈希 ==============
# 直接使用 bcrypt 库（passlib 1.7.4 与 bcrypt 4.x/5.x 不兼容：
# bcrypt 4+ 移除了 __about__，passlib 探测失败后 fallback 路径会触发
# "password cannot be longer than 72 bytes" 硬错误。直接调 bcrypt 更稳）
_BCRYPT_ROUNDS = 12


def hash_password(raw: str) -> str:
    pw = raw.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


# ============== 确定性哈希（用于索引/缓存Key/订单号） ==============

def md5_hex(text: Any) -> str:
    """确定性 MD5（跨进程/重启一致）"""
    s = str(text).encode("utf-8", errors="ignore")
    return hashlib.md5(s).hexdigest()


def sha1_hex(text: Any) -> str:
    s = str(text).encode("utf-8", errors="ignore")
    return hashlib.sha1(s).hexdigest()


def sha256_hex(text: Any) -> str:
    s = str(text).encode("utf-8", errors="ignore")
    return hashlib.sha256(s).hexdigest()


def gen_client_order_id(prefix: str = "T") -> str:
    """生成交易所客户端订单号（确定性+唯一）"""
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
    rand = secrets.token_hex(3)
    return f"{prefix}{ts}{rand}".upper()[:32]


# ============== JWT ==============

def create_access_token(subject: Union[str, int], extra: Optional[dict] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(subject),
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.APP_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: Union[str, int]) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(subject),
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.APP_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """解码JWT，失败抛出 jwt.PyJWTError 子类"""
    return jwt.decode(
        token,
        settings.APP_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub", "type"]},
    )


# ============== 随机数/字符串 ==============

def random_string(n: int = 16, chars: Optional[str] = None) -> str:
    chars = chars or (string.ascii_letters + string.digits)
    return "".join(secrets.choice(chars) for _ in range(n))


def random_digits(n: int = 6) -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(n))


def gen_uuid() -> str:
    return uuid.uuid4().hex


# ============== 数值处理 ==============

def round_decimal(value: Any, digits: int = 4) -> Decimal:
    """四舍五入（银行家模式）"""
    d = Decimal(str(value))
    q = Decimal("1").scaleb(-digits)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return default


def pct_change(old: Any, new: Any) -> float:
    """涨跌百分比"""
    o, n = safe_float(old), safe_float(new)
    if o == 0:
        return 0.0
    return round((n - o) / abs(o) * 100, 4)


# ============== 时间 ==============

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ts_ms() -> int:
    """毫秒级时间戳"""
    return int(datetime.now().timestamp() * 1000)


def start_of_day(d: Optional[datetime] = None) -> datetime:
    d = d or datetime.now()
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(d: Optional[datetime] = None) -> datetime:
    d = d or datetime.now()
    return d.replace(hour=23, minute=59, second=59, microsecond=999999)


def date_key(d: Optional[datetime] = None) -> str:
    return (d or datetime.now()).strftime("%Y-%m-%d")


def week_key(d: Optional[datetime] = None) -> str:
    d = d or datetime.now()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def month_key(d: Optional[datetime] = None) -> str:
    return (d or datetime.now()).strftime("%Y-%m")


# ============== 列表/字典 ==============

def chunks(lst, n):
    """列表分块"""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]
