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



    V_RAW_TRANSACTIONS_VIEW_SQL = """
    SELECT 
        r.transaction_id,
        r.bank_no,
        COALESCE(b.bank_name, '') AS bank_name,
        COALESCE(b.bills_mapping_name, '') AS bills_mapping_name,
        r.statement_month,
        r.transaction_date,
        r.posting_date,
        r.conversion_date,
        r.raw_merchant,
        r.raw_currency,
        r.raw_amount,
        r.payment_currency,
        r.payment_amount,
        r.card_no,
        r.raw_location,
        r.raw_extra,
        r.created_at
    FROM raw_transactions r
    LEFT JOIN dim_banks b ON r.bank_no = b.bank_no
    """

    RAW_TABLE_DDL_PG = """
    CREATE TABLE IF NOT EXISTS raw_transactions (
        transaction_id      VARCHAR(32) PRIMARY KEY,
        bank_no             VARCHAR(3) NOT NULL,
        statement_month     DATE NOT NULL,
        transaction_date    DATE NOT NULL,
        posting_date        DATE,
        conversion_date     DATE,
        raw_merchant        VARCHAR(500) NOT NULL,
        raw_currency        VARCHAR(3) NOT NULL DEFAULT 'TWD',
        raw_amount          NUMERIC(12, 2) NOT NULL,
        payment_currency    VARCHAR(3) NOT NULL DEFAULT 'TWD',
        payment_amount      NUMERIC(12, 2) NOT NULL,
        card_no             VARCHAR(4),
        raw_location        VARCHAR(10) DEFAULT 'TW',
        raw_extra           JSONB,
        created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """

    RAW_TABLE_DDL_SQLITE = """
    CREATE TABLE IF NOT EXISTS raw_transactions (
        transaction_id      TEXT PRIMARY KEY,
        bank_no             TEXT NOT NULL,
        statement_month     TEXT NOT NULL,
        transaction_date    TEXT NOT NULL,
        posting_date        TEXT,
        conversion_date     TEXT,
        raw_merchant        TEXT NOT NULL,
        raw_currency        TEXT NOT NULL DEFAULT 'TWD',
        raw_amount          REAL NOT NULL,
        payment_currency    TEXT NOT NULL DEFAULT 'TWD',
        payment_amount      REAL NOT NULL,
        card_no             TEXT,
        raw_location        TEXT DEFAULT 'TW',
        raw_extra           TEXT,
        created_at          TEXT NOT NULL DEFAULT (DATETIME('now', 'localtime'))
    );
    """

    @classmethod
    def ensure_raw_schema(
        cls,
        db_backend: Optional[str] = None,
        db_path: Optional[str] = None,
        engine=None,
        conn=None,
        loader: Optional[Any] = None
    ) -> bool:
        """
        確保 Stage 1 原始事實表 raw_transactions、索引與 v_raw_transactions 檢視表已建立
        """
        backend = getattr(loader, 'backend', None) or resolve_db_backend(db_backend)
        target_path = getattr(loader, 'db_path', None) or db_path

        if backend == 'sqlite':
            path = target_path or getattr(const, 'DB_PATH', 'data/credit_card.db')
            should_close = False
            if conn is None:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                conn = sqlite3.connect(path, timeout=30.0)
                should_close = True
            try:
                cursor = conn.cursor()
                cursor.execute(cls.RAW_TABLE_DDL_SQLITE)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_txns_bank_month ON raw_transactions (bank_no, statement_month);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_txns_date ON raw_transactions (transaction_date);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_raw_txns_card_no ON raw_transactions (card_no);")

                # 建立或覆蓋 v_raw_transactions 視圖
                cursor.execute("SELECT type FROM sqlite_master WHERE name='v_raw_transactions'")
                row = cursor.fetchone()
                if row:
                    if row[0] == 'table':
                        cursor.execute("DROP TABLE IF EXISTS v_raw_transactions")
                    else:
                        cursor.execute("DROP VIEW IF EXISTS v_raw_transactions")
                cursor.execute(f"CREATE VIEW v_raw_transactions AS {cls.V_RAW_TRANSACTIONS_VIEW_SQL}")

                conn.commit()
                logger.info("✅ SQLite [raw_transactions] 表與 [v_raw_transactions] 視圖初始化完成")
                return True
            except Exception as e:
                logger.error(f"❌ 建立 SQLite raw_transactions 表或視圖失敗: {e}", exc_info=True)
                return False
            finally:
                if should_close and conn:
                    conn.close()
        else:
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
                with engine.connect() as pg_conn:
                    pg_conn.execute(text(cls.RAW_TABLE_DDL_PG))
                    pg_conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_txns_bank_month ON raw_transactions (bank_no, statement_month);"))
                    pg_conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_txns_date ON raw_transactions (transaction_date);"))
                    pg_conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_txns_card_no ON raw_transactions (card_no);"))
                    pg_conn.execute(text(f"CREATE OR REPLACE VIEW v_raw_transactions AS {cls.V_RAW_TRANSACTIONS_VIEW_SQL}"))
                    pg_conn.commit()
                logger.info("✅ PostgreSQL [raw_transactions] 表與 [v_raw_transactions] 視圖初始化完成")
                return True
            except Exception as e:
                logger.error(f"❌ 建立 PostgreSQL raw_transactions 表或視圖失敗: {e}", exc_info=True)
                return False

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

            # 檢查是否有 dim_banks 維度表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dim_banks'")
            has_dim_banks = bool(cursor.fetchone())

            # 1. 重建 rewards_transactions
            cursor.execute("SELECT type FROM sqlite_master WHERE name='rewards_transactions'")
            row = cursor.fetchone()
            if row and row[0] == 'table' and not has_dim_banks:
                logger.debug("ℹ️ 資料表 [rewards_transactions] 為實體表且缺少 dim_banks，保留實體表。")
            else:
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
            if row_rfm and row_rfm[0] == 'table' and not has_dim_banks:
                logger.debug("ℹ️ 資料表 [rfm_transactions] 為實體表且缺少 dim_banks，保留實體表。")
            else:
                if row_rfm:
                    if row_rfm[0] == 'table':
                        cursor.execute("DROP TABLE IF EXISTS rfm_transactions")
                    else:
                        cursor.execute("DROP VIEW IF EXISTS rfm_transactions")
                cursor.execute(f"CREATE VIEW rfm_transactions AS {cls.RFM_VIEW_SQL}")
                logger.info("✅ SQLite 視圖 [rfm_transactions] 建立/更新成功")



            # 3. 若 raw_transactions 存在，建立/覆蓋 v_raw_transactions
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='raw_transactions'")
            if cursor.fetchone():
                cursor.execute("SELECT type FROM sqlite_master WHERE name='v_raw_transactions'")
                row_raw = cursor.fetchone()
                if row_raw:
                    if row_raw[0] == 'table':
                        cursor.execute("DROP TABLE IF EXISTS v_raw_transactions")
                    else:
                        cursor.execute("DROP VIEW IF EXISTS v_raw_transactions")
                cursor.execute(f"CREATE VIEW v_raw_transactions AS {cls.V_RAW_TRANSACTIONS_VIEW_SQL}")
                logger.info("✅ SQLite 視圖 [v_raw_transactions] 建立/更新成功")

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
                # 檢查若 rewards_transactions 為實體表 (BASE TABLE)，則略過建立視圖避免命名衝突
                check_rewards = conn.execute(text("SELECT table_type FROM information_schema.tables WHERE table_name = 'rewards_transactions'")).scalar()
                if check_rewards == 'VIEW' or check_rewards is None:
                    conn.execute(text(f"CREATE OR REPLACE VIEW rewards_transactions AS {cls.REWARDS_VIEW_SQL}"))
                    logger.info("✅ PostgreSQL 視圖 [rewards_transactions] 建立/更新成功")
                else:
                    logger.info("ℹ️ 資料表 [rewards_transactions] 已為實體表，保留實體資料結構")

                # 檢查若 rfm_transactions 為實體表 (BASE TABLE)，則略過建立視圖避免命名衝突
                check_rfm = conn.execute(text("SELECT table_type FROM information_schema.tables WHERE table_name = 'rfm_transactions'")).scalar()
                if check_rfm == 'VIEW' or check_rfm is None:
                    conn.execute(text(f"CREATE OR REPLACE VIEW rfm_transactions AS {cls.RFM_VIEW_SQL}"))
                    logger.info("✅ PostgreSQL 視圖 [rfm_transactions] 建立/更新成功")
                else:
                    logger.info("ℹ️ 資料表 [rfm_transactions] 已為實體表，保留實體資料結構")


                # 若 raw_transactions 存在，建立或覆蓋 v_raw_transactions
                check_raw = conn.execute(text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'raw_transactions')")).scalar()
                if check_raw:
                    conn.execute(text(f"CREATE OR REPLACE VIEW v_raw_transactions AS {cls.V_RAW_TRANSACTIONS_VIEW_SQL}"))
                    logger.info("✅ PostgreSQL 視圖 [v_raw_transactions] 建立/更新成功")

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
