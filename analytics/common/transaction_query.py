# database/transaction_query.py
"""
交易資料庫專用查詢器 (Transaction Query Repository / DAO)
提供跨資料庫 (SQLite / PostgreSQL) 相容之交易提取與動態條件查詢功能
預設查詢預先建構之全維度 rfm_transactions 視圖 (含商家正規化、支付管道與持卡對照)
"""
import os
import pandas as pd
import logging
from typing import Optional, List, Union
import const
from database.loaders.db_reader import DBReader

logger = logging.getLogger(__name__)

def get_transactions(
    window: const.TimeWindow = const.TimeWindow.LAST_YEAR,
    exclude_non_retail: bool = False,
    anchor_date: Optional[str] = None,
    db_path: str = const.DB_PATH
) -> pd.DataFrame:
    """
    通用交易資料讀取服務 (預設讀取已整合全維度資訊之 rfm_transactions 視圖，相容 SQLite / PostgreSQL)
    """
    conditions = []
    params = {}
    
    # 統一 SQL 欄位映射與型態強轉 (SSOT 對齊，查詢預先建構好的 rfm_transactions 視圖)
    query_parts = [
        "t.transaction_id",
        f"t.transaction_date AS {const.COL_TXN_DATE}",
        f"t.bank_name AS {const.COL_BANK_NAME}",
        f"CAST(t.card_type AS TEXT) AS {const.COL_CARD_TYPE}",
        f"t.merchant_name AS {const.COL_MERCHANT}",
        f"t.merchant_display AS {const.COL_MERCHANT_DISPLAY}",
        f"t.merchant_location AS {const.COL_LOCATION}",
        f"t.normalized_merchant AS {const.COL_NORMALIZED_MERCHANT}",
        f"t.payment_process AS {const.COL_PAYMENT_PROCESS}",
        f"t.ec_platform AS {const.COL_EC_PLATFORM}",
        f"t.payment_currency AS {const.COL_PAY_CURR}",
        f"CAST(t.payment_amount AS REAL) AS {const.COL_PAY_AMOUNT}",
        f"t.category AS {const.COL_CATEGORY}",
        f"t.sub_category AS {const.COL_SUB_CATEGORY}",
        f"'交易' AS {const.COL_TXN_TYPE}"
    ]
    
    # 動態獲取最新交易日作為 anchor_date
    if not anchor_date and window != const.TimeWindow.LIFETIME:
        try:
            df_max = DBReader.read_sql("SELECT max(transaction_date) AS max_date FROM rfm_transactions", db_path=db_path)
            if not df_max.empty and pd.notna(df_max['max_date'].iloc[0]):
                anchor_date = str(df_max['max_date'].iloc[0]).split()[0]
        except Exception as e:
            logger.debug(f"無法取得 max transaction_date: {e}")

    start_date = window.get_start_date(anchor_date)
    if start_date:
        conditions.append("t.transaction_date >= :start_date")
        params["start_date"] = start_date
        
    sql = f"SELECT {', '.join(query_parts)} FROM rfm_transactions t"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
        
    try:
        df = DBReader.read_sql(sql, params=params, parse_dates=[const.COL_TXN_DATE], db_path=db_path)
        logger.info(f"📥 [DB 提取 (rfm_transactions)] 成功載入 {len(df)} 筆交易資料 (時間視窗: {window.name}, 基準日: {anchor_date})")
        return df
    except Exception as e:
        logger.warning(f"⚠️ 讀取 rfm_transactions 視圖失敗 ({e})，降級嘗試從 all_transactions 原始表讀取...")
        try:
            fallback_parts = [
                "transaction_id",
                f"transaction_date AS {const.COL_TXN_DATE}",
                f"merchant_name AS {const.COL_MERCHANT}",
                f"merchant_display AS {const.COL_MERCHANT_DISPLAY}",
                f"normalized_merchant AS {const.COL_NORMALIZED_MERCHANT}",
                "'' AS ec_platform",
                "'' AS payment_process",
                f"merchant_location AS {const.COL_LOCATION}",
                f"CAST(payment_amount AS REAL) AS {const.COL_PAY_AMOUNT}",
                "'' AS card_type",
                f"bank_name AS {const.COL_BANK_NAME}",
                f"transaction_type AS {const.COL_TXN_TYPE}"
            ]
            fallback_sql = f"SELECT {', '.join(fallback_parts)} FROM all_transactions"
            fb_conditions = [c.replace("t.", "") for c in conditions]
            if fb_conditions: fallback_sql += " WHERE " + " AND ".join(fb_conditions)
            df = DBReader.read_sql(fallback_sql, params=params, parse_dates=[const.COL_TXN_DATE], db_path=db_path)
            df['category'] = '未分類'
            df['sub_category'] = ''
            return df
        except Exception as fb_err:
            logger.error(f"❌ 讀取交易資料庫失敗: {fb_err}", exc_info=True)
            return pd.DataFrame()

