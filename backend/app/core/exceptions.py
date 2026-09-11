"""业务异常与全局异常处理。"""


class BizError(Exception):
    """业务异常，携带业务 code 与 HTTP 状态码。"""

    def __init__(self, code: int = 1, message: str = "error", status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(BizError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(code=404, message=message, status_code=404)


class AuthError(BizError):
    def __init__(self, message: str = "未授权或凭证失效"):
        super().__init__(code=401, message=message, status_code=401)


class ForbiddenError(BizError):
    def __init__(self, message: str = "无权限访问"):
        super().__init__(code=403, message=message, status_code=403)
