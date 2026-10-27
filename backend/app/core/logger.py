import logging
import sys
from contextvars import ContextVar, Token

from loguru import logger

from app.common.enums import EnvironmentEnum
from app.config.path_conf import LOG_DIR
from app.config.setting import settings


def _make_std_streams_encoding_safe() -> None:
    """让 stdout/stderr 遇到无法编码的字符时用 ``?`` 代替，而不是抛异常。

    Windows 控制台默认 GBK（cp936），日志/欢迎面板里的 emoji（✅ 🚀）直接写入会抛
    ``UnicodeEncodeError``，表现为「本地启动报错」甚至服务起不来。这里在导入阶段
    统一把标准流的 errors 改成 replace：控制台显示为 ?，进程继续运行。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="replace")
        except (ValueError, OSError):
            continue


_make_std_streams_encoding_safe()


# ── 请求链路 ID（日志追踪） ──
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def set_correlation_id(cid: str) -> Token:
    return _correlation_id.set(cid)


def get_correlation_id() -> str:
    return _correlation_id.get()


def reset_correlation_id(token: Token) -> None:
    _correlation_id.reset(token)


def _context_patcher(record):
    cid = get_correlation_id()
    record["extra"]["ctx"] = f" | cid={cid[:8]}" if cid else ""


class InterceptHandler(logging.Handler):
    """将标准库 logging 重定向到 Loguru"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # 第一轮无条件回溯跳过 emit 自身帧，之后跳过 logging 内部帧，
        # 使 caller 定位到真实调用方（否则 uvicorn 等日志会显示 logging:callHandlers:xxx）
        frame, depth = logging.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, "{}", record.getMessage())


def _console_sink(message: str) -> None:
    """控制台日志兜底：Windows GBK 控制台遇到 ✅ 等字符时用 ? 替换，不中断进程。

    直接 `logger.add(sys.stdout)` 时，GBK 编码写 emoji 会抛 UnicodeEncodeError，
    表现为启动日志里反复出现 ``--- Logging error in Loguru Handler #1 ---``。
    """
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write(message)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(message.encode(encoding, "replace").decode(encoding, "replace"))
    try:
        stream.flush()
    except ValueError:
        pass


def setup_logger() -> None:
    """配置日志记录器"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(patcher=_context_patcher)

    LOG_FMT = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>{extra[ctx]}"
    _is_prod = settings.ENVIRONMENT == EnvironmentEnum.PROD
    logger.add(_console_sink, format=LOG_FMT, backtrace=not _is_prod, diagnose=not _is_prod, catch=True, level=settings.LOGGER_LEVEL)
    logger.add(
        sink=str(LOG_DIR / "fastapiadmin.log"),
        format=LOG_FMT,
        level=settings.LOGGER_LEVEL,
        backtrace=not _is_prod,
        diagnose=not _is_prod,
        catch=True,
        rotation="00:00",
        retention=30,
        compression="gz",
        encoding="utf-8",
    )

    logging.basicConfig(handlers=[InterceptHandler()], level=settings.LOGGER_LEVEL, force=True)
    for name in [k for k in logging.root.manager.loggerDict if isinstance(k, str)] + ["uvicorn", "uvicorn.error", "uvicorn.access"]:
        std = logging.getLogger(name)
        std.handlers = [InterceptHandler()]
        std.propagate = False

    # 第三方库 DEBUG/INFO 噪音干扰太大，只保留 WARNING 以上：
    # apscheduler（任务轮询）、alembic（autogenerate 插件注册 setup plugin、模型对比 Detected added 批量输出）、
    # 数据库驱动（aiomysql 连接缓存、sqlalchemy 引擎日志，原 alembic.ini [logger_sqlalchemy] 的配置迁移至此）、
    # tzlocal（模块级调试输出 /etc/localtime found、is a symlink to ...，dev reload 下会随应用加载刷屏）
    for name in (
        "apscheduler",
        "apscheduler.schedulers",
        "apscheduler.jobstores",
        "alembic.runtime.migration",
        "alembic.autogenerate",
        "alembic.runtime.plugins",
        "asyncio",
        "websockets",
        "sqlalchemy",
        "aiomysql",
        "tzlocal",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


setup_logger()
