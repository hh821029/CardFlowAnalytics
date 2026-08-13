import pandas as pd
import logging
import os
from typing import Optional, List, Literal, Dict, Any

import const
from .base_loader import BaseDBLoader

logger = logging.getLogger(__name__)

# 嘗試動態載入 PostgreSQL 相關驅動庫 (sqlalchemy / psycopg2)
try:
    import sqlalchemy
    from sqlalchemy import create_engine, text
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


from .db_config import get_postgres_url, get_postgres_engine


class PostgresLoader(BaseDBLoader):
    """
    [資料載入層 - PostgreSQL 實作]
    繼承 BaseDBLoader，負責將 DataFrame 批次寫入 / Upsert 至 PostgreSQL 資料庫。
    支援 ON CONFLICT (transaction_id) DO UPDATE 高效去重機制。
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        connection_string: Optional[str] = None
    ):
        self.host = host or getattr(const, 'PG_HOST', '127.0.0.1')
        if self.host == 'localhost' and not getattr(const, 'IS_IN_DOCKER', False):
            self.host = '127.0.0.1'
        self.port = port or getattr(const, 'PG_PORT', 5432)
        self.user = user or getattr(const, 'PG_USER', 'postgres')
        self.password = password or getattr(const, 'PG_PASSWORD', 'postgres')
        self.database = database or getattr(const, 'PG_DATABASE', 'credit_card_db')

        if connection_string:
            self.conn_str = connection_string
        else:
            self.conn_str = get_postgres_url(hide_password=False)

        if not HAS_SQLALCHEMY and not HAS_PSYCOPG2:
            logger.warning("⚠️ 未檢測到 sqlalchemy 或 psycopg2 套件。若要寫入 PostgreSQL，請安裝: pip install sqlalchemy psycopg2-binary")

    def _get_engine(self):
        engine = get_postgres_engine()
        if engine is None:
            raise ImportError("無法建立 PostgreSQL 連線：請確定已安裝 sqlalchemy 與 psycopg2-binary 套件。")
        return engine

    def load(
        self, 
        df: pd.DataFrame, 
        table_name: str, 
        mode: Literal['append', 'delete_rows', 'fail', 'replace'] = 'replace', 
        indices: Optional[List[str]] = None
    ) -> None:
        """
        將 DataFrame 寫入 / Upsert 至 PostgreSQL
        """
        if df.empty:
            logger.warning(f"⚠️ 沒有資料可寫入 PostgreSQL 資料庫表 [{table_name}]。")
            return

        logger.info(f"💾 準備將 {len(df)} 筆資料寫入 PostgreSQL ({self.host}:{self.port}/{self.database}) 表 [{table_name}]...")

        # 1. 呼叫 BaseDBLoader 的通用清理與格式化
        df_final = self._sanitize_dataframe(df)

        try:
            engine = self._get_engine()
            
            # 1.5 自動修補資料表欄位 (Self-Healing Schema Check)
            self._ensure_table_columns_exist(engine, table_name, df_final)

            # 2. 判斷是否有 primary key / unique id 欄位 (如 transaction_id) 可做 ON CONFLICT Upsert
            pk_col = None
            if 'transaction_id' in df_final.columns:
                pk_col = 'transaction_id'
            elif 'file_hash' in df_final.columns:
                pk_col = 'file_hash'

            # 取得基於 const.TransactionColumn 的資料庫原生型態對照字典 (Date, Float, Boolean, String)
            sql_dtypes = const.TransactionColumn.get_sql_dtypes(df_final)

            # 若為 append 模式且包含 pk_col，採用 ON CONFLICT Upsert 特化處置
            if mode == 'append' and pk_col and HAS_PSYCOPG2:
                self._upsert_with_psycopg2(df_final, table_name, pk_col)
            else:
                # 若為 replace 模式，先以 DROP TABLE ... CASCADE 移除舊表與 View 依賴，確保 Schema 異動 (如新增欄位) 能順利重建
                if mode == 'replace':
                    logger.info(f"ℹ️ 資料表 [{table_name}] 採用 DROP TABLE ... CASCADE 重建模式...")
                    with engine.connect() as conn:
                        conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;'))
                        conn.commit()
                    df_final.to_sql(table_name, engine, if_exists='replace', index=False, dtype=sql_dtypes)
                else:
                    df_final.to_sql(table_name, engine, if_exists='append', index=False, dtype=sql_dtypes)

            # 3. 建立索引 (Indices Optimization)
            if indices:
                with engine.connect() as conn:
                    for idx_col in indices:
                        if idx_col in df_final.columns:
                            # 僅有主鍵欄位 (如 pk_col 或與表名同名之主鍵) 才建立 UNIQUE INDEX，其餘外鍵 _id 建立一般索引
                            is_pk = (pk_col and idx_col == pk_col) or (idx_col == f"{table_name}_id") or (idx_col == "transaction_id")
                            is_unique = "UNIQUE" if is_pk else ""
                            idx_name = f"idx_{table_name}_{idx_col}"
                            conn.execute(text(f"CREATE {is_unique} INDEX IF NOT EXISTS {idx_name} ON {table_name} ({idx_col})"))
                    conn.commit()

            # 4. 驗證總筆數
            with engine.connect() as conn:
                result = conn.execute(text(f"SELECT count(*) FROM {table_name}"))
                count = result.scalar()
                logger.info(f"✅ PostgreSQL 資料庫作業完成！資料表 [{table_name}] 目前共有 {count} 筆資料。")

            # 5. 若寫入表為 all_transactions，自動寫入 fact_transaction_merchants 並建構 vw_transactions_enriched 視圖
            if table_name == 'all_transactions':
                self.create_enriched_view(df)

        except Exception as e:
            logger.error(f"❌ 寫入 PostgreSQL 資料庫失敗: {e}", exc_info=True)
            raise e

    def create_enriched_view(self, df_full: Optional[pd.DataFrame] = None):
        """
        委派 etl.views_manager 執行：
        1. 物化寫入清洗擴充欄位至 fact_transaction_merchants
        2. 自動建立 / 更新 PostgreSQL 分析視圖 (vw_rfm_analysis, vw_rewards_calculation, vw_transactions_enriched)
        """
        try:
            from etl.views_manager import create_all_views, upsert_transaction_merchants
            engine = self._get_engine()
            if df_full is not None and not df_full.empty:
                upsert_transaction_merchants(engine, df_full)
            create_all_views(engine)
        except Exception as e:
            logger.warning(f"⚠️ 委派建立視圖失敗: {e}")

    def _ensure_table_columns_exist(self, engine, table_name: str, df: pd.DataFrame):
        """
        自癒 (Self-Healing) 機制：檢查並自動為 PostgreSQL 資料表補齊 DataFrame 中新增的欄位
        """
        try:
            with engine.connect() as conn:
                check_table_sql = text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = :table_name;
                """)
                res = conn.execute(check_table_sql, {"table_name": table_name})
                existing_cols = {row[0] for row in res.fetchall()}

                if not existing_cols:
                    return  # 資料表尚不存在

                missing_cols = [c for c in df.columns if c not in existing_cols]
                if missing_cols:
                    logger.info(f"🛠️ 檢測到資料表 [{table_name}] 缺少欄位 {missing_cols}，正在為 PostgreSQL 自動補齊欄位...")
                    for col in missing_cols:
                        col_type = "VARCHAR(255)"
                        conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col}" {col_type};'))
                    conn.commit()
                    logger.info(f"✅ 資料表 [{table_name}] 欄位自動補齊完成。")
        except Exception as e:
            logger.warning(f"⚠️ 檢查/補齊 PostgreSQL 欄位失敗 (非致命): {e}")


    def _upsert_with_psycopg2(self, df: pd.DataFrame, table_name: str, pk_col: str):
        """
        使用 psycopg2 執行批次 ON CONFLICT (...) DO UPDATE 語法
        """
        raw_conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database
        )
        try:
            cursor = raw_conn.cursor()
            cols = list(df.columns)
            columns_str = ", ".join([f'"{c}"' for c in cols])
            
            # 構建 UPDATE SET 語法 (排除 PK 本身)
            update_cols = [c for c in cols if c != pk_col]
            update_str = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])
            
            sql = f"""
                INSERT INTO "{table_name}" ({columns_str})
                VALUES %s
                ON CONFLICT ("{pk_col}") DO UPDATE SET {update_str}
            """
            
            values = [tuple(x) for x in df.to_numpy()]
            execute_values(cursor, sql, values)
            raw_conn.commit()
            cursor.close()
        finally:
            raw_conn.close()
