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
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import pyotp

from backend.db.session import get_db
from backend.core.auth import get_current_user, require_admin
from backend.core.exceptions import UnauthorizedException, ParameterException, success
from backend.config import get_settings
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
    totp_code: str = Field(default="", max_length=10)


class LoginResp(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict = {}


@router.post("/login", response_model=ApiResponse[LoginResp])
def login(req: LoginReq, db: Session = Depends(get_db), request: Request = None):
    """用户名密码登录（如已启用2FA需提供totp_code）"""
    user: User | None = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise UnauthorizedException("用户名或密码错误")
    if user.status != 1:
        raise UnauthorizedException("账号已被禁用，请联系管理员")

    # 2FA 检查：已启用 2FA 的用户需在登录时直接验证 TOTP 验证码（一步式，不签发中间令牌）
    if user.two_factor_enabled and user.two_factor_secret:
        if not req.totp_code:
            raise UnauthorizedException("需要两步验证(2FA)验证码")
        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(req.totp_code, valid_window=1):
            raise UnauthorizedException("两步验证码错误")

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
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }
    return success(LoginResp(
        access_token=access,
        refresh_token=refresh,
        user=user_payload,
    ))


@router.post("/login/cookie", response_model=ApiResponse[LoginResp])
def login_cookie(req: LoginReq, db: Session = Depends(get_db), request: Request = None, response: Response = None):
    """登录并设置HttpOnly Cookie（更安全的Token存储方式，防XSS窃取）"""
    user: User | None = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise UnauthorizedException("用户名或密码错误")
    if user.status != 1:
        raise UnauthorizedException("账号已被禁用，请联系管理员")

    if user.two_factor_enabled and user.two_factor_secret:
        if not req.totp_code:
            raise UnauthorizedException("需要两步验证(2FA)验证码")
        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(req.totp_code, valid_window=1):
            raise UnauthorizedException("两步验证码错误")

    extra = {"role": user.role, "username": user.username}
    access = create_access_token(user.id, extra)
    refresh = create_refresh_token(user.id)

    from datetime import datetime
    user.last_login_at = datetime.now()
    user.last_login_ip = request.client.host if request and request.client else ""
    db.commit()

    # 设置HttpOnly Cookie（SameSite=Strict，防CSRF和XSS窃取）
    _settings = get_settings()
    token_lifetime = getattr(_settings, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 1440) * 60
    response.set_cookie(
        key="access_token",
        value=access,
        httponly=True,
        samesite="strict",
        secure=(_settings.APP_ENV == "production"),
        max_age=token_lifetime,
        path="/",
    )

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
def logout(
    request: Request,
    user: User = Depends(get_current_user),
):
    """登出：将当前 Token 的 jti 加入黑名单，使其立即失效"""
    from backend.core.auth import _add_to_blacklist
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.cookies.get("access_token", "")
        if token:
            payload = decode_token(token)
            jti = payload.get("jti")
            exp = payload.get("exp", 0)
            if jti:
                _add_to_blacklist(jti, exp)
    except Exception:
        pass  # 即使提取失败也允许登出
    return success(message="已退出登录")


# ============ 2FA 双因素认证 ============

class TwoFASetupResp(BaseModel):
    secret: str
    otpauth_uri: str
    qr_code_data: str


class TwoFAVerifyReq(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class TwoFALoginReq(BaseModel):
    temp_token: str
    code: str = Field(..., min_length=6, max_length=6)


@router.post("/2fa/setup", response_model=ApiResponse[TwoFASetupResp])
def setup_2fa(user: User = Depends(get_current_user)):
    """生成 2FA 密钥和 QR 码（用户扫码后需调用 /2fa/verify 确认）"""
    import pyotp
    import urllib.parse
    import urllib.parse as _urlparse

    secret = pyotp.random_base32()
    issuer = "StrategyTrade"
    label = f"{issuer}:{user.username}"
    otpauth_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=issuer)

    # 不立即保存 secret，等验证通过后才写入
    return success(TwoFASetupResp(
        secret=secret,
        otpauth_uri=otpauth_uri,
        qr_code_data=otpauth_uri,
    ))


