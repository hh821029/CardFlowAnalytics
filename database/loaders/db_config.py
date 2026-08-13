# database/loaders/db_config.py
import os
import logging
from typing import Optional, Any

import const

logger = logging.getLogger(__name__)

# 嘗試載入 SQLAlchemy
try:
    import sqlalchemy
    from sqlalchemy.engine import URL, Engine
    from sqlalchemy import create_engine
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    Engine = None  # type: ignore

# 全域 Engine 快取實體 (Singleton Engine Instance)
_cached_pg_engine: Optional[Any] = None


def get_postgres_url(hide_password: bool = False) -> str:
    """
    [安全資料庫連線 URL 建構器]
    1. 優先支援環境變數直接指定的連線字串 (POSTGRES_URL / DATABASE_URL)。
    2. 使用 sqlalchemy.engine.URL.create 動態建構連線 URL，自動對帳號密碼進行安全轉義。
    3. 支援 hide_password=True，方便安全列印 Log 而不洩漏明文密碼。
    """
    env_url = os.getenv('POSTGRES_URL') or os.getenv('DATABASE_URL')
    if env_url:
        if not getattr(const, 'IS_IN_DOCKER', False):
            env_url = env_url.replace('@localhost:', '@127.0.0.1:')
        if hide_password and HAS_SQLALCHEMY:
            try:
                from sqlalchemy.engine import make_url
                url_obj = make_url(env_url)
                return url_obj.render_as_string(hide_password=True)
            except Exception:
                return "postgresql://***:***@... (env_url set)"
        return env_url

    host = getattr(const, 'PG_HOST', '127.0.0.1')
    if host == 'localhost' and not getattr(const, 'IS_IN_DOCKER', False):
        host = '127.0.0.1'
    port = int(getattr(const, 'PG_PORT', 5432))
    user = getattr(const, 'PG_USER', 'postgres')
    password = getattr(const, 'PG_PASSWORD', 'postgres')
    database = getattr(const, 'PG_DATABASE', 'credit_card_db')

    if HAS_SQLALCHEMY:
        url_obj = URL.create(
            drivername="postgresql+psycopg2",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database
        )
        return url_obj.render_as_string(hide_password=hide_password)
    else:
        # Fallback (若未安裝 SQLAlchemy)
        if password:
            pwd_str = "***" if hide_password else password
            return f"postgresql://{user}:{pwd_str}@{host}:{port}/{database}"
        return f"postgresql://{user}@{host}:{port}/{database}"


def get_postgres_engine(connect_timeout: int = 5, force_new: bool = False):
    """
    [單例 PostgreSQL Engine 工廠]
    建立並快取 SQLAlchemy Engine，避免重複建立連線池導致效能損耗或連線洩漏。
    """
    global _cached_pg_engine

    if not HAS_SQLALCHEMY:
        logger.warning("⚠️ 未檢測到 sqlalchemy 套件，無法建立 PostgreSQL Engine。")
        return None

    if _cached_pg_engine is not None and not force_new:
        return _cached_pg_engine

    try:
        conn_str = get_postgres_url(hide_password=False)
        safe_log_str = get_postgres_url(hide_password=True)
        logger.debug(f"🔌 建立 PostgreSQL Engine: {safe_log_str}")
        
        engine = create_engine(
            conn_str, 
            connect_args={'connect_timeout': connect_timeout},
            pool_pre_ping=True
        )
        _cached_pg_engine = engine
        return engine
    except Exception as e:
        safe_log_str = get_postgres_url(hide_password=True)
        logger.warning(f"⚠️ 無法建立 PostgreSQL Engine ({safe_log_str}): {e}")
        return None
