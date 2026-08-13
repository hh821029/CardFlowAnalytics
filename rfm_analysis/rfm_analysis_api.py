# rfm_analysis/rfm_analysis_api.py
"""
RFM 分析模組對外統一進入點 (Facade API)
提供獨立且高內聚的 RFM 分群計算、多維度矩陣分析與報表產出功能
"""
import os
import pandas as pd
import logging
from typing import Optional, List, Union

import const
from rfm_analysis.rfm_modules import (
    calculate_merchant_rfm,
    calculate_payment_rfm,
    calculate_card_rfm,
    generate_spending_matrix
)
import database.database_api as ts

logger = logging.getLogger(__name__)

OUTPUT_DIR = const.OUTPUT_DIR
DB_PATH = const.DB_PATH
MATRIX_DIR = os.path.join(OUTPUT_DIR, 'matrix')
CONFIG_DIR = const.CONFIG_DIR

os.makedirs(MATRIX_DIR, exist_ok=True)

RFM_WINDOWS = const.TimeWindow.to_legacy_list()
MATRIX_WINDOWS = const.TimeWindow.to_list()

def run_analytics(
    banks: Optional[List[str]] = None,
    cards: Optional[List[str]] = None,
    payments: Optional[List[str]] = None,
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[Union[str, List[str]]] = None,
    categories: Optional[List[str]] = None,
    sub_categories: Optional[List[str]] = None
):
    """
    執行全方位 RFM 分析計算並導出報表
    """
    logger.info("🚀 [RFM Analytics Pipeline] 開始執行全方位 RFM 分析...")

    # 若有傳入任何篩選條件，採用動態 SQL 查詢；否則使用預設之全歷史
    if any([banks, cards, payments, time_window, start_date, end_date, location]):
        logger.info("⚙️ 偵測到篩選參數，將採用動態 SQL 篩選交易資料進行分析...")
        df_raw = ts.query_transactions_modular(
            banks=banks,
            cards=cards,
            payments=payments,
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            location=location
        )
    else:
        df_raw = ts.get_transactions(window=const.TimeWindow.LIFETIME)

    if df_raw.empty:
        logger.error("❌ 資料庫無資料，終止程序。")
        return

    # 基礎型態轉換與欄位補位
    df_raw['transaction_date'] = pd.to_datetime(df_raw['transaction_date'])
    amount_series = pd.to_numeric(df_raw['payment_amount'], errors='coerce')
    if isinstance(amount_series, pd.Series):
        df_raw['payment_amount'] = amount_series.fillna(0)
    else:
        df_raw['payment_amount'] = pd.Series(amount_series).fillna(0)
    
    if 'normalized_merchant' not in df_raw.columns or df_raw['normalized_merchant'].dropna().empty:
        df_raw['normalized_merchant'] = df_raw.get('merchant_display', '')

    if 'ec_platform' not in df_raw.columns:
        df_raw['ec_platform'] = ''
    else:
        df_raw['ec_platform'] = df_raw['ec_platform'].fillna('')

    # 自動補位 ec_platform (若為空則從 dim_ec_platform.csv 正則判定)
    ec_config_path = os.path.join(CONFIG_DIR, 'dim_ec_platform.csv')
    if os.path.exists(ec_config_path):
        try:
            df_ec = pd.read_csv(ec_config_path, dtype=str)
            for _, ec_row in df_ec.iterrows():
                pat = ec_row.get('ec_platform_pattern') or ec_row.get('pattern')
                ec_name = ec_row.get('ec_platform') or ec_row.get('platform')
                if pat and ec_name:
                    empty_ec_mask = (df_raw['ec_platform'] == '')
                    match_mask = df_raw['merchant_display'].astype(str).str.contains(pat, regex=True, na=False) | \
                                 df_raw['normalized_merchant'].astype(str).str.contains(pat, regex=True, na=False)
                    df_raw.loc[empty_ec_mask & match_mask, 'ec_platform'] = ec_name
        except Exception as e_ec:
            logger.debug(f"動態補位 ec_platform 異常: {e_ec}")

    if 'payment_process' not in df_raw.columns:
        df_raw['payment_process'] = ''
    else:
        df_raw['payment_process'] = df_raw['payment_process'].fillna('')

    # [動態補回 Category & Sub_Category] 
    is_category_unfilled = 'category' not in df_raw.columns or (df_raw['category'].fillna('未分類') == '未分類').all() or df_raw['category'].dropna().empty
    if is_category_unfilled:
        merchants_config_path = os.path.join(CONFIG_DIR, 'dim_merchants.csv')
        if os.path.exists(merchants_config_path):
            df_merchants = pd.read_csv(merchants_config_path, dtype=str)
            category_map_norm = dict(zip(df_merchants['normalized_merchant'].dropna(), df_merchants['category']))
            category_map_disp = dict(zip(df_merchants['merchant_display'].dropna(), df_merchants['category']))
            
            sub_category_map_norm = dict(zip(df_merchants['normalized_merchant'].dropna(), df_merchants.get('sub_category', pd.Series(''))))
            sub_category_map_disp = dict(zip(df_merchants['merchant_display'].dropna(), df_merchants.get('sub_category', pd.Series(''))))

            # 雙重 map: 先用 normalized_merchant 查，若無再用 merchant_display 查
            cat_series = df_raw['normalized_merchant'].map(category_map_norm).fillna(df_raw['merchant_display'].map(category_map_disp)).fillna('未分類')
            sub_cat_series = df_raw['normalized_merchant'].map(sub_category_map_norm).fillna(df_raw['merchant_display'].map(sub_category_map_disp)).fillna('')

            df_raw['category'] = cat_series
            df_raw['sub_category'] = sub_cat_series
        else:
            logger.warning("⚠️ 找不到 dim_merchants.csv，所有交易將標記為 '未分類'")
            df_raw['category'] = '未分類'
            df_raw['sub_category'] = ''
    else:
        df_raw['category'] = df_raw['category'].fillna('未分類')
        df_raw['sub_category'] = df_raw.get('sub_category', pd.Series('')).fillna('')

    logger.info(f"✅ 成功載入 {len(df_raw)} 筆交易資料，已設置 normalized_merchant、ec_platform、payment_process 與分類資訊。")

    # 暫時資料輸出至 output/rfm_raw_matrix.csv 供檢查
    try:
        debug_output_path = os.path.join(const.OUTPUT_DIR, 'rfm_raw_matrix.csv')
        df_raw.to_csv(debug_output_path, index=False, encoding='utf-8-sig')
        logger.info(f"📊 [診斷匯出] 已將 {len(df_raw)} 筆全量原始矩陣資料輸出至: {debug_output_path}")
    except Exception as debug_e:
        logger.warning(f"⚠️ 匯出診斷資料失敗: {debug_e}")

    # [篩選消費類別] (僅在傳入有效非空清單時進行篩選)
    if categories:
        df_raw = df_raw[df_raw['category'].isin(categories)]
        logger.info(f"🧹 已依據消費類別進行篩選 ({categories})，剩下 {len(df_raw)} 筆交易資料。")

    # [篩選消費次類別] (僅在傳入有效非空清單時進行篩選)
    if sub_categories:
        has_no_sub = '無次分類' in sub_categories or '' in sub_categories
        mask = df_raw['sub_category'].isin(sub_categories)
        if has_no_sub:
            sub_cat_str = df_raw['sub_category'].astype(str).str.strip()
            mask = mask | (df_raw['sub_category'] == '') | df_raw['sub_category'].isna() | sub_cat_str.isin(['', 'nan', 'None'])
        df_raw = df_raw[mask]
        logger.info(f"🧹 已依據消費次類別進行篩選 ({sub_categories})，剩下 {len(df_raw)} 筆交易資料。")

    # ==========================================
    # 分發與計算 (Transform)
    # ==========================================
    logger.info("⚙️ 執行各分析模組...")
    
    # A. 商家 RFM
    df_merchant = calculate_merchant_rfm(df_raw, RFM_WINDOWS)
    logger.info(f"   -> Merchant RFM: {len(df_merchant)} 筆商家")
    
    # B. 支付 RFM
    df_payment = calculate_payment_rfm(df_raw, RFM_WINDOWS)
    logger.info(f"   -> Payment RFM: {len(df_payment)} 種支付方式")
    
    # C. 信用卡 RFM
    df_card = calculate_card_rfm(df_raw, RFM_WINDOWS)
    logger.info(f"   -> Card RFM: {len(df_card)} 張信用卡")
    
    # D. 消費矩陣 (CSV Report)
    matrix_results = generate_spending_matrix(df_raw, MATRIX_WINDOWS)
    logger.info(f"   -> Matrix: 產出 {len(matrix_results)} 份消費矩陣報表")

    # ==========================================
    # 寫入結果 (Load)
    # ==========================================
    logger.info("💾 儲存分析結果...")
    
    try:
        for filename, df_matrix in matrix_results:
            csv_path = os.path.join(MATRIX_DIR, filename)
            df_matrix.round(2).to_csv(csv_path, encoding='utf-8-sig')
            logger.info(f"   ✅ [CSV] 報表已儲存: {csv_path}")
            
    except Exception as e:
        logger.error(f"❌ 寫入過程發生錯誤: {e}", exc_info=True)
