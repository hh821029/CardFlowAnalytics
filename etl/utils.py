# etl/utils.py
import os
import logging
import pandas as pd
from typing import List, Dict
import const

logger = logging.getLogger(__name__)

OUTPUT_DIR = const.OUTPUT_DIR
TC = const.TransactionColumn


class StandardColumns:
    """
    定義各階段與目標資料表之標準欄位清單 (Standard Columns Schema)
    以 const.TransactionColumn 為單一真相來源 (SSOT)
    """
    TC = const.TransactionColumn

    # 1. 核心交易事實表 (all_transactions)
    ALL_TRANSACTIONS_MEMBERS = [
        TC.TXN_ID, TC.TXN_DATE, TC.POST_DATE, TC.CONV_DATE, TC.STAT_MON,
        TC.BANK_NAME, TC.CARD_TYPE, TC.CARD_NO, TC.MERCHANT, TC.LOCATION, 
        TC.TXN_TYPE, TC.PAYMENT_PROCESS, TC.EC_PLATFORM, TC.VPC_TYPE,
        TC.CURRENCY, TC.CURR_AMOUNT, TC.PAY_CURR, TC.PAY_AMOUNT
    ]
    ALL_TRANSACTIONS: List[str] = [m.col_name for m in ALL_TRANSACTIONS_MEMBERS]

    # 2. RFM 分析專用表 (rfm_transactions)
    RFM_MEMBERS = [
        TC.TXN_ID, TC.TXN_DATE, TC.BANK_NAME, TC.CARD_TYPE,
        TC.MERCHANT, TC.LOCATION, TC.MERCHANT_DISPLAY, TC.VPC_TYPE, 
        TC.PAYMENT_PROCESS, TC.EC_PLATFORM, TC.NORMALIZED_MERCHANT,
        TC.PAY_CURR, TC.PAY_AMOUNT, TC.TXN_TYPE,
        TC.EC_CATEGORY, TC.EC_SUB_CATEGORY, TC.CATEGORY, TC.SUB_CATEGORY
    ]
    RFM_TRANSACTIONS: List[str] = [m.col_name for m in RFM_MEMBERS]

    # 3. 回饋計算事實表 (rewards_transactions)
    REWARDS_MEMBERS = [
        TC.TXN_ID, TC.TXN_DATE, TC.POST_DATE, TC.STAT_MON, TC.BANK_NAME,
        TC.CARD_TYPE, TC.CARD_NO, TC.MERCHANT, TC.MERCHANT_DISPLAY,
        TC.PAYMENT_PROCESS, TC.EC_PLATFORM, TC.NORMALIZED_MERCHANT,
        TC.VPC_TYPE, TC.PAY_CURR, TC.PAY_AMOUNT, TC.TXN_TYPE
    ]
    REWARDS_TRANSACTIONS: List[str] = [m.col_name for m in REWARDS_MEMBERS]

    # 4. 商家維度事實表 (fact_transaction_merchants)
    MERCHANT_FACT_MEMBERS = [
        TC.TXN_ID, TC.NORMALIZED_MERCHANT, TC.PAYMENT_PROCESS, TC.EC_PLATFORM,
        TC.MERCHANT_DISPLAY, TC.CATEGORY, TC.SUB_CATEGORY
    ]
    MERCHANT_FACT_TRANSACTIONS: List[str] = [m.col_name for m in MERCHANT_FACT_MEMBERS]

    # 5. 全量/最大欄位聯集 (MAX / Refined Superset)
    MAX_TRANSACTIONS: List[str] = list(dict.fromkeys(
        ALL_TRANSACTIONS + RFM_TRANSACTIONS + REWARDS_TRANSACTIONS + MERCHANT_FACT_TRANSACTIONS
    ))

    # 6. 用於計算同日流水號 _seq 與生成 MD5 transaction_id 的基準欄位
    ID_GROUP_COLUMNS: List[str] = [
        TC.TXN_DATE.col_name,
        TC.MERCHANT.col_name,
        TC.CARD_NO.col_name,
        TC.PAY_AMOUNT.col_name,
        TC.TXN_TYPE.col_name
    ]


# 向下相容別名
STANDARD_COLUMNS: List[str] = StandardColumns.ALL_TRANSACTIONS


# ==========================================
# 2. 異常報告匯出工具 (Anomaly / Crash Report)
# ==========================================

def save_anomaly_report(df: pd.DataFrame, filename: str, message: str):
    """
    將異常或未定義的交易資料匯出至 output 資料夾，供使用者檢查。
    """
    try:
        if df is None or df.empty:
            return
        
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        report_path = os.path.join(OUTPUT_DIR, filename)
        df.to_csv(report_path, index=False, encoding='utf-8-sig')
        logger.warning(f"⚠️ {message}，已將診斷資料匯出至: {report_path}")
    except Exception as e:
        logger.error(f"❌ 無法匯出異常報告: {e}")
