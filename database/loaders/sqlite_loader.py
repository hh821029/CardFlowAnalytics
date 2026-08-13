import pandas as pd
import sqlite3
import logging
import os
from typing import Optional, List, Literal

import const
from .base_loader import BaseDBLoader

logger = logging.getLogger(__name__)

class SQLiteLoader(BaseDBLoader):
    """
    [資料載入層 - SQLite 實作]
    繼承 BaseDBLoader，負責將 DataFrame 寫入 SQLite 資料庫。
    維持 100% 舊有 SQLite 行為與相容性。
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or const.DB_PATH
        if not self.db_path:
            raise ValueError("❌ SQLiteLoader db_path 未指定且 const.DB_PATH 無效。")
            
        # 確保目錄存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def load(
        self, 
        df: pd.DataFrame, 
        table_name: str, 
        mode: Literal['append', 'delete_rows', 'fail', 'replace'] = 'replace', 
        indices: Optional[List[str]] = None
    ) -> None:
        """
        將 DataFrame 寫入 SQLite
        mode: 'replace' (全量覆蓋), 'append' (附加)
        indices: 欄位名稱列表，用於建立索引
        """
        if df.empty:
            logger.warning(f"⚠️ 沒有資料可寫入資料庫表 [{table_name}]。")
            return

        logger.info(f"💾 準備將 {len(df)} 筆資料寫入 SQLite 資料庫 ({self.db_path}) 表 [{table_name}]...")
        
        # 1. 呼叫 BaseDBLoader 的通用清理與格式化
        df_final = self._sanitize_dataframe(df)

        # 2. 寫入 SQLite (加入 timeout 避免在高併發或 API 連線時 DB locked)
        try:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                df_final.to_sql(table_name, conn, if_exists=mode, index=False)
                
                # 3. 建立索引 (Optimization)
                if indices:
                    cursor = conn.cursor()
                    for idx_col in indices:
                        if idx_col in df_final.columns:
                            # 判斷是否為 unique index (例如 transaction_id)
                            is_unique = "UNIQUE" if idx_col.endswith('_id') else ""
                            idx_name = f"idx_{table_name}_{idx_col}"
                            cursor.execute(f"CREATE {is_unique} INDEX IF NOT EXISTS {idx_name} ON {table_name} ({idx_col})")
                    conn.commit()
                
                # 4. 驗證
                cursor = conn.cursor()
                cursor.execute(f"SELECT count(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                logger.info(f"✅ SQLite 資料庫作業完成！資料表 [{table_name}] 目前共有 {count} 筆資料。")

        except Exception as e:
            logger.error(f"❌ 寫入 SQLite 資料庫失敗: {e}", exc_info=True)
            raise e
