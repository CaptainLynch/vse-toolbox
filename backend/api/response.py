"""FastAPI 通用响应辅助函数。独立模块，避免循环导入。"""

from fastapi.responses import JSONResponse


def success_response(data=None):
    return {"success": True, "data": data, "message": None}


def error_response(message: str, status_code: int = 400):
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "message": message},
    )