@router.post("/2fa/verify")
def verify_2fa(
    req: TwoFAVerifyReq,
    secret: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """验证 6 位验证码，通过后启用 2FA"""
    import pyotp
    from fastapi import Query

    if not secret:
        raise ParameterException("缺少 secret 参数")
    totp = pyotp.TOTP(secret)
    if not totp.verify(req.code, valid_window=1):
        raise ParameterException("验证码错误或已过期")

    user.two_factor_secret = secret
    user.two_factor_enabled = True
    db.commit()
    return success(message="2FA 已启用")


@router.post("/2fa/disable")
def disable_2fa(
    req: TwoFAVerifyReq,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """关闭 2FA（需密码验证码确认）"""
    import pyotp
    if not user.two_factor_enabled or not user.two_factor_secret:
        raise ParameterException("未启用 2FA")
    totp = pyotp.TOTP(user.two_factor_secret)
    if not totp.verify(req.code, valid_window=1):
        raise ParameterException("验证码错误或已过期")
    user.two_factor_secret = ""
    user.two_factor_enabled = False
    db.commit()
    return success(message="2FA 已关闭")


@router.post("/login/2fa", response_model=ApiResponse[LoginResp])
def login_2fa(req: TwoFALoginReq, db: Session = Depends(get_db), request: Request = None):
    """2FA 登录第二步：用 temp_token + 验证码完成登录"""
    import pyotp
    try:
        payload = decode_token(req.temp_token)
        if payload.get("type") != "2fa_pending":
            raise UnauthorizedException("无效的 2FA 临时令牌")
        uid = int(payload["sub"])
    except UnauthorizedException:
        raise
    except Exception:
        raise UnauthorizedException("2FA 临时令牌已过期或无效")

    user = db.query(User).filter(User.id == uid, User.status == 1).first()
    if not user:
        raise UnauthorizedException("用户不存在或已禁用")
    if not user.two_factor_enabled or not user.two_factor_secret:
        raise UnauthorizedException("该用户未启用 2FA")

    totp = pyotp.TOTP(user.two_factor_secret)
    if not totp.verify(req.code, valid_window=1):
        raise UnauthorizedException("验证码错误或已过期")

    extra = {"role": user.role, "username": user.username}
    access = create_access_token(user.id, extra)
    refresh = create_refresh_token(user.id)

    from datetime import datetime
    user.last_login_at = datetime.now()
    user.last_login_ip = request.client.host if request and request.client else ""
    db.commit()

    user_payload = {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "email": user.email,
        "phone": user.phone,
        "avatar": user.avatar,
        "role": user.role,
        "two_factor_enabled": user.two_factor_enabled,
        "must_change_password": user.must_change_password,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }
    return success(LoginResp(
        access_token=access,
        refresh_token=refresh,
        user=user_payload,
    ))


# ============ 用户信息 ============

class UpdatePasswordReq(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


class UpdateMeReq(BaseModel):
    """用户修改自己的基础资料（不可改 username/role/status）"""
    nickname: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    avatar: str | None = Field(default=None, max_length=512)


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
        "must_change_password": user.must_change_password,
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
        "must_change_password": user.must_change_password,
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
    user.must_change_password = False
    db.commit()
    return success(message="密码修改成功")


# ============ 2FA 两步验证 ============

class Setup2FAResp(BaseModel):
    secret: str
    qr_uri: str


@user_router.post("/me/2fa/setup", response_model=ApiResponse[Setup2FAResp])
def setup_2fa(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成2FA密钥（需用户用Google Authenticator等扫码绑定）"""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    qr_uri = totp.provisioning_uri(name=user.username, issuer_name="StrategyTrade")
    user.two_factor_secret = secret
    db.commit()
    return success(Setup2FAResp(secret=secret, qr_uri=qr_uri), message="密钥已生成，请用验证器扫码绑定")


class Enable2FAReq(BaseModel):
    totp_code: str = Field(..., min_length=6, max_length=10)


@user_router.post("/me/2fa/enable")
def enable_2fa(
    req: Enable2FAReq,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """验证TOTP码并启用2FA"""
    if not user.two_factor_secret:
        raise ParameterException("请先调用 /2fa/setup 生成密钥")
    totp = pyotp.TOTP(user.two_factor_secret)
    if not totp.verify(req.totp_code, valid_window=1):
        raise ParameterException("验证码错误")
    user.two_factor_enabled = True
    db.commit()
    return success(message="2FA已启用")


@user_router.post("/me/2fa/disable")
def disable_2fa(
    req: Enable2FAReq,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """关闭2FA（需验证当前TOTP码）"""
    if not user.two_factor_enabled:
        raise ParameterException("2FA未启用")
    totp = pyotp.TOTP(user.two_factor_secret)
    if not totp.verify(req.totp_code, valid_window=1):
        raise ParameterException("验证码错误")
    user.two_factor_enabled = False
    user.two_factor_secret = ""
    db.commit()
    return success(message="2FA已关闭")


# ============ 用户管理（仅管理员） ============

class CreateUserReq(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    nickname: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=128)
    phone: str = Field(default="", max_length=32)
    avatar: str = Field(default="", max_length=512)
    role: int = Field(default=3, ge=1, le=3)
    status: int = 1


class UpdateUserReq(BaseModel):
    """管理员修改用户（Body JSON；字段为 None 代表保持原值）"""
    nickname: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    avatar: str | None = Field(default=None, max_length=512)
    role: int | None = Field(default=None, ge=1, le=3)
    status: int | None = None
    reset_password: str | None = Field(default=None, max_length=128)


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
        avatar=req.avatar,
        role=req.role,
        status=req.status,
        must_change_password=True,
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
    if req.avatar is not None:
        user.avatar = req.avatar
    if req.role is not None:
        user.role = req.role
    if req.status is not None:
        user.status = req.status
    if req.reset_password:
        if len(req.reset_password) < 6 or len(req.reset_password) > 128:
            raise ParameterException("新密码长度需 6-128 位")
        user.password_hash = hash_password(req.reset_password)
        user.must_change_password = True
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
