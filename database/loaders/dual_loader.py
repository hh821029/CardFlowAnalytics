import pandas as pd
import logging
from typing import Optional, List, Literal

from .base_loader import BaseDBLoader

logger = logging.getLogger(__name__)

class DualDBLoader(BaseDBLoader):
    """
    [資料載入層 - 雙軌併行寫入器]
    繼承 BaseDBLoader，包裝 Primary Loader (如 SQLiteLoader) 與 Secondary Loader (如 PostgresLoader)。
    在執行 load() 時，自動同步將資料寫入兩個目標資料庫中。
    """
    def __init__(self, primary_loader: BaseDBLoader, secondary_loader: BaseDBLoader):
        self.primary_loader = primary_loader
        self.secondary_loader = secondary_loader

    def load(
        self, 
        df: pd.DataFrame, 
        table_name: str, 
        mode: Literal['append', 'delete_rows', 'fail', 'replace'] = 'replace', 
        indices: Optional[List[str]] = None
    ) -> None:
        """
        雙軌同步寫入：先寫入 Primary DB，再寫入 Secondary DB
        """
        if df.empty:
            logger.warning(f"⚠️ 沒有資料可寫入 [DualDBLoader] 資料表 [{table_name}]。")
            return

        logger.info(f"🔄 雙軌併行 (Dual-DB Write) 寫入啟動：資料表 [{table_name}]...")

        # 1. 寫入主資料庫 (Primary)
        try:
            logger.info("1️⃣ 執行 Primary DB 寫入...")
            self.primary_loader.load(df, table_name=table_name, mode=mode, indices=indices)
        except Exception as e:
            logger.error(f"❌ Primary DB 寫入失敗: {e}")
            raise e

        # 2. 寫入副資料庫 (Secondary)
        try:
            logger.info("2️⃣ 執行 Secondary DB (PostgreSQL) 寫入...")
            self.secondary_loader.load(df, table_name=table_name, mode=mode, indices=indices)
        except Exception as e:
            logger.error(f"⚠️ Secondary DB (PostgreSQL) 寫入失敗: {e} (主資料庫作業不受影響)")
