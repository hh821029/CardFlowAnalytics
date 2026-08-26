# analytics/api.py
"""
Analytics 分析模組統一對外進入點 (Facade API)
協調整合交易提取、RFM 客群價值模型、Spending Matrix 交叉透視、多維度月度聚合、金流桑基圖運算與 Data Mart 資料超市入庫
"""
import os
import sqlite3
import logging
import pandas as pd
from typing import Optional, List, Union, Dict, Any

import const
from analytics import (
    BASE_OUTPUT_DIR,
    MATRIX_OUTPUT_DIR,
    RFM_OUTPUT_DIR
)
from analytics.analytics_base import prepare_analytics_dataset
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
from analytics.common import (
    aggregate_monthly_by_category,
    aggregate_monthly_by_card,
    aggregate_monthly_by_payment,
    aggregate_monthly_card_category,
    generate_monthly_pivot
)
from analytics.sankeyflow import build_sankey_flow, build_sankey_dataframe

logger = logging.getLogger(__name__)

RFM_WINDOWS = const.TimeWindow.to_legacy_list()
MATRIX_WINDOWS = const.TimeWindow.to_list()


def _save_to_data_mart(tables: Dict[str, pd.DataFrame], db_path: str = const.ANALYSIS_DB_PATH) -> None:
    """將分析結果結構化寫入 TransactionsAnalysis.db 資料庫"""
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            for table_name, df_table in tables.items():
                if df_table is not None and not df_table.empty:
                    df_table.to_sql(table_name, conn, if_exists='replace', index=False)
                    logger.debug(f"   💾 [Data Mart] 表 [{table_name}] 已成功寫入 {len(df_table)} 筆。")
        logger.info(f"✅ [Data Mart] 成功同步分析數據至資料庫: {db_path}")
    except Exception as e:
        logger.error(f"❌ [Data Mart] 寫入 TransactionsAnalysis.db 失敗: {e}")


def run_analytics(
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
) -> None:
    """
    執行全方位 Analytics 分析 (包含 RFM 客群分群、Spending Matrix 交叉透視、月度多維度聚合、金流桑基圖與 Data Mart 入庫)
    """
    logger.info("🚀 [Analytics Pipeline] 啟動全方位消費分析運算...")

    # 1. 透過 Base Pipeline 進行資料提取與清洗
    df_raw = prepare_analytics_dataset(
        banks=banks,
        cards=cards,
        payments=payments,
        include_direct_payment=include_direct_payment,
        time_window=time_window,
        start_date=start_date,
        end_date=end_date,
        location=location,
        categories=categories,
        sub_categories=sub_categories
    )

    if df_raw.empty:
        logger.warning("⚠️ 篩選後無符合條件之交易資料，終止後續分析。")
        return

    # ==========================================
    # 2. 執行各子模型計算
    # ==========================================
    logger.info("⚙️ 執行 RFM 客群與資產價值模型運算...")
    df_merchant = calculate_merchant_rfm(df_raw, RFM_WINDOWS)
    df_category = calculate_category_rfm(df_raw, RFM_WINDOWS)
    df_payment = calculate_payment_rfm(df_raw, RFM_WINDOWS)
    df_card = calculate_card_rfm(df_raw, RFM_WINDOWS)

    logger.info("⚙️ 執行 Spending Matrix 交叉透視運算...")
    matrix_results = generate_spending_matrix(df_raw, MATRIX_WINDOWS, output_dir=MATRIX_OUTPUT_DIR)

    logger.info("⚙️ 執行月度多維度 GroupBy 與樞紐分析運算...")
    df_monthly_category = aggregate_monthly_by_category(df_raw)
    df_monthly_card = aggregate_monthly_by_card(df_raw)
    df_monthly_payment = aggregate_monthly_by_payment(df_raw)
    df_monthly_card_category = aggregate_monthly_card_category(df_raw)

    logger.info("⚙️ 執行金流桑基圖 (Sankey Flow) 運算...")
    df_sankey_links = build_sankey_dataframe(df_raw)

    # ==========================================
    # 3. 輸出報表 (CSV)
    # ==========================================
    logger.info("💾 儲存 Matrix 報表至 output/matrix/ ...")
    save_spending_matrix_reports(matrix_results, output_dir=MATRIX_OUTPUT_DIR)

    logger.info("💾 儲存 RFM 報表至 output/rfm/ ...")
    try:
        if not df_merchant.empty:
            df_merchant.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'merchant_rfm.csv'), index=False, encoding='utf-8-sig')
        if not df_category.empty:
            df_category.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'category_rfm.csv'), index=False, encoding='utf-8-sig')
        if not df_payment.empty:
            df_payment.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'payment_rfm.csv'), index=False, encoding='utf-8-sig')
        if not df_card.empty:
            df_card.round(2).to_csv(os.path.join(RFM_OUTPUT_DIR, 'card_rfm.csv'), index=False, encoding='utf-8-sig')
    except Exception as e:
        logger.warning(f"⚠️ 儲存 RFM 報表時發生錯誤: {e}")

    # ==========================================
    # 4. 結構化資料入庫 (TransactionsAnalysis.db - Data Mart)
    # ==========================================
    logger.info("💾 同步資料至分析資料超市 (TransactionsAnalysis.db)...")
    mart_tables = {
        'rfm_merchants': df_merchant,
        'rfm_categories': df_category,
        'rfm_payments': df_payment,
        'rfm_cards': df_card,
        'matrix_monthly_category': df_monthly_category,
        'matrix_monthly_card': df_monthly_card,
        'matrix_monthly_payment': df_monthly_payment,
        'matrix_monthly_detail': df_monthly_card_category,
        'sankey_flow_links': df_sankey_links
    }
    _save_to_data_mart(mart_tables)

    logger.info("🎉 [Analytics Pipeline] 全方位消費分析執行完畢！")


__all__ = ['run_analytics']
