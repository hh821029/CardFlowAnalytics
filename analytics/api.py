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


def sync_rewards_data_mart(detailed_csv_path: Optional[str] = None, db_path: str = const.ANALYSIS_DB_PATH) -> bool:
    """
    將 C# 回饋計算結果 (reward_calculation_detailed.csv) 彙總並結構化寫入 TransactionsAnalysis.db
    產生兩張資料超市表：
    1. rewards_monthly_summary (月份 x 銀行 x 卡別之消費總額、回饋總額、實質回饋率)
    2. rewards_pool_utilization (回饋池使用狀況與上限使用率)
    """
    import numpy as np
    if not detailed_csv_path:
        detailed_csv_path = os.path.join(const.OUTPUT_DIR, 'reward_dotnet', 'detail', 'reward_calculation_detailed.csv')

    if not os.path.exists(detailed_csv_path):
        alt_path = os.path.join(const.OUTPUT_DIR, 'reward_calculation_detailed.csv')
        if os.path.exists(alt_path):
            detailed_csv_path = alt_path
        else:
            logger.warning(f"⚠️ 找不到回饋明細檔: {detailed_csv_path}")
            return False

    try:
        df = pd.read_csv(detailed_csv_path, encoding='utf-8')
        if df.empty:
            return False

        if 'transaction_date' in df.columns:
            dt_series = pd.to_datetime(df['transaction_date'], errors='coerce')
            if isinstance(dt_series, pd.Series):
                df['month'] = dt_series.dt.strftime('%Y-%m').fillna('未知月份')
            elif hasattr(dt_series, 'strftime') and pd.notna(dt_series):
                df['month'] = dt_series.strftime('%Y-%m')
            else:
                df['month'] = '未知月份'
        else:
            df['month'] = '未知月份'

        if 'payment_amount' in df.columns:
            payment_series = pd.to_numeric(df['payment_amount'], errors='coerce')
            df['payment_amount'] = payment_series.fillna(0.0) if isinstance(payment_series, pd.Series) else (0.0 if pd.isna(payment_series) else payment_series)
        else:
            df['payment_amount'] = 0.0

        if 'calculated_reward' in df.columns:
            reward_series = pd.to_numeric(df['calculated_reward'], errors='coerce')
            df['calculated_reward'] = reward_series.fillna(0.0) if isinstance(reward_series, pd.Series) else (0.0 if pd.isna(reward_series) else reward_series)
        else:
            df['calculated_reward'] = 0.0

        # 1. rewards_monthly_summary 彙總 (消費金額依交易 ID 去重後加總)
        group_keys = ['month', 'bank_name', 'card_type']
        valid_keys = [k for k in group_keys if k in df.columns]

        if 'transaction_id' in df.columns:
            txn_spending = df.groupby(valid_keys + ['transaction_id'])['payment_amount'].first().reset_index()
            monthly_spending = txn_spending.groupby(valid_keys)['payment_amount'].sum().reset_index(name='total_spending')
        else:
            monthly_spending = df.groupby(valid_keys)['payment_amount'].sum().reset_index(name='total_spending')

        monthly_reward = df.groupby(valid_keys)['calculated_reward'].sum().reset_index(name='total_reward')
        monthly_summary = pd.merge(monthly_spending, monthly_reward, on=valid_keys, how='outer').fillna(0)

        monthly_summary['effective_rate'] = np.where(
            monthly_summary['total_spending'] > 0,
            (monthly_summary['total_reward'] / monthly_summary['total_spending'] * 100).round(2),
            0.0
        )
        monthly_summary['total_spending'] = monthly_summary['total_spending'].round(2)
        monthly_summary['total_reward'] = monthly_summary['total_reward'].round(2)
        # 清除任何 NaN/inf，避免 JSON 序列化失敗
        monthly_summary = monthly_summary.replace([float('inf'), float('-inf')], 0.0)
        monthly_summary = monthly_summary.where(pd.notna(monthly_summary), other=0.0)

        # 2. rewards_pool_utilization 彙總
        pool_cols = ['month', 'bank_name', 'card_type', 'pool_id', 'pool_name']
        valid_pool_cols = [c for c in pool_cols if c in df.columns]

        def _get_first_cap(x):
            if isinstance(x, (pd.Series, list, tuple, np.ndarray)):
                for v in x:
                    if pd.notna(v):
                        val = pd.to_numeric(v, errors='coerce')
                        if pd.notna(val):
                            return val
                return None
            if pd.notna(x):
                val = pd.to_numeric(x, errors='coerce')
                return val if pd.notna(val) else None
            return None

        agg_dict: Dict[str, Any] = {
            'total_reward': ('calculated_reward', 'sum'),
            'is_capped': ('is_capped', lambda x: any(str(v).upper() == 'TRUE' for v in x))
        }
        if 'cap_amount' in df.columns:
            agg_dict['cap_amount'] = ('cap_amount', _get_first_cap)

        pool_util = df.groupby(valid_pool_cols).agg(**agg_dict).reset_index()
        pool_util['total_reward'] = pool_util['total_reward'].round(2)
        if 'cap_amount' in pool_util.columns:
            pool_util['cap_amount'] = pd.to_numeric(pool_util['cap_amount'], errors='coerce').fillna(0.0)
        # 清除任何 NaN/inf，避免 JSON 序列化失敗
        pool_util = pool_util.replace([float('inf'), float('-inf')], 0.0)
        pool_util = pool_util.where(pd.notna(pool_util), other=None)

        # 3. 寫入 Data Mart
        _save_to_data_mart({
            'rewards_monthly_summary': monthly_summary,
            'rewards_pool_utilization': pool_util
        }, db_path=db_path)
        logger.info(f"✅ [Data Mart] 成功同步回饋彙總數據至 {db_path}")
        return True
    except Exception as e:
        logger.error(f"❌ [Data Mart] 同步回饋數據失敗: {e}")
        return False


__all__ = ['run_analytics', 'sync_rewards_data_mart']
