"""
FastAPI 认证依赖
- get_current_user: 从 Authorization: Bearer <token> 解析并查库
- require_roles: 角色权限校验
"""
from typing import Optional
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import jwt

from backend.db.session import get_db
from backend.core.exceptions import UnauthorizedException, ForbiddenException
from backend.core.utils import decode_token
from backend.models.user import User


_bearer = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials],
) -> str:
    """优先从 Header，其次从 Cookie 取 Token"""
    if credentials and credentials.credentials:
        return credentials.credentials
    token = request.cookies.get("access_token")
    if token:
        return token
    raise UnauthorizedException("缺少登录凭证")


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """解析当前登录用户；未登录或无效抛出 401"""
    token = _extract_token(request, credentials)
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise UnauthorizedException("无效的Token类型")
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise UnauthorizedException("登录凭证无效")
    except (KeyError, ValueError, TypeError):
        raise UnauthorizedException("登录凭证格式错误")

    user = db.query(User).filter(User.id == user_id, User.status == 1).first()
    if not user:
        raise UnauthorizedException("用户不存在或已被禁用")
    return user


def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """可选解析用户（匿名接口也可访问，有Token则返回用户）"""
    try:
        return get_current_user(request, credentials, db)
    except Exception:
        return None


class RequireRole:
    """角色权限装饰器/依赖"""

    def __init__(self, *allowed_roles: int):
        self.allowed = set(allowed_roles)

    def __call__(self, user: User = Depends(get_current_user)) -> User:
        # 超级管理员(1) 拥有所有权限
        if user.role == 1 or user.role in self.allowed:
            return user
        raise ForbiddenException(f"需要角色: {sorted(self.allowed)}，当前角色: {user.role}")


# 常用角色常量
ROLE_ADMIN = 1
ROLE_OPERATOR = 2
ROLE_VIEWER = 3

# 便捷依赖：仅管理员
require_admin = RequireRole(ROLE_ADMIN)
require_editor = RequireRole(ROLE_ADMIN, ROLE_OPERATOR)
require_trader = RequireRole(ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)
# 所有登录用户
require_login = get_current_user