def _resolve_bank_names(bank_inputs: List[str]) -> List[str]:
    """
    依據 dim_banks.yaml 定義，將傳入之 bank_id 或 bank_name 解析為所有可能的中文名稱與代碼集合
    """
    resolved = set()
    all_banks = const.get_all_banks()
    bank_map = {}
    for b in all_banks:
        b_id = str(b.get('bank_id', '')).strip().lower()
        b_name = str(b.get('bank_name', '')).strip()
        b_mapping = str(b.get('bills_mapping_name', '')).strip()
        names = {b_id, b_name, b_mapping}.union(set(b.get('keywords', [])))
        valid_names = {n for n in names if n and n.lower() != 'none' and n.lower() != 'nan'}
        for n in valid_names:
            bank_map[n.lower()] = valid_names
    
    for item in bank_inputs:
        item_str = str(item).strip()
        item_lower = item_str.lower()
        if item_lower in bank_map:
            resolved.update(bank_map[item_lower])
        else:
            resolved.add(item_str)
            
    return [r for r in resolved if r]

def query_transactions_modular(
    banks: Optional[List[str]] = None,
    cards: Optional[List[str]] = None,
    payments: Optional[List[str]] = None,
    include_direct_payment: bool = True,
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[Union[str, List[str]]] = None,
    exclude_non_retail: bool = False,
    db_path: str = const.DB_PATH,
    limit_by_card_start: bool = False
) -> pd.DataFrame:
    """
    動態 SQL 條件查詢服務 (直接查詢預先構建好之 rfm_transactions 視圖，相容 SQLite / PostgreSQL)
    """
    conditions = []
    params = {}
    
    query_parts = [
        "t.transaction_id",
        f"t.transaction_date AS {const.COL_TXN_DATE}",
        f"t.merchant_name AS {const.COL_MERCHANT}",
        f"t.merchant_display AS {const.COL_MERCHANT_DISPLAY}",
        f"t.normalized_merchant AS {const.COL_NORMALIZED_MERCHANT}",
        f"t.ec_platform AS {const.COL_EC_PLATFORM}",
        f"t.payment_process AS {const.COL_PAYMENT_PROCESS}",
        f"t.category AS {const.COL_CATEGORY}",
        f"t.sub_category AS {const.COL_SUB_CATEGORY}",
        f"t.merchant_location AS {const.COL_LOCATION}",
        f"CAST(t.payment_amount AS REAL) AS {const.COL_PAY_AMOUNT}",
        f"CAST(t.card_type AS TEXT) AS {const.COL_CARD_TYPE}",
        f"t.bank_name AS {const.COL_BANK_NAME}",
        f"'交易' AS {const.COL_TXN_TYPE}"
    ]

    anchor_date = None
    if time_window or (not start_date and not end_date):
        try:
            df_max = DBReader.read_sql("SELECT max(transaction_date) AS max_date FROM rfm_transactions", db_path=db_path)
            if not df_max.empty and pd.notna(df_max['max_date'].iloc[0]):
                anchor_date = str(df_max['max_date'].iloc[0]).split()[0]
        except Exception:
            pass

    if time_window:
        try:
            tw_enum = const.TimeWindow[time_window]
            calculated_start = tw_enum.get_start_date(anchor_date)
            if calculated_start:
                conditions.append("t.transaction_date >= :start_date")
                params["start_date"] = calculated_start
            if anchor_date:
                conditions.append("t.transaction_date <= :end_date")
                params["end_date"] = anchor_date
        except KeyError:
            logger.warning(f"⚠️ 傳入未知的時間視窗名稱: {time_window}，將略過預設時間篩選。")
    else:
        if start_date:
            conditions.append("t.transaction_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            conditions.append("t.transaction_date <= :end_date")
            params["end_date"] = end_date

    if banks:
        resolved_banks = _resolve_bank_names(banks)
        bank_placeholders = [f":bank_{i}" for i in range(len(resolved_banks))]
        for i, b in enumerate(resolved_banks):
            params[f"bank_{i}"] = b
        conditions.append(f"t.bank_name IN ({', '.join(bank_placeholders)})")

    if cards:
        card_placeholders = [f":card_{i}" for i in range(len(cards))]
        for i, c in enumerate(cards):
            params[f"card_{i}"] = c
        conditions.append(f"t.card_type IN ({', '.join(card_placeholders)})")

    if payments is not None:
        if payments:
            pay_placeholders = [f":pay_{i}" for i in range(len(payments))]
            for i, p in enumerate(payments):
                params[f"pay_{i}"] = p
            if include_direct_payment:
                conditions.append(f"(t.payment_process IN ({', '.join(pay_placeholders)}) OR t.payment_process IS NULL OR t.payment_process = '')")
            else:
                conditions.append(f"t.payment_process IN ({', '.join(pay_placeholders)})")
        else:
            if include_direct_payment:
                conditions.append("(t.payment_process IS NULL OR t.payment_process = '')")
            else:
                conditions.append("1 = 0")
    elif not include_direct_payment:
        conditions.append("(t.payment_process IS NOT NULL AND t.payment_process <> '')")

    if location:
        if isinstance(location, list):
            loc_placeholders = [f":loc_{i}" for i in range(len(location))]
            for i, l in enumerate(location):
                params[f"loc_{i}"] = l
            conditions.append(f"t.merchant_location IN ({', '.join(loc_placeholders)})")
        else:
            conditions.append("t.merchant_location = :location")
            params["location"] = location

    sql = f"SELECT {', '.join(query_parts)} FROM rfm_transactions t"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    
    sql += " ORDER BY t.transaction_date DESC"

    try:
        df = DBReader.read_sql(sql, params=params, parse_dates=[const.COL_TXN_DATE], db_path=db_path)
        logger.info(f"📥 [DB 條件篩選 (rfm_transactions)] 成功載入 {len(df)} 筆交易資料 (條件數: {len(conditions)})")
        return df
    except Exception as e:
        logger.warning(f"⚠️ 讀取 rfm_transactions 視圖條件查詢失敗 ({e})，降級嘗試從 all_transactions 原始表讀取...")
        try:
            fallback_parts = [
                "transaction_id",
                f"transaction_date AS {const.COL_TXN_DATE}",
                f"merchant_name AS {const.COL_MERCHANT}",
                f"merchant_display AS {const.COL_MERCHANT_DISPLAY}",
                f"normalized_merchant AS {const.COL_NORMALIZED_MERCHANT}",
                "'' AS ec_platform",
                "'' AS payment_process",
                f"merchant_location AS {const.COL_LOCATION}",
                f"CAST(payment_amount AS REAL) AS {const.COL_PAY_AMOUNT}",
                "'' AS card_type",
                f"bank_name AS {const.COL_BANK_NAME}",
                f"transaction_type AS {const.COL_TXN_TYPE}"
            ]
            fallback_sql = f"SELECT {', '.join(fallback_parts)} FROM all_transactions"
            fb_conditions = [c.replace("t.", "") for c in conditions]
            if fb_conditions: fallback_sql += " WHERE " + " AND ".join(fb_conditions)
            fallback_sql += " ORDER BY transaction_date DESC"
            df = DBReader.read_sql(fallback_sql, params=params, parse_dates=[const.COL_TXN_DATE], db_path=db_path)
            df['category'] = '未分類'
            df['sub_category'] = ''
            return df
        except Exception as fb_err:
            logger.error(f"❌ 條件查詢交易資料庫失敗: {fb_err}", exc_info=True)
            return pd.DataFrame()
