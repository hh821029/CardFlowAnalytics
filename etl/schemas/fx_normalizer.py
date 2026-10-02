# etl/schemas/fx_normalizer.py
"""
匯率載入器與台幣本位幣轉換器 (FX Normalizer)
負責雙幣卡外幣交易匯率折算與標準化
"""
import os
import logging
import pandas as pd
from typing import Optional

import const

logger = logging.getLogger(__name__)


def _standardize_fx_df(df: pd.DataFrame) -> pd.DataFrame:
    """標準化匯率表欄位名稱與型態"""
    if df is None or df.empty:
        return pd.DataFrame()
    df_clean = df.copy()
    
    # 匯率欄位相容 exchange_rate / fx_rate
    if 'exchange_rate' in df_clean.columns:
        if 'fx_rate' not in df_clean.columns:
            df_clean['fx_rate'] = df_clean['exchange_rate']
        else:
            df_clean['fx_rate'] = df_clean['fx_rate'].combine_first(df_clean['exchange_rate'])
        
    # 日期與幣別處理
    if 'conversion_date' in df_clean.columns:
        df_clean['conversion_date'] = df_clean['conversion_date'].astype(str).str.strip().str.split(' ').str[0]
    if 'currency_type' in df_clean.columns:
        df_clean['currency_type'] = df_clean['currency_type'].astype(str).str.strip().str.upper()
    if 'fx_rate' in df_clean.columns:
        df_clean['fx_rate'] = pd.to_numeric(df_clean['fx_rate'], errors='coerce')
        
    required_cols = ['conversion_date', 'currency_type', 'fx_rate']
    if not all(col in df_clean.columns for col in required_cols):
        return pd.DataFrame()
        
    return df_clean.dropna(subset=required_cols)


def load_fx_table(config_dir: Optional[str] = None) -> pd.DataFrame:
    """
    雙軌載入匯率對照表：
    1. 優先從資料庫 (dim_fx_table) 讀取
    2. 備援從 profiles/.../configs/dim_fx_table.csv 讀取
    """
    # 1. 嘗試從 DB 讀取
    try:
        from database.loaders.db_reader import DBReader
        db_df = DBReader.read_sql("SELECT * FROM dim_fx_table")
        if db_df is not None and not db_df.empty:
            logger.debug("✅ 成功從資料庫 (dim_fx_table) 載入匯率資料")
            return _standardize_fx_df(db_df)
    except Exception as e:
        logger.debug(f"ℹ️ 從資料庫讀取 dim_fx_table 略過: {e}")

    # 2. 備援從 ConfigLoader 讀取 CSV
    try:
        from profiles.loaders.config_loader import ConfigLoader
        target_dir = config_dir or const.CONFIG_DIR
        csv_df = ConfigLoader.load_config(target_dir, "dim_fx_table", strategy='replace')
        if csv_df is not None and not csv_df.empty:
            logger.debug("✅ 成功從 ConfigLoader 載入 dim_fx_table.csv")
            return _standardize_fx_df(csv_df)
    except Exception as e:
        logger.warning(f"⚠️ 從 CSV 載入 dim_fx_table 失敗: {e}")

    return pd.DataFrame()


