import logging
import logging.handlers
import shutil
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.response import error_response, success_response
from config import BASE_DIR, DATA_DIR, DIST_DIR, LOGS_DIR, TEMP_DIR, safe_path
from services.db import init_schema

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / "VSE_TOOLBOX.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.handlers.TimedRotatingFileHandler(
            log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("VSE_TOOLBOX")

# ---------------------------------------------------------------------------
# 临时文件自动清理
# ---------------------------------------------------------------------------

TEMP_MAX_AGE_HOURS = 24


def _clean_temp_files():
    """清理超过 TEMP_MAX_AGE_HOURS 小时的临时文件。"""
    cutoff = datetime.now() - timedelta(hours=TEMP_MAX_AGE_HOURS)
    cleaned = 0
    try:
        for item in TEMP_DIR.iterdir():
            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if mtime < cutoff:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                    cleaned += 1
            except OSError:
                pass
    except Exception as e:
        logger.warning("Temp cleanup failed: %s", e)
    if cleaned:
        logger.info("Cleaned %d old temp files", cleaned)


def _start_temp_cleanup():
    """启动后台线程，每 30 分钟清理一次临时文件。"""
    def loop():
        while True:
            time.sleep(1800)
            _clean_temp_files()

    t = threading.Thread(target=loop, daemon=True, name="temp-cleanup")
    t.start()
    logger.info("Temp cleanup thread started")


# ---------------------------------------------------------------------------
# 异常处理
# ---------------------------------------------------------------------------

async def validation_exception_handler(request: Request, exc):
    logger.warning("Validation error: %s", exc)
    return error_response(str(exc), status_code=400)


async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTP exception %s: %s", exc.status_code, exc.detail)
    return error_response(exc.detail, status_code=exc.status_code)


async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception at %s", request.url.path)
    return error_response("服务器内部错误", status_code=500)


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== VSE TOOLBOX Backend Starting ===")
    logger.info("Base dir: %s", BASE_DIR)
    logger.info("Data dir: %s", DATA_DIR)
    logger.info("Temp dir: %s", TEMP_DIR)
    logger.info("Logs dir: %s", LOGS_DIR)

    init_schema()
    _clean_temp_files()
    _start_temp_cleanup()

    yield

    logger.info("=== VSE TOOLBOX Backend Shutting Down ===")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

app = FastAPI(
    title="VSE Toolbox API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：仅允许本地回环地址
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:8002", "http://localhost:8002", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(422, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# ---------------------------------------------------------------------------
# 注册路由
# ---------------------------------------------------------------------------

from api import issues, excel, crawler, ppt, feishu, milestones, dashboard, ewo_ncr, tir, lookup, settings

app.include_router(issues.router, prefix="/api")
app.include_router(excel.router, prefix="/api")
app.include_router(crawler.router, prefix="/api")
app.include_router(ppt.router, prefix="/api")
app.include_router(feishu.router, prefix="/api")
app.include_router(milestones.router, prefix="/api")

app.include_router(dashboard.router, prefix='/api')
app.include_router(ewo_ncr.router, prefix='/api')
app.include_router(tir.router, prefix='/api')
app.include_router(lookup.router, prefix='/api')
app.include_router(settings.router, prefix='/api')

# ---------------------------------------------------------------------------
# 文件下载端点
# ---------------------------------------------------------------------------

from fastapi.responses import FileResponse


@app.get("/api/download")
async def download_file(path: str):
    try:
        file_path = safe_path(path)
    except ValueError as e:
        return error_response(str(e), status_code=400)

    if not file_path.exists() or not file_path.is_file():
        return error_response("文件不存在", status_code=404)

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/octet-stream",
    )


# ---------------------------------------------------------------------------
# 静态文件托管（前端 dist/）
# ---------------------------------------------------------------------------

if DIST_DIR.exists() and any(DIST_DIR.iterdir()):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="static")
    logger.info("Static files mounted from %s", DIST_DIR)
else:
    logger.warning("dist/ not found or empty; static files not mounted")


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8002,
        reload=False,
        log_level="info",
    )
