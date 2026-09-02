"""
用户认证 + 用户管理 路由
POST   /auth/login          登录
POST   /auth/logout         登出
POST   /auth/refresh        刷新Token
GET    /users/me            当前用户信息
PUT    /users/me            修改自己的基础资料
PUT    /users/me/password   修改密码
GET    /users               用户列表(管理员)
POST   /users               创建用户(管理员)
PUT    /users/{uid}         修改用户(管理员, Body JSON)
DELETE /users/{uid}         删除用户(管理员)
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.db.session import get_db
from backend.core.auth import get_current_user, require_admin
from backend.core.exceptions import UnauthorizedException, ParameterException, success
from backend.core.utils import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from backend.core.schemas import BaseWithId, ApiResponse, PaginationParams, paginate
from backend.models.user import User

router = APIRouter(prefix="/auth", tags=["认证"])
user_router = APIRouter(prefix="/users", tags=["用户管理"])


# ============ 认证 ============

class LoginReq(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class LoginResp(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    # 注意：必须用 Any/dict 而非 BaseWithId | dict，否则 Pydantic Union 会
    # 优先匹配 BaseWithId，并因 BaseSchema.extra="ignore" 丢弃 username/role 等字段
    user: dict = {}


@router.post("/login", response_model=ApiResponse[LoginResp])
def login(req: LoginReq, db: Session = Depends(get_db), request: Request = None):
    """用户名密码登录"""
    user: User | None = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise UnauthorizedException("用户名或密码错误")
    if user.status != 1:
        raise UnauthorizedException("账号已被禁用，请联系管理员")

    # 生成Token
    extra = {"role": user.role, "username": user.username}
    access = create_access_token(user.id, extra)
    refresh = create_refresh_token(user.id)

    # 更新登录信息
    from datetime import datetime
    user.last_login_at = datetime.now()
    user.last_login_ip = request.client.host if request and request.client else ""
    db.commit()

    # 返回与 /users/me 同结构的 user 信息，避免前端 store 存的 userInfo
    # 缺 username/nickname/role 导致 isAdmin=false、顶栏用户信息空、用户管理菜单隐藏等运营bug
    user_payload = {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar,
        "role": user.role,
        "two_factor_enabled": user.two_factor_enabled,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }
    return success(LoginResp(
        access_token=access,
        refresh_token=refresh,
        user=user_payload,
    ))


@router.post("/refresh", response_model=ApiResponse[dict])
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    """刷新 access_token"""
    import jwt
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedException("无效的refresh token")
        uid = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("refresh token已过期，请重新登录")
    except Exception:
        raise UnauthorizedException("refresh token无效")

    user = db.query(User).filter(User.id == uid, User.status == 1).first()
    if not user:
        raise UnauthorizedException("用户不存在")
    extra = {"role": user.role, "username": user.username}
    return success({
        "access_token": create_access_token(user.id, extra),
        "token_type": "bearer",
    })


@router.post("/logout")
def logout(user: User = Depends(get_current_user)):
    """登出（前端清除Token即可，后端如需黑名单可扩展Redis）"""
    return success(message="已退出登录")


# ============ 用户信息 ============

class UpdatePasswordReq(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


class UpdateMeReq(BaseModel):
    """用户修改自己的基础资料（不可改 username/role/status）"""
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None


@user_router.put("/me")
def update_me(
    req: UpdateMeReq,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改自己的基础资料"""
    if req.nickname is not None:
        user.nickname = req.nickname
    if req.email is not None:
        user.email = req.email
    if req.phone is not None:
        user.phone = req.phone
    if req.avatar is not None:
        user.avatar = req.avatar
    db.commit()
    return success({
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar,
        "role": user.role,
        "two_factor_enabled": user.two_factor_enabled,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }, message="资料已更新")


@user_router.get("/me", response_model=ApiResponse[dict])
def get_me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return success({
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar,
        "role": user.role,
        "two_factor_enabled": user.two_factor_enabled,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    })


@user_router.put("/me/password")
def change_password(
    req: UpdatePasswordReq,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改密码"""
    if not verify_password(req.old_password, user.password_hash):
        raise ParameterException("原密码错误")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return success(message="密码修改成功")


# ============ 用户管理（仅管理员） ============

class CreateUserReq(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: str = ""
    email: str = ""
    phone: str = ""
    role: int = Field(default=3, ge=1, le=3)
    status: int = 1


class UpdateUserReq(BaseModel):
    """管理员修改用户（Body JSON；字段为 None 代表保持原值）"""
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    role: int | None = Field(default=None, ge=1, le=3)
    status: int | None = None
    reset_password: str | None = None


@user_router.get("", response_model=ApiResponse[dict])
def list_users(
    q: PaginationParams = Depends(),
    keyword: str = "",
    role: int | None = None,
    status: int | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """用户列表（仅管理员）"""
    query = db.query(User)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter((User.username.like(like)) | (User.nickname.like(like)))
    if role is not None:
        query = query.filter(User.role == role)
    if status is not None:
        query = query.filter(User.status == status)
    return success(paginate(query, q.page, q.page_size, q.order_by))


@user_router.post("")
def create_user(
    req: CreateUserReq,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """创建用户（仅管理员）"""
    if db.query(User).filter(User.username == req.username).first():
        raise ParameterException("用户名已存在")
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        nickname=req.nickname or req.username,
        email=req.email,
        phone=req.phone,
        role=req.role,
        status=req.status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return success(BaseWithId.model_validate(user), message="创建成功")


@user_router.put("/{uid}")
def update_user(
    uid: int,
    req: UpdateUserReq,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """修改用户信息（仅管理员，Body JSON：允许局部更新）"""
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise ParameterException("用户不存在")
    if req.nickname is not None:
        user.nickname = req.nickname
    if req.email is not None:
        user.email = req.email
    if req.phone is not None:
        user.phone = req.phone
    if req.role is not None:
        user.role = req.role
    if req.status is not None:
        user.status = req.status
    if req.reset_password:
        if len(req.reset_password) < 6 or len(req.reset_password) > 128:
            raise ParameterException("新密码长度需 6-128 位")
        user.password_hash = hash_password(req.reset_password)
    db.commit()
    return success(message="修改成功")


@user_router.delete("/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """删除用户（仅管理员）"""
    if uid == 1:
        raise ParameterException("不能删除超级管理员")
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise ParameterException("用户不存在")
    db.delete(user)
    db.commit()
    return success(message="删除成功")
