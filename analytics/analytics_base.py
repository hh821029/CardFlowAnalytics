# analytics/analytics_base.py
"""
Analytics 分析基礎管線模組 (Base Pipeline)
負責統一 Schema 檢查、交易資料提取、型態強轉、基礎空值補齊與分類篩選等前置流程
"""
import logging
import pandas as pd
from typing import Optional, List, Union, cast

import const
from analytics import validate_analytics_schema
from analytics.common import (
    get_transactions,
    query_transactions_modular
)

logger = logging.getLogger(__name__)


def prepare_analytics_dataset(
    banks: Optional[List[str]] = None,
    cards: Optional[List[str]] = None,
    payments: Optional[List[str]] = None,
    include_direct_payment: bool = True,
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[Union[str, List[str]]] = None,
    categories: Optional[List[str]] = None,
    sub_categories: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    通用前置資料管線：執行 Schema 驗證、依條件提取交易資料、型態強轉、欄位修復與分類篩選。
    回傳清洗後可直接進入模型運算的 DataFrame。若無資料則回傳空的 DataFrame。
    """
    # 1. 執行前置 Schema 檢查
    is_valid_schema, missing_cols = validate_analytics_schema()
    if not is_valid_schema:
        logger.warning(f"⚠️ [Analytics Base] Schema 檢查未完全通過，缺少欄位: {missing_cols}")

    # 2. 資料提取 (動態條件篩選 vs 全歷史)
    df_raw: pd.DataFrame
    if any([banks, cards, payments, time_window, start_date, end_date, location]) or not include_direct_payment:
        logger.info("⚙️ [Analytics Base] 偵測到篩選參數，採用動態條件提取交易資料...")
        df_raw = query_transactions_modular(
            banks=banks,
            cards=cards,
            payments=payments,
            include_direct_payment=include_direct_payment,
            time_window=time_window,
            start_date=start_date,
            end_date=end_date,
            location=location
        )
    else:
        df_raw = get_transactions(window=const.TimeWindow.LIFETIME)

    if df_raw is None or df_raw.empty:
        logger.warning("❌ [Analytics Base] 提取之交易資料庫為空。")
        return pd.DataFrame()

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

    logger.info(f"✅ [Analytics Base] 成功載入並清洗 {len(df_raw)} 筆交易資料。")

    # 4. 類別與次類別篩選 (若有傳入)
    if categories:
        df_raw = cast(pd.DataFrame, df_raw[df_raw['category'].isin(categories)].copy())
        logger.info(f"🧹 [Analytics Base] 已依主分類篩選 ({categories})，剩餘 {len(df_raw)} 筆。")
    else:
        # 預設排除非日常消費分類 (未分類、銀行費用)
        df_raw = cast(pd.DataFrame, df_raw[~df_raw['category'].isin(['未分類', '銀行費用'])].copy())

    if sub_categories:
        has_no_sub = '無次分類' in sub_categories or '' in sub_categories
        mask = df_raw['sub_category'].isin(sub_categories)
        if has_no_sub:
            sub_cat_str = df_raw['sub_category'].astype(str).str.strip()
            mask = mask | (df_raw['sub_category'] == '') | df_raw['sub_category'].isna() | sub_cat_str.isin(['', 'nan', 'None'])
        df_raw = cast(pd.DataFrame, df_raw[mask].copy())
        logger.info(f"🧹 [Analytics Base] 已依次分類篩選 ({sub_categories})，剩餘 {len(df_raw)} 筆。")

    return df_raw


class BaseAnalyticsPipeline:
    """
    分析管線基礎類別，提供子模組繼承或統一調用標準生命週期。
    """
    def __init__(self, **filters):
        self.filters = filters
        self.df_clean: pd.DataFrame = pd.DataFrame()

    def prepare_data(self) -> pd.DataFrame:
        self.df_clean = prepare_analytics_dataset(**self.filters)
        return self.df_clean
