# analytics/api.py
"""
Analytics 分析模組統一對外進入點 (Facade API)
協調整合交易提取、RFM 客群價值模型與 Spending Matrix 交叉透視運算
"""
import os
import logging
import pandas as pd
from typing import Optional, List, Union, cast

import const
from analytics import (
    BASE_OUTPUT_DIR,
    MATRIX_OUTPUT_DIR,
    RFM_OUTPUT_DIR,
    validate_analytics_schema
)
from analytics.common import (
    get_transactions,
    query_transactions_modular
)
from analytics.rfm import (
    calculate_merchant_rfm,
    calculate_category_rfm,
    calculate_payment_rfm,
    calculate_card_rfm
)
from analytics.matrix import (
    generate_spending_matrix,
    save_spending_matrix_reports
)

logger = logging.getLogger(__name__)

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
) -> None:
    """
    執行全方位 Analytics 分析 (包含 RFM 客群分群與 Spending Matrix 交叉透視)
    """
    logger.info("🚀 [Analytics Pipeline] 啟動全方位消費分析運算...")
    
    # 1. 執行前置 Schema 檢查
    is_valid_schema, missing_cols = validate_analytics_schema()
    if not is_valid_schema:
        logger.warning(f"⚠️ [Analytics Pipeline] Schema 檢查未完全通過，缺少欄位: {missing_cols}")

    # 2. 資料提取 (動態條件篩選 vs 全歷史)
    df_raw: pd.DataFrame
    if any([banks, cards, payments, time_window, start_date, end_date, location]):
        logger.info("⚙️ 偵測到篩選參數，採用動態條件提取交易資料...")
        df_raw = query_transactions_modular(
            banks=banks,
            cards=cards,
            payments=payments,
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            location=location
        )
    else:
        df_raw = get_transactions(window=const.TimeWindow.LIFETIME)

    if df_raw.empty:
        logger.warning("❌ 提取之交易資料庫為空，終止分析流程。")
        return

    # 3. 基礎欄位與型態校正
    df_raw['transaction_date'] = pd.to_datetime(df_raw['transaction_date'])
    amount_series = pd.to_numeric(df_raw['payment_amount'], errors='coerce')
    if isinstance(amount_series, pd.Series):
        df_raw['payment_amount'] = amount_series.fillna(0)
    else:
        df_raw['payment_amount'] = pd.Series(amount_series).fillna(0)
    
    if 'normalized_merchant' not in df_raw.columns or df_raw['normalized_merchant'].dropna().empty:
        df_raw['normalized_merchant'] = df_raw.get('merchant_display', df_raw.get('merchant_name', ''))
        
    if 'category' not in df_raw.columns:
        df_raw['category'] = '未分類'
    else:
        df_raw['category'] = df_raw['category'].fillna('未分類')
        
    if 'sub_category' not in df_raw.columns:
        df_raw['sub_category'] = ''
    else:
        df_raw['sub_category'] = df_raw['sub_category'].fillna('')

    logger.info(f"✅ 成功載入 {len(df_raw)} 筆交易資料。")

    # 4. 類別與次類別篩選 (若有傳入)
    if categories:
        df_raw = cast(pd.DataFrame, df_raw[df_raw['category'].isin(categories)].copy())
        logger.info(f"🧹 已依主分類篩選 ({categories})，剩餘 {len(df_raw)} 筆。")
        
    if sub_categories:
        has_no_sub = '無次分類' in sub_categories or '' in sub_categories
        mask = df_raw['sub_category'].isin(sub_categories)
        if has_no_sub:
            sub_cat_str = df_raw['sub_category'].astype(str).str.strip()
            mask = mask | (df_raw['sub_category'] == '') | df_raw['sub_category'].isna() | sub_cat_str.isin(['', 'nan', 'None'])
        df_raw = cast(pd.DataFrame, df_raw[mask].copy())
        logger.info(f"🧹 已依次分類篩選 ({sub_categories})，剩餘 {len(df_raw)} 筆。")

    if df_raw.empty:
        logger.warning("⚠️ 篩選後無符合條件之交易資料。")
        return

    # ==========================================
    # 5. 執行分析模型計算
    # ==========================================
    logger.info("⚙️ 執行 RFM 客群與資產價值模型運算...")
    
    # A. 商家 RFM
    df_merchant = calculate_merchant_rfm(df_raw, RFM_WINDOWS)
    logger.info(f"   -> Merchant RFM: {len(df_merchant)} 筆商家")

    # B. 消費類別 RFM
    df_category = calculate_category_rfm(df_raw, RFM_WINDOWS)
    logger.info(f"   -> Category RFM: {len(df_category)} 個消費類別")
    
    # C. 支付管道 RFM
    df_payment = calculate_payment_rfm(df_raw, RFM_WINDOWS)
    logger.info(f"   -> Payment RFM: {len(df_payment)} 種支付方式")
    
    # D. 信用卡 RFM
    df_card = calculate_card_rfm(df_raw, RFM_WINDOWS)
    logger.info(f"   -> Card RFM: {len(df_card)} 張信用卡")
    
    # E. 消費交叉矩陣 (Spending Matrix)
    logger.info("⚙️ 執行 Spending Matrix 交叉透視運算...")
    matrix_results = generate_spending_matrix(df_raw, MATRIX_WINDOWS, output_dir=MATRIX_OUTPUT_DIR)
    logger.info(f"   -> Matrix: 產出 {len(matrix_results)} 份消費矩陣報表")

    # ==========================================
    # 6. 輸出報表
    # ==========================================
    logger.info("💾 儲存 Matrix 報表至 output/matrix/ ...")
    save_spending_matrix_reports(matrix_results, output_dir=MATRIX_OUTPUT_DIR)
    
    logger.info("💾 儲存 RFM 報表至 output/rfm/ ...")
    try:
        if not df_merchant.empty:
            df_merchant.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'merchant_rfm.csv'), index=False, encoding='utf-8-sig')
            logger.info(f"   ✅ [RFM CSV] 商家報表已儲存: {os.path.join(RFM_OUTPUT_DIR, 'merchant_rfm.csv')}")
        if not df_category.empty:
            df_category.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'category_rfm.csv'), index=False, encoding='utf-8-sig')
            logger.info(f"   ✅ [RFM CSV] 消費類別報表已儲存: {os.path.join(RFM_OUTPUT_DIR, 'category_rfm.csv')}")
        if not df_payment.empty:
            df_payment.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'payment_rfm.csv'), index=False, encoding='utf-8-sig')
            logger.info(f"   ✅ [RFM CSV] 支付管道報表已儲存: {os.path.join(RFM_OUTPUT_DIR, 'payment_rfm.csv')}")
        if not df_card.empty:
            df_card.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'card_rfm.csv'), index=False, encoding='utf-8-sig')
            logger.info(f"   ✅ [RFM CSV] 信用卡報表已儲存: {os.path.join(RFM_OUTPUT_DIR, 'card_rfm.csv')}")
    except Exception as e:
        logger.warning(f"⚠️ 儲存 RFM 報表時發生錯誤: {e}")
        
    logger.info("🎉 [Analytics Pipeline] 全方位消費分析執行完畢！")

__all__ = ['run_analytics']
