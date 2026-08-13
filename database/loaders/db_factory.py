import os
import logging
from typing import Optional

import const
from .base_loader import BaseDBLoader
from .sqlite_loader import SQLiteLoader
from .postgres_loader import PostgresLoader

logger = logging.getLogger(__name__)

def get_db_loader(
    db_backend: Optional[str] = None,
    db_path: Optional[str] = None
) -> BaseDBLoader:
    """
    [資料載入層 - 工廠函式]
    根據環境變數 DB_BACKEND (或傳入參數) 自動切換載入器實體。
    
    支援模式：
    - 'sqlite' (預設): 回傳 SQLiteLoader
    - 'postgres': 回傳 PostgresLoader
    """
    backend = db_backend or os.getenv('DB_BACKEND', getattr(const, 'DEFAULT_DB_BACKEND', 'sqlite'))
    backend = backend.strip().lower()

    sqlite_path = db_path or const.DB_PATH

    if backend == 'postgres':
        logger.info("🔌 工廠初始化 DB Backend: PostgreSQL")
        return PostgresLoader()
    else:
        # 預設回傳 SQLiteLoader (確保 100% 舊有行為相容)
        if backend != 'sqlite':
            logger.warning(f"⚠️ 未知的 DB_BACKEND 設定 [{backend}]，將降級切換至預設 'sqlite' 模式。")
        return SQLiteLoader(db_path=sqlite_path)