def normalize_to_twd(
    df: pd.DataFrame, 
    fx_df: Optional[pd.DataFrame] = None, 
    output_dir: Optional[str] = None
) -> pd.DataFrame:
    """
    將非 TWD 的雙幣交易依結匯日 (conversion_date) 匯率折算為台幣 (TWD)，供 RFM 與 Rewards 分析使用。
    嚴格業務規則：僅在 conversion_date 存在且 payment_currency != 'TWD' 時觸發折算。
    """
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.copy()

    df_result = df.copy()

    # 確保必要欄位存在 (若無折算日或無幣別/金額，直接略過折算)
    if (
        'conversion_date' not in df_result.columns or 
        'payment_currency' not in df_result.columns or 
        'payment_amount' not in df_result.columns
    ):
        return df_result

    # 1. 判斷需要折算的條件：conversion_date 存在 且 payment_currency 非 TWD / 空值
    has_conv_date = (
        df_result['conversion_date'].notna() & 
        (df_result['conversion_date'].astype(str).str.strip() != '') & 
        (df_result['conversion_date'].astype(str).str.lower() != 'nan') &
        (df_result['conversion_date'].astype(str).str.lower() != 'none')
    )
    is_foreign_curr = (
        df_result['payment_currency'].notna() & 
        (df_result['payment_currency'].astype(str).str.strip().str.upper() != 'TWD') & 
        (df_result['payment_currency'].astype(str).str.strip() != '') &
        (df_result['payment_currency'].astype(str).str.lower() != 'nan')
    )
    
    mask_to_convert = has_conv_date & is_foreign_curr

    if not mask_to_convert.any():
        return df_result

    count_to_convert = mask_to_convert.sum()
    logger.info(f"💱 偵測到 {count_to_convert} 筆雙幣外幣交易 (具備 conversion_date 且非 TWD)，準備進行台幣折算...")

    if fx_df is None or fx_df.empty:
        fx_df = load_fx_table()

    # 建立匯率查找映射字典: (conversion_date, currency_type) -> fx_rate
    fx_map = {}
    if fx_df is not None and not fx_df.empty and 'conversion_date' in fx_df.columns and 'currency_type' in fx_df.columns and 'fx_rate' in fx_df.columns:
        for _, row in fx_df.iterrows():
            c_date = str(row['conversion_date']).strip().split(' ')[0]
            curr = str(row['currency_type']).strip().upper()
            try:
                rate = float(row['fx_rate'])
                fx_map[(c_date, curr)] = rate
            except (ValueError, TypeError):
                continue

    missing_fx_rows = []
    
    for idx in df_result[mask_to_convert].index:
        conv_date = str(df_result.at[idx, 'conversion_date']).strip().split(' ')[0]
        pay_curr = str(df_result.at[idx, 'payment_currency']).strip().upper()
        raw_amt = df_result.at[idx, 'payment_amount']

        key = (conv_date, pay_curr)
        # 如果 payment_currency 找不到，也可嘗試 currency_type (若有)
        if key not in fx_map and 'currency_type' in df_result.columns:
            curr_type = str(df_result.at[idx, 'currency_type']).strip().upper()
            key = (conv_date, curr_type)

        if key in fx_map:
            fx_rate = fx_map[key]
            try:
                amt_val = float(raw_amt)
                converted_amt = round(amt_val * fx_rate)  # 四捨五入至整數台幣
                df_result.at[idx, 'payment_amount'] = converted_amt
                df_result.at[idx, 'payment_currency'] = 'TWD'
                logger.debug(f"💱 [折算成功] 結匯日: {conv_date}, {raw_amt} {pay_curr} * {fx_rate} -> {converted_amt} TWD")
            except (ValueError, TypeError) as conv_err:
                logger.warning(f"⚠️ 金額轉換數值失敗 (row {idx}): {conv_err}")
        else:
            logger.warning(f"⚠️ 查無匯率對照: 結匯日 [{conv_date}], 幣別 [{pay_curr}], 交易: {df_result.at[idx, 'transaction_id'] if 'transaction_id' in df_result.columns else idx}")
            missing_fx_rows.append(df_result.loc[idx])

    if missing_fx_rows:
        df_missing = pd.DataFrame(missing_fx_rows)
        logger.error(f"❌ 共有 {len(missing_fx_rows)} 筆外幣交易查無匯率，請補錄 dim_fx_table！")
        target_out = output_dir or const.OUTPUT_DIR
        if target_out:
            os.makedirs(target_out, exist_ok=True)
            missing_path = os.path.join(target_out, 'missing_fx_rate_anomalies.csv')
            df_missing.to_csv(missing_path, index=False, encoding='utf-8-sig')
            logger.info(f"🔍 查無匯率之異常明細已存至: {missing_path}")

    return df_result


__all__ = ['_standardize_fx_df', 'load_fx_table', 'normalize_to_twd']
