-- ========================================================
-- DDL: raw_transactions (Stage 1 Bronze Raw Fact Table)
-- 目的: 保持 100% 銀行原始純淨度，作為全系統不可竄改的原始單一事實來源 (SSOT)
-- 適用資料庫: PostgreSQL (相容 SQLite)
-- ========================================================

-- 1. 建立 raw_transactions 實體表
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

-- 2. 建立常用查詢複合索引
CREATE INDEX IF NOT EXISTS idx_raw_txns_bank_month ON raw_transactions (bank_no, statement_month);
CREATE INDEX IF NOT EXISTS idx_raw_txns_date ON raw_transactions (transaction_date);
CREATE INDEX IF NOT EXISTS idx_raw_txns_card_no ON raw_transactions (card_no);

-- 3. 建立 v_raw_transactions 檢視表 (自動關聯 dim_banks 補充銀行名稱，維護 3NF 純淨)
CREATE OR REPLACE VIEW v_raw_transactions AS
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
LEFT JOIN dim_banks b ON r.bank_no = b.bank_no;
