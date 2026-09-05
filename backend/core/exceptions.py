"""
全局异常定义 + FastAPI 全局异常处理器
统一前后端错误响应格式
"""
from typing import Any, Optional, Dict
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


# ============ 自定义业务异常 ============

class BizException(Exception):
    """业务异常基类：所有业务逻辑抛出的异常都用它"""

    def __init__(
        self,
        message: str = "业务错误",
        code: int = 4000,
        http_status: int = status.HTTP_400_BAD_REQUEST,
        data: Optional[Any] = None,
    ):
        self.code = code
        self.message = message
        self.http_status = http_status
        self.data = data
        super().__init__(message)


# 常用错误预设
class UnauthorizedException(BizException):
    def __init__(self, message: str = "未登录或登录已过期"):
        super().__init__(message=message, code=4010, http_status=status.HTTP_401_UNAUTHORIZED)


class ForbiddenException(BizException):
    def __init__(self, message: str = "权限不足"):
        super().__init__(message=message, code=4030, http_status=status.HTTP_403_FORBIDDEN)


class NotFoundException(BizException):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message=message, code=4040, http_status=status.HTTP_404_NOT_FOUND)


class ParameterException(BizException):
    def __init__(self, message: str = "参数错误", data: Any = None):
        super().__init__(message=message, code=4001, http_status=status.HTTP_422_UNPROCESSABLE_ENTITY, data=data)


class ExchangeAPIException(BizException):
    def __init__(self, message: str = "交易所接口异常", data: Any = None):
        super().__init__(message=message, code=5010, http_status=status.HTTP_502_BAD_GATEWAY, data=data)


class ExchangeError(ExchangeAPIException):
    def __init__(self, message: str = "交易所通用错误", data: Any = None):
        super().__init__(message=message, data=data)


class ExchangeNotImplementedError(ExchangeAPIException):
    def __init__(self, message: str = "交易所暂未支持此功能"):
        super().__init__(message=message, code=5011, http_status=status.HTTP_501_NOT_IMPLEMENTED)


class InsufficientBalanceError(ExchangeAPIException):
    def __init__(self, message: str = "余额不足，无法开仓", data: Any = None):
        super().__init__(message=message, code=5012, data=data)


class OrderNotFoundError(ExchangeAPIException):
    def __init__(self, message: str = "订单不存在", data: Any = None):
        super().__init__(message=message, code=5013, http_status=status.HTTP_404_NOT_FOUND, data=data)


class RiskControlException(BizException):
    def __init__(self, message: str = "风控拦截", data: Any = None):
        super().__init__(message=message, code=4500, http_status=status.HTTP_403_FORBIDDEN, data=data)


# ============ 统一响应结构 ============

def build_response(
    code: int = 0,
    message: str = "success",
    data: Any = None,
    **extra: Any,
) -> Dict[str, Any]:
    """构造统一成功响应体"""
    resp: Dict[str, Any] = {"code": code, "message": message, "data": data}
    resp.update(extra)
    return resp


def success(data: Any = None, message: str = "success", **extra: Any) -> Dict[str, Any]:
    return build_response(0, message, data, **extra)


# ============ 全局异常处理器注册函数 ============

def register_exception_handlers(app):
    """把所有异常处理器挂载到 FastAPI app 上"""

    @app.exception_handler(BizException)
    async def biz_exception_handler(_: Request, exc: BizException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=build_response(exc.code, exc.message, exc.data),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=build_response(
                code=exc.status_code,
                message=exc.detail if isinstance(exc.detail, str) else "HTTP Error",
                data=exc.detail if not isinstance(exc.detail, str) else None,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 把 pydantic 的错误格式精简为可读字符串
        errs = exc.errors()
        readable = "; ".join(
            [f"{'->'.join(map(str, e['loc']))}: {e['msg']}" for e in errs[:5]]
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=build_response(
                code=4220,
                message=f"参数校验失败: {readable}" if readable else "参数错误",
                data=errs,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        # 兜底：未捕获异常，避免直接返回 500 HTML
        # 安全：生产环境不泄露异常类名和消息，仅返回通用提示
        from backend.config import get_settings
        _settings = get_settings()
        if _settings.APP_ENV == "production":
            _msg = "服务器内部错误，请联系管理员"
        else:
            _msg = f"服务器内部错误: {exc.__class__.__name__}: {str(exc)[:200]}"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=build_response(
                code=5000,
                message=_msg,
                data=None,
            ),
        )
