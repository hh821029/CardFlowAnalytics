# database/loaders/db_reader.py
import os
import logging
import sqlite3
import pandas as pd
from typing import Optional, Dict, Any, Union
import const

logger = logging.getLogger(__name__)

# 嘗試載入 SQLAlchemy 以支援 PostgreSQL 連線
try:
    import sqlalchemy
    from sqlalchemy import create_engine, text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


from .db_config import get_postgres_url, get_postgres_engine

class DBReader:
    """
    [資料庫讀取連線工廠 (Read Abstraction)]
    職責：根據 DB_BACKEND 設定 (sqlite / postgres / dual) 動態選擇讀取連線。
    1. 當 DB_BACKEND 為 'postgres' 或 'dual' 時，優先嘗試連線至 PostgreSQL (credit_card_db)。
    2. 若 PostgreSQL 連線失敗或設定為 'sqlite'，自動平滑降級 (Fallback) 讀取本機 SQLite (TransactionsBills.db)。
    3. 自動統一 SQL 命名參數處理，確保與 pd.read_sql 完美整合。
    """

    @classmethod
    def get_postgres_connection_string(cls, hide_password: bool = False) -> str:
        """委派 db_config 動態產生安全的 PostgreSQL 連線字串"""
        return get_postgres_url(hide_password=hide_password)

    @classmethod
    def get_engine(cls):
        """傳回快取的 PostgreSQL SQLAlchemy Engine實體"""
        return get_postgres_engine(connect_timeout=5)

    @classmethod
    def read_sql(
        cls, 
        sql: str, 
        params: Optional[Dict[str, Any]] = None, 
        parse_dates: Optional[Any] = None,
        db_path: Optional[str] = None
    ) -> pd.DataFrame:
        """
        跨 DB 相容讀取 API (自動判定 backend & 降級)
        """
        backend = os.getenv('DB_BACKEND', getattr(const, 'DEFAULT_DB_BACKEND', 'postgres')).strip().lower()
        sqlite_db_path = db_path or const.DB_PATH

        # 1. 嘗試 PostgreSQL 讀取 (若 backend 為 postgres 或 dual)
        if backend in ('postgres', 'dual') and HAS_SQLALCHEMY:
            engine = cls.get_engine()
            if engine:
                try:
                    logger.debug(f"🔌 [DBReader] 嘗試使用 PostgreSQL 執行查詢...")
                    with engine.connect() as conn:
                        df = pd.read_sql(text(sql), conn, params=params, parse_dates=parse_dates)
                        logger.debug(f"✅ [DBReader] PostgreSQL 查詢成功，傳回 {len(df)} 筆紀錄。")
                        return df
                except Exception as pg_err:
                    logger.warning(f"⚠️ PostgreSQL 查詢失敗，降級切換至 SQLite 讀取: {pg_err}")

        # 2. 降級至 SQLite 讀取 (Default Fallback)
        logger.debug(f"💾 [DBReader] 使用 SQLite 執行查詢 ({os.path.basename(sqlite_db_path)})...")
        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
            df = pd.read_sql(sql, conn, params=params, parse_dates=parse_dates)
            return df
