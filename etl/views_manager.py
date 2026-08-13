# etl/views_manager.py
import logging
import pandas as pd
from typing import Optional, Any
from sqlalchemy import text

logger = logging.getLogger(__name__)

# --- SQL DDL 語句 ---

SQL_CREATE_FACT_TRANSACTION_MERCHANTS = """
CREATE TABLE IF NOT EXISTS fact_transaction_merchants (
    transaction_id VARCHAR(128) PRIMARY KEY,
    normalized_merchant VARCHAR(255),
    payment_process VARCHAR(255),
    ec_platform VARCHAR(255),
    merchant_display VARCHAR(255),
    category VARCHAR(255),
    sub_category VARCHAR(255)
);

ALTER TABLE fact_transaction_merchants ADD COLUMN IF NOT EXISTS category VARCHAR(255);
ALTER TABLE fact_transaction_merchants ADD COLUMN IF NOT EXISTS sub_category VARCHAR(255);

CREATE TABLE IF NOT EXISTS dim_banks (
    bank_no VARCHAR(20) PRIMARY KEY,
    bank_name VARCHAR(100),
    bills_mapping_name VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS dim_credit_card_products (
    card_id VARCHAR(100) PRIMARY KEY,
    bank_no VARCHAR(20),
    is_co_branded BOOLEAN,
    is_dual_currency BOOLEAN,
    note TEXT
);

CREATE TABLE IF NOT EXISTS bridge_user_cards (
    user_card_id VARCHAR(100) PRIMARY KEY,
    bank_no VARCHAR(20),
    card_id VARCHAR(100),
    card_type VARCHAR(100),
    card_network VARCHAR(50),
    smart_card_type VARCHAR(50),
    fx_type VARCHAR(20),
    card_no VARCHAR(20),
    vpc_no VARCHAR(20),
    vpc_type VARCHAR(50),
    card_start_date VARCHAR(20),
    card_end_date VARCHAR(20),
    is_active VARCHAR(20),
    is_enable_reward_calc VARCHAR(20)
);

ALTER TABLE bridge_user_cards ADD COLUMN IF NOT EXISTS fx_type VARCHAR(20);
ALTER TABLE bridge_user_cards ADD COLUMN IF NOT EXISTS card_start_date VARCHAR(20);
ALTER TABLE bridge_user_cards ADD COLUMN IF NOT EXISTS card_end_date VARCHAR(20);
ALTER TABLE bridge_user_cards ADD COLUMN IF NOT EXISTS is_active VARCHAR(20);
ALTER TABLE bridge_user_cards ADD COLUMN IF NOT EXISTS is_enable_reward_calc VARCHAR(20);

CREATE TABLE IF NOT EXISTS dim_categories (
    category_id VARCHAR(100) PRIMARY KEY,
    category_name VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS dim_sub_categories (
    sub_category_id VARCHAR(100) PRIMARY KEY,
    category_id VARCHAR(100),
    sub_category_name VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS dim_fx_table (
    conversion_date DATE,
    currency_type VARCHAR(10),
    exchange_rate NUMERIC(12, 4),
    PRIMARY KEY (conversion_date, currency_type)
);
"""

