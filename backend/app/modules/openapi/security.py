"""开放接口鉴权：应用密钥校验、访问令牌签发与校验、调用限流。

与管理端 JWT 完全隔离：
- 开放令牌带 ``typ=open_client`` 声明，管理端 ``_authenticate`` 按 Redis 会话查不到会直接 401；
- 管理端令牌没有该声明，本模块解码时同样拒绝。
"""

import secrets
import time
from datetime import UTC, datetime, timedelta

import jwt
from redis.asyncio.client import Redis

from app.config.setting import settings
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.core.redis_crud import RedisCURD
from app.modules.openapi.model import OpenClientModel
from app.utils.password_util import PwdUtil

OPEN_TOKEN_TYPE = "open_client"
TOKEN_KEY_PREFIX = "open_api_token"
RATE_KEY_PREFIX = "open_api_rate"

# 业务错误码（与 docs/指标开放接口设计.md 对齐）
CODE_UNAUTHORIZED = 40100
CODE_CLIENT_FORBIDDEN = 40101
CODE_METRIC_FORBIDDEN = 40102
CODE_RATE_LIMIT = 40103
CODE_PARAM_INVALID = 40104


def generate_app_secret() -> str:
    """生成应用密钥（只在下发时明文返回一次）。"""
    return secrets.token_urlsafe(32)


async def hash_app_secret(secret: str) -> str:
    """密钥落库前哈希（PBKDF2，与用户口令同实现）。"""
    return await PwdUtil.ahash_password(secret)


async def verify_app_secret(plain_secret: str, secret_hash: str) -> bool:
    return await PwdUtil.averify_password(plain_secret, secret_hash)


def create_open_token(app_id: str, ttl_seconds: int) -> tuple[str, int, str]:
    """签发开放令牌。

    返回:
    - tuple[str, int, str]: (令牌, 有效期秒, jti)
    """
    ttl = max(int(ttl_seconds), 300)
    jti = secrets.token_urlsafe(16)
    now = datetime.now(UTC)
    payload = {
        "sub": f"open:{app_id}",
        "typ": OPEN_TOKEN_TYPE,
        "app_id": app_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    token = jwt.encode(payload=payload, key=settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, ttl, jti


def decode_open_token(token: str) -> dict:
    """解析开放令牌；非法/过期/类型不符统一返回 401。"""
    if not token:
        raise CustomException(msg="未提供访问令牌", code=CODE_UNAUTHORIZED, status_code=401)
    try:
        payload = jwt.decode(token, key=settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise CustomException(msg="访问令牌已过期，请重新获取", code=CODE_UNAUTHORIZED, status_code=401) from e
    except (jwt.InvalidTokenError, jwt.DecodeError, jwt.InvalidSignatureError) as e:
        raise CustomException(msg="访问令牌无效", code=CODE_UNAUTHORIZED, status_code=401) from e

    if payload.get("typ") != OPEN_TOKEN_TYPE or not payload.get("app_id"):
        raise CustomException(msg="访问令牌无效", code=CODE_UNAUTHORIZED, status_code=401)
    return payload


async def store_token(redis: Redis, app_id: str, jti: str, ttl_seconds: int) -> None:
    """令牌登记进 Redis：应用停用或密钥重置时按前缀批量失效。"""
    await RedisCURD(redis).set(key=f"{TOKEN_KEY_PREFIX}:{app_id}:{jti}", value=app_id, expire=ttl_seconds)


async def is_token_active(redis: Redis, app_id: str, jti: str) -> bool:
    return bool(await RedisCURD(redis).get(f"{TOKEN_KEY_PREFIX}:{app_id}:{jti}"))


async def revoke_tokens(redis: Redis, app_id: str) -> int:
    """失效某应用已签发的全部令牌（停用应用、重置密钥时调用）。

    单应用令牌键数量等于在线令牌数（个位数到几十），用 ``KEYS`` + 批量 ``DEL``
    比 ``SCAN`` 更直接；这里不做大 key 空间的扫描。
    """
    crud = RedisCURD(redis)
    keys = await crud.get_keys(f"{TOKEN_KEY_PREFIX}:{app_id}:*")
    if not keys:
        return 0
    await crud.delete(*[key.decode() if isinstance(key, bytes) else str(key) for key in keys])
    return len(keys)


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise CustomException(msg="缺少 Authorization 请求头", code=CODE_UNAUTHORIZED, status_code=401)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != settings.TOKEN_TYPE.lower() or not token.strip():
        raise CustomException(msg="Authorization 格式应为 Bearer <access_token>", code=CODE_UNAUTHORIZED, status_code=401)
    return token.strip()


def ip_allowed(client_ip: str | None, ip_whitelist: str | None) -> bool:
    """IP 白名单校验：支持精确 IP 与 ``192.168.1.*`` 前缀通配，空配置不限制。"""
    if not ip_whitelist or not ip_whitelist.strip():
        return True
    if not client_ip:
        return False
    for item in ip_whitelist.split(","):
        rule = item.strip()
        if not rule:
            continue
        if rule.endswith("*"):
            if client_ip.startswith(rule[:-1]):
                return True
        elif rule == client_ip:
            return True
    return False


async def check_rate_limit(
    redis: Redis,
    client: OpenClientModel,
    limit_override: int | None = None,
    scope: str = "api",
) -> None:
    """按「应用 + 分钟 + 用途」统计调用次数，超限抛 429。

    用 ``get`` + ``set(ex=)`` 的读改写而非 INCR，兼容测试用的 Redis 替身；
    窗口为自然分钟，轻微并发下可能少计 1~2 次，对限流用途足够。

    参数:
    - limit_override (int | None): 指定配额，缺省用应用配置的 ``rate_limit``；
    - scope (str): 计数用途，业务接口与换令牌分开计数（换令牌另有更严的固定配额）。
    """
    limit = int(limit_override if limit_override is not None else (client.rate_limit or 0))
    if limit <= 0:
        return
    window = int(time.time()) // 60
    key = f"{RATE_KEY_PREFIX}:{scope}:{client.app_id}:{window}"
    crud = RedisCURD(redis)
    try:
        raw = await crud.get(key)
        count = int(raw or 0) + 1
        await crud.set(key=key, value=count, expire=120)
    except Exception as e:  # Redis 异常不阻断业务：限流是保护手段，不是正确性依赖
        logger.warning(f"开放接口限流计数失败: {e!s}")
        return
    if count > limit:
        raise CustomException(
            msg=f"调用频率超限（上限 {limit} 次/分钟），请在 {60 - int(time.time()) % 60} 秒后重试",
            code=CODE_RATE_LIMIT,
            status_code=429,
        )


def ensure_client_usable(client: OpenClientModel) -> None:
    """应用状态、有效期校验（令牌有效但应用被停用/过期时同样拒绝）。"""
    if int(client.status or 0) != 0:
        raise CustomException(msg="该应用已停用，请联系管理员", code=CODE_CLIENT_FORBIDDEN, status_code=403)
    expire_time = client.expire_time
    if expire_time is not None:
        now = datetime.now(UTC)
        expire_time = expire_time if expire_time.tzinfo else expire_time.replace(tzinfo=UTC)
        if expire_time < now:
            raise CustomException(msg="该应用凭证已过期，请联系管理员", code=CODE_CLIENT_FORBIDDEN, status_code=403)
