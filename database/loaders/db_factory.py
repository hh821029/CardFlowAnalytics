import os
import logging
from typing import Optional

import const
from .base_loader import BaseDBLoader
from .sqlite_loader import SQLiteLoader
from .postgres_loader import PostgresLoader
from .db_config import resolve_db_backend

logger = logging.getLogger(__name__)

def get_db_loader(
    db_backend: Optional[str] = None,
    db_path: Optional[str] = None
) -> BaseDBLoader:
    """
    [資料載入層 - 工廠函式]
    使用 resolve_db_backend 統一解析後端身分並切換載入器實體。
    
    支援模式：
    - 'sqlite' (預設): 回傳 SQLiteLoader
    - 'postgres': 回傳 PostgresLoader
    """
    backend = resolve_db_backend(db_backend)
    sqlite_path = db_path or const.DB_PATH

    if backend == 'postgres':
        logger.info("🔌 工廠初始化 DB Backend: PostgreSQL")
        return PostgresLoader()
    else:
        return SQLiteLoader(db_path=sqlite_path)