SQL_CREATE_VW_RFM_ANALYSIS = r"""
CREATE OR REPLACE VIEW vw_rfm_analysis AS
SELECT
    t.transaction_id,
    t.transaction_date,
    
    -- 卡片與銀行維度 (經由 dim_banks 與 bridge_user_cards 關聯)
    t.bank_name,
    COALESCE(buc.card_type, '')                      AS card_type,
    t.vpc_type,
    
    -- 商家與分類維度
    t.merchant_name,
    COALESCE(m.merchant_display, t.merchant_name)     AS merchant_display,
    COALESCE(m.normalized_merchant, t.merchant_name)  AS normalized_merchant,
    COALESCE(cat.category_name, m.category, '')       AS category,
    COALESCE(sub.sub_category_name, m.sub_category, '') AS sub_category,
    COALESCE(m.payment_process, '')                   AS payment_process,
    COALESCE(m.ec_platform, '')                       AS ec_platform,
    t.merchant_location,
    
    -- 金額與幣別 (條件觸發外幣換算 + 查無匯率自動保底退回 payment_amount)
    t.payment_currency,
    CASE 
        WHEN t.conversion_date IS NOT NULL 
         AND t.currency_type IS NOT NULL 
         AND UPPER(t.currency_type) <> 'TWD' 
         AND t.currency_amount IS NOT NULL 
         AND t.currency_amount <> 0 
        THEN 
            COALESCE(ROUND(t.currency_amount * fx.exchange_rate), t.payment_amount)
        ELSE t.payment_amount
    END AS payment_amount

FROM all_transactions t
LEFT JOIN (
    SELECT bank_no, bank_name, bills_mapping_name
    FROM dim_banks
    GROUP BY bank_no, bank_name, bills_mapping_name
) b 
       ON t.bank_name = b.bills_mapping_name OR t.bank_name = b.bank_name
LEFT JOIN (
    SELECT bank_no, card_no, MAX(card_type) AS card_type, MAX(card_id) AS card_id
    FROM bridge_user_cards
    GROUP BY bank_no, card_no
) buc 
       ON b.bank_no = buc.bank_no AND t.card_no = buc.card_no
LEFT JOIN dim_credit_card_products c 
       ON buc.card_id = c.card_id
LEFT JOIN fact_transaction_merchants m 
       ON t.transaction_id = m.transaction_id
LEFT JOIN dim_sub_categories sub 
       ON m.sub_category = sub.sub_category_name
LEFT JOIN dim_categories cat 
       ON sub.category_id = cat.category_id
LEFT JOIN dim_fx_table fx 
       ON t.conversion_date = fx.conversion_date AND t.currency_type = fx.currency_type
WHERE t.transaction_type = '交易';
"""

SQL_CREATE_VW_REWARDS_CALCULATION = r"""
CREATE OR REPLACE VIEW vw_rewards_calculation AS
SELECT
    t.transaction_id,
    t.transaction_date,
    t.posting_date,
    t.statement_month,
    
    -- 卡片與銀行維度
    t.bank_name,
    COALESCE(buc.card_type, '')                      AS card_type,
    t.vpc_type,
    
    -- 商家與支付管道維度
    t.merchant_name,
    COALESCE(m.merchant_display, t.merchant_name)     AS merchant_display,
    COALESCE(m.normalized_merchant, t.merchant_name)  AS normalized_merchant,
    COALESCE(m.payment_process, '')                   AS payment_process,
    COALESCE(m.ec_platform, '')                       AS ec_platform,
    t.merchant_location,
    
    -- 金額與幣別 (保留原始 payment_amount 並提供換算後 TWD 金額供 C# 運算)
    t.payment_currency,
    t.payment_amount                                 AS raw_payment_amount,
    CASE 
        WHEN t.conversion_date IS NOT NULL 
         AND t.currency_type IS NOT NULL 
         AND UPPER(t.currency_type) <> 'TWD' 
         AND t.currency_amount IS NOT NULL 
         AND t.currency_amount <> 0 
        THEN 
            COALESCE(t.currency_amount * fx.exchange_rate, t.payment_amount)
        ELSE t.payment_amount
    END AS payment_amount_twd,
    
    t.transaction_type

FROM all_transactions t
LEFT JOIN (
    SELECT bank_no, bank_name, bills_mapping_name
    FROM dim_banks
    GROUP BY bank_no, bank_name, bills_mapping_name
) b 
       ON t.bank_name = b.bills_mapping_name OR t.bank_name = b.bank_name
LEFT JOIN (
    SELECT bank_no, card_no, MAX(card_type) AS card_type, MAX(card_id) AS card_id
    FROM bridge_user_cards
    GROUP BY bank_no, card_no
) buc 
       ON b.bank_no = buc.bank_no AND t.card_no = buc.card_no
LEFT JOIN dim_credit_card_products c 
       ON buc.card_id = c.card_id
LEFT JOIN fact_transaction_merchants m 
       ON t.transaction_id = m.transaction_id
LEFT JOIN dim_fx_table fx 
       ON t.conversion_date = fx.conversion_date AND t.currency_type = fx.currency_type
WHERE t.transaction_type IN ('交易', '退刷');
"""

