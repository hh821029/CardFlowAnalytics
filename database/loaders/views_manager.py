# database/loaders/views_manager.py
"""
[SQL View Layer & Index Manager]
管理 3NF 視圖層與效能索引：
1. rewards_transactions: 動態關聯 dim_banks 與 dim_credit_card_products 補全 bank_name 與 card_type。
2. rfm_transactions: 同樣動態關聯維度表，提供統一消費視圖。
3. 建立 (bank_no, card_id) 與 (transaction_date) 複合索引以加速查詢。
"""
import logging
import sqlite3
import os
from typing import Optional, Any

import const
from .db_config import resolve_db_backend

logger = logging.getLogger(__name__)


class ViewsManager:
    """視圖與複合索引管理層"""

    REWARDS_VIEW_SQL = """
    SELECT 
        t.transaction_id,
        t.bank_no,
        COALESCE(b.bank_name, '') AS bank_name,
        COALESCE(b.bills_mapping_name, '') AS bills_mapping_name,
        t.card_id,
        COALESCE(p.card_type, '') AS card_type,
        t.card_no,
        t.vpc_no,
        t.vpc_type,
        t.transaction_date,
        t.posting_date,
        t.payment_amount AS amount,
        t.payment_amount,
        t.payment_currency,
        t.currency_amount,
        t.currency_type,
        t.conversion_date,
        t.statement_month,
        t.transaction_type,
        t.payment_process,
        t.ec_platform,
        t.merchant_name AS merchant,
        t.merchant_name,
        t.normalized_merchant,
        t.merchant_display,
        t.merchant_location,
        t.merchant_location AS location
    FROM all_transactions t
    LEFT JOIN dim_banks b ON t.bank_no = b.bank_no
    LEFT JOIN dim_credit_card_products p ON t.card_id = p.card_id
    """

    RFM_VIEW_SQL = """
    SELECT 
        t.transaction_id,
        t.bank_no,
        COALESCE(b.bank_name, '') AS bank_name,
        t.card_id,
        COALESCE(p.card_type, '') AS card_type,
        t.card_no,
        t.vpc_type,
        t.transaction_date,
        t.payment_amount,
        t.payment_currency,
        t.transaction_type,
        t.payment_process,
        t.ec_platform,
        t.merchant_name AS merchant,
        t.merchant_name,
        t.normalized_merchant,
        t.merchant_display,
        t.merchant_location,
        t.merchant_location AS location
    FROM all_transactions t
    LEFT JOIN dim_banks b ON t.bank_no = b.bank_no
    LEFT JOIN dim_credit_card_products p ON t.card_id = p.card_id
    """

    @classmethod
    def create_or_replace_views(
        cls, 
        db_backend: Optional[str] = None, 
        db_path: Optional[str] = None, 
        engine=None, 
        conn=None,
        loader: Optional[Any] = None
    ) -> bool:
        """
        在目標資料庫建立或更新 rewards_transactions 與 rfm_transactions 視圖
        """
        backend = getattr(loader, 'backend', None) or resolve_db_backend(db_backend)
        target_path = getattr(loader, 'db_path', None) or db_path
        if backend == 'sqlite':
            return cls._create_sqlite_views(db_path=target_path, conn=conn)
        else:
            return cls._create_postgres_views(engine=engine)

    @classmethod
    def _create_sqlite_views(cls, db_path: Optional[str] = None, conn=None) -> bool:
        path = db_path or getattr(const, 'DB_PATH', 'data/credit_card.db')
        should_close = False
        if conn is None:
            if not os.path.exists(path):
                logger.debug(f"ℹ️ SQLite 資料庫尚未存在 ({path})，略過視圖建立。")
                return False
            conn = sqlite3.connect(path, timeout=30.0)
            should_close = True

        try:
            cursor = conn.cursor()

            # 檢查 all_transactions 表是否存在
            cursor.execute("SELECT name, type FROM sqlite_master WHERE name='all_transactions'")
            tbl = cursor.fetchone()
            if not tbl:
                logger.debug("ℹ️ all_transactions 實體表尚未建立，略過視圖建立。")
                return False

            # 1. 重建 rewards_transactions
            cursor.execute("SELECT type FROM sqlite_master WHERE name='rewards_transactions'")
            row = cursor.fetchone()
            if row:
                if row[0] == 'table':
                    cursor.execute("DROP TABLE IF EXISTS rewards_transactions")
                else:
                    cursor.execute("DROP VIEW IF EXISTS rewards_transactions")
            
            cursor.execute(f"CREATE VIEW rewards_transactions AS {cls.REWARDS_VIEW_SQL}")
            logger.info("✅ SQLite 視圖 [rewards_transactions] 建立/更新成功")

            # 2. 重建 rfm_transactions
            cursor.execute("SELECT type FROM sqlite_master WHERE name='rfm_transactions'")
            row_rfm = cursor.fetchone()
            if row_rfm:
                if row_rfm[0] == 'table':
                    cursor.execute("DROP TABLE IF EXISTS rfm_transactions")
                else:
                    cursor.execute("DROP VIEW IF EXISTS rfm_transactions")

            cursor.execute(f"CREATE VIEW rfm_transactions AS {cls.RFM_VIEW_SQL}")
            logger.info("✅ SQLite 視圖 [rfm_transactions] 建立/更新成功")

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ 建立 SQLite 視圖失敗: {e}", exc_info=True)
            return False
        finally:
            if should_close and conn:
                conn.close()

    @classmethod
    def _create_postgres_views(cls, engine=None) -> bool:
        if engine is None:
            try:
                from database.loaders.db_config import get_postgres_engine
                engine = get_postgres_engine()
            except Exception as e:
                logger.warning(f"⚠️ 無法取得 PostgreSQL engine: {e}")
                return False

        if engine is None:
            return False

        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                # 建立或覆蓋 rewards_transactions
                conn.execute(text(f"CREATE OR REPLACE VIEW rewards_transactions AS {cls.REWARDS_VIEW_SQL}"))
                logger.info("✅ PostgreSQL 視圖 [rewards_transactions] 建立/更新成功")

                # 建立或覆蓋 rfm_transactions
                conn.execute(text(f"CREATE OR REPLACE VIEW rfm_transactions AS {cls.RFM_VIEW_SQL}"))
                logger.info("✅ PostgreSQL 視圖 [rfm_transactions] 建立/更新成功")

                conn.commit()
            return True
        except Exception as e:
            logger.error(f"❌ 建立 PostgreSQL 視圖失敗: {e}", exc_info=True)
            return False

    @classmethod
    def create_indices(
        cls, 
        db_backend: Optional[str] = None, 
        db_path: Optional[str] = None, 
        engine=None, 
        conn=None,
        loader: Optional[Any] = None
    ) -> bool:
        """
        在 all_transactions 建立複合索引 (bank_no, card_id) 與 (transaction_date)
        """
        backend = getattr(loader, 'backend', None) or resolve_db_backend(db_backend)
        target_path = getattr(loader, 'db_path', None) or db_path
        if backend == 'sqlite':
            path = target_path or getattr(const, 'DB_PATH', 'data/credit_card.db')
            should_close = False
            if conn is None:
                if not os.path.exists(path):
                    return False
                conn = sqlite3.connect(path, timeout=30.0)
                should_close = True

            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='all_transactions'")
                if not cursor.fetchone():
                    return False

                cursor.execute("CREATE INDEX IF NOT EXISTS idx_all_transactions_bank_card ON all_transactions (bank_no, card_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_all_transactions_txn_date ON all_transactions (transaction_date)")
                conn.commit()
                logger.info("✅ SQLite 索引 (bank_no, card_id) 與 (transaction_date) 建立成功")
                return True
            except Exception as e:
                logger.error(f"❌ 建立 SQLite 索引失敗: {e}")
                return False
            finally:
                if should_close and conn:
                    conn.close()
        else:
            if engine is None:
                try:
                    from database.loaders.db_config import get_postgres_engine
                    engine = get_postgres_engine()
                except Exception:
                    return False
            if engine is None:
                return False

            try:
                from sqlalchemy import text
                with engine.connect() as conn_pg:
                    conn_pg.execute(text("CREATE INDEX IF NOT EXISTS idx_all_transactions_bank_card ON all_transactions (bank_no, card_id)"))
                    conn_pg.execute(text("CREATE INDEX IF NOT EXISTS idx_all_transactions_txn_date ON all_transactions (transaction_date)"))
                    conn_pg.commit()
                logger.info("✅ PostgreSQL 索引 (bank_no, card_id) 與 (transaction_date) 建立成功")
                return True
            except Exception as e:
                logger.error(f"❌ 建立 PostgreSQL 索引失敗: {e}")
                return False