SQL_CREATE_VW_TRANSACTIONS_ENRICHED = r"""
CREATE OR REPLACE VIEW vw_transactions_enriched AS
SELECT
    t.transaction_id,
    t.bank_name,
    COALESCE(buc.card_type, '')               AS card_type,
    t.card_no,
    t.vpc_type,
    t.transaction_date,
    t.posting_date,
    t.payment_currency,
    t.payment_amount,
    t.transaction_type,
    t.merchant_name,
    COALESCE(m.merchant_display, t.merchant_name) AS merchant_display,
    COALESCE(m.payment_process, '')               AS payment_process,
    COALESCE(m.ec_platform, '')                   AS ec_platform,
    COALESCE(m.normalized_merchant, t.merchant_name) AS normalized_merchant,
    t.merchant_location
FROM all_transactions t
LEFT JOIN (
    SELECT bank_no, bank_name, bills_mapping_name
    FROM dim_banks
    GROUP BY bank_no, bank_name, bills_mapping_name
) b ON t.bank_name = b.bills_mapping_name OR t.bank_name = b.bank_name
LEFT JOIN (
    SELECT bank_no, card_no, MAX(card_type) AS card_type, MAX(card_id) AS card_id
    FROM bridge_user_cards
    GROUP BY bank_no, card_no
) buc ON b.bank_no = buc.bank_no AND t.card_no = buc.card_no
LEFT JOIN dim_credit_card_products c ON buc.card_id = c.card_id
LEFT JOIN fact_transaction_merchants m ON t.transaction_id = m.transaction_id;
"""

def create_all_views(engine: Any) -> bool:
    """
    建立 / 更新所有 PostgreSQL 分析視圖與依賴基礎表
    """
    if engine is None:
        logger.warning("⚠️ Engine 為空，無法建立視圖。")
        return False

    try:
        with engine.connect() as conn:
            conn.execute(text(SQL_CREATE_FACT_TRANSACTION_MERCHANTS))
            conn.execute(text(SQL_CREATE_VW_RFM_ANALYSIS))
            conn.execute(text(SQL_CREATE_VW_REWARDS_CALCULATION))
            conn.execute(text(SQL_CREATE_VW_TRANSACTIONS_ENRICHED))
            conn.commit()
            logger.info("✨ PostgreSQL 視圖 [vw_rfm_analysis, vw_rewards_calculation, vw_transactions_enriched] 成功建立/更新！")
            return True
    except Exception as e:
        logger.error(f"❌ 建立視圖時發生錯誤: {e}", exc_info=True)
        return False

def upsert_transaction_merchants(engine: Any, df_full: pd.DataFrame) -> bool:
    """
    將 DataFrame 中的清洗屬性寫入 / 物化至 fact_transaction_merchants 資料表
    """
    if df_full is None or df_full.empty or 'transaction_id' not in df_full.columns:
        return False

    merchant_cols = [
        'transaction_id', 'normalized_merchant', 'payment_process', 
        'ec_platform', 'merchant_display', 'category', 'sub_category'
    ]
    avail_cols = [c for c in merchant_cols if c in df_full.columns]
    if len(avail_cols) <= 1:
        return False

    df_dedup = pd.DataFrame(df_full.drop_duplicates(subset=['transaction_id']))
    df_mer = pd.DataFrame(df_dedup[avail_cols])

    try:
        with engine.connect() as conn:
            conn.execute(text(SQL_CREATE_FACT_TRANSACTION_MERCHANTS))
            conn.commit()

        df_mer.to_sql('fact_transaction_merchants', engine, if_exists='append', index=False, method='multi')
        logger.info(f"✨ 成功物化 {len(df_mer)} 筆商家清洗屬性至 fact_transaction_merchants")
        return True
    except Exception as e:
        try:
            df_mer.to_sql('fact_transaction_merchants', engine, if_exists='append', index=False)
            return True
        except Exception as inner_e:
            logger.warning(f"⚠️ 寫入 fact_transaction_merchants 注意事項: {inner_e}")
            return False
