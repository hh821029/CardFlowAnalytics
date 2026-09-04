# analytics/rfm/service.py
"""
RFM 儀表板與視覺化服務模組 (Dashboard Service)
負責整合 RFM 氣泡圖統計 (μ, σ, CV)、全類別中位數基準、波動度象限分類、領域 Top 3 排行與信用卡排序
"""
import os
import sqlite3
import logging
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any, Callable, Tuple

import const
from analytics.analytics_base import prepare_analytics_dataset

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """安全轉換純量為 float"""
    try:
        if pd.isna(val):
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    """安全轉換純量為 int"""
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _calc_ticket_medians(
    merchants: List[Dict[str, Any]],
    fallback_avg: float = 0.0,
    fallback_std: float = 0.0
) -> Tuple[float, float]:
    """計算商家串列中非零的客單價與標準差中位數 (避免重複計算與硬編碼用戶歷史數值)"""
    avg_vals = [m['avg_ticket'] for m in merchants if m.get('avg_ticket', 0.0) > 0]
    std_vals = [m['std_ticket'] for m in merchants if m.get('std_ticket', 0.0) > 0]

    med_avg = float(pd.Series(avg_vals).median()) if avg_vals else fallback_avg
    med_std = float(pd.Series(std_vals).median()) if std_vals else fallback_std

    if pd.isna(med_avg):
        med_avg = fallback_avg
    if pd.isna(med_std):
        med_std = fallback_std

    return med_avg, med_std


def _safe_to_numeric_series(
    data: Any,
    index: Optional[pd.Index] = None,
    fill_value: float = 0.0
) -> pd.Series:
    """安全轉換為數值型 pd.Series 並填補缺失值，解決型別檢查器誤判為 float 的問題"""
    converted = pd.to_numeric(data, errors='coerce')
    if isinstance(converted, pd.Series):
        return converted.fillna(fill_value)
    return pd.Series(converted, index=index).fillna(fill_value)


def compute_merchant_ticket_stats(df_tx: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """
    計算各商家的單筆交易明細統計 (平均客單價 μ, 樣本標準差 σ, 變異係數 CV, 筆數 count)
    以向量化運算取代迴圈，大幅提升效能並保證型別安全。
    """
    if df_tx.empty or 'payment_amount' not in df_tx.columns:
        return {}

    m_field = 'normalized_merchant' if 'normalized_merchant' in df_tx.columns else (
        'merchant_display' if 'merchant_display' in df_tx.columns else 'merchant'
    )
    if m_field not in df_tx.columns:
        return {}

    mask = df_tx[m_field].notna() & (df_tx[m_field] != '')
    df_clean = df_tx.loc[mask].copy()
    if df_clean.empty:
        return {}

    df_clean['payment_amount'] = _safe_to_numeric_series(df_clean['payment_amount'], df_clean.index, 0.0)

    # 向量化聚合計算均值、標準差與筆數
    grouped = df_clean.groupby(m_field)['payment_amount']
    cnt_series = grouped.count()
    mean_series = grouped.mean()
    std_series = grouped.std(ddof=1).fillna(0.0)

    # 計算 CV (變異係數 = σ / μ)
    cv_raw = (std_series / mean_series).replace([np.inf, -np.inf], 0.0)
    cv_series = _safe_to_numeric_series(cv_raw, std_series.index, 0.0).round(3)

    merchant_stats: Dict[str, Dict[str, float]] = {}
    for m_name in cnt_series.index:
        cnt = float(cnt_series.at[m_name])
        m_amt = float(mean_series.at[m_name]) if cnt > 0 else 0.0
        s_amt = float(std_series.at[m_name]) if cnt >= 2 else 0.0
        cv_amt = float(cv_series.at[m_name]) if m_amt > 0 else 0.0

        merchant_stats[str(m_name).strip()] = {
            'avg_ticket': round(m_amt, 2),
            'std_ticket': round(s_amt, 2),
            'cv': cv_amt,
            'count': cnt
        }

    return merchant_stats


def extract_top_merchants_by_category(
    df_merchants: pd.DataFrame,
    m_col: str,
    f_col: str,
    r_col: str,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """計算各生活消費領域 Top 3 商家排行 (依 M 累積金額降冪)"""
    top_by_category = []
    if 'category' not in df_merchants.columns or m_col not in df_merchants.columns:
        return top_by_category

    df_calc = df_merchants.copy()
    df_calc[m_col] = _safe_to_numeric_series(df_calc[m_col], df_calc.index, 0.0)

    cat_col = df_calc['category'].astype(str).str.strip()
    valid_mask = (
        df_calc['category'].notna() &
        (cat_col != '') &
        (cat_col != '未分類') &
        (cat_col != 'nan') &
        (df_calc[m_col] > 0)
    )
    if category and category != 'all':
        valid_mask = valid_mask & (df_calc['category'] == category)

    valid_cats = df_calc[valid_mask]
    if not isinstance(valid_cats, pd.DataFrame) or valid_cats.empty:
        return top_by_category

    # 完全向量化排序與前 3 名抽取，避免 groupby iteration 引發的型別推斷異常
    sorted_df = valid_cats.sort_values(by=['category', m_col], ascending=[True, False])
    top_3_df = sorted_df.groupby('category', as_index=False).head(3).copy()
    top_3_df['rank'] = top_3_df.groupby('category').cumcount() + 1

    for _, row in top_3_df.iterrows():
        sub_c = str(row.get('sub_category', '')).strip()
        if sub_c.lower() in ('nan', 'none'):
            sub_c = ''
        top_by_category.append({
            "category": str(row.get('category', '')),
            "rank": int(row.get('rank', 1)),
            "name": str(row.get('normalized_merchant', '')),
            "sub_category": sub_c,
            "monetary": _safe_float(row.get(m_col, 0.0)),
            "frequency": _safe_int(row.get(f_col, 0)),
            "recency": _safe_int(row.get(r_col, 9999), default=9999),
            "segment": str(row.get('segment', '一般活躍 (Active)'))
        })

    return top_by_category


def format_and_pin_cards(
    df_cards: pd.DataFrame,
    m_col: str,
    f_col: str,
    r_col: str
) -> List[Dict[str, Any]]:
    """整理信用卡資料並依 DEMO 模式進行釘選排序 (Cube, Uniopen, Unicard 置頂)"""
    cards_list = []
    if df_cards.empty:
        return cards_list

    for _, row in df_cards.iterrows():
        card_name = str(row.get('card_type', ''))
        cards_list.append({
            "bank_name": str(row.get('bank_name', '')),
            "card_type": card_name,
            "status": str(row.get('status', 'active')),
            "segment": str(row.get('segment', '')),
            "recency": _safe_int(row.get(r_col, row.get('life_recency_days', 9999)), default=9999),
            "frequency": _safe_int(row.get(f_col, row.get('life_frequency', 0)), default=0),
            "monetary": _safe_float(row.get(m_col, row.get('life_monetary', 0.0))),
            "avg_ticket": _safe_float(row.get('avg_ticket', 0.0))
        })

    def _card_sort_priority(item: Dict[str, Any]):
        cn = str(item.get('card_type', '')).lower()
        if 'cube' in cn:
            prio = 1
        elif 'uniopen' in cn:
            prio = 2
        elif 'unicard' in cn:
            prio = 3
        else:
            prio = 99
        return (prio, -float(item.get('monetary', 0.0)))

    cards_list.sort(key=_card_sort_priority)
    for item in cards_list:
        cn = str(item.get('card_type', '')).lower()
        item['is_demo_pinned'] = any(kw in cn for kw in ['cube', 'uniopen', 'unicard'])

    return cards_list


def get_rfm_dashboard_data(
    window: Optional[str] = "life",
    category: Optional[str] = None,
    limit: int = 200,
    df_tx_provider: Optional[Callable[[], pd.DataFrame]] = None
) -> Dict[str, Any]:
    """
    查詢 RFM 視覺化儀表板完整數據 (客單價 vs 標準差氣泡圖、客群分佈統計、四象限分類、Top 3 商家、信用卡置頂排序)
    """
    prefix = f"{window}_" if window and window != "life" else "life_"
    db_path = const.ANALYSIS_DB_PATH
    df_merchants = pd.DataFrame()
    df_cards = pd.DataFrame()

    # 1. 優先從 TransactionsAnalysis.db 讀取
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                df_merchants = pd.read_sql_query("SELECT * FROM rfm_merchants", conn)
                try:
                    df_cards = pd.read_sql_query("SELECT * FROM rfm_cards", conn)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"⚠️ 從 DB 讀取 RFM 失敗: {e}")

    # Fallback 讀取 CSV
    if df_merchants.empty:
        csv_path = os.path.join(const.OUTPUT_DIR, 'rfm', 'merchant_rfm.csv')
        if os.path.exists(csv_path):
            df_merchants = pd.read_csv(csv_path, encoding='utf-8')

    if df_cards.empty:
        card_csv_path = os.path.join(const.OUTPUT_DIR, 'rfm', 'card_rfm.csv')
        if os.path.exists(card_csv_path):
            df_cards = pd.read_csv(card_csv_path, encoding='utf-8')

    if df_merchants.empty:
        return {
            "merchants": [],
            "segment_counts": {},
            "categories": [],
            "top_by_category": [],
            "cards": [],
            "median_avg_ticket": 0.0,
            "median_std_ticket": 0.0,
            "current_median_avg_ticket": 0.0,
            "current_median_std_ticket": 0.0,
            "global_median_avg_ticket": 0.0,
            "global_median_std_ticket": 0.0
        }

    # 2. 提取所有有效分類清單 (在篩選前提取)
    all_categories = sorted([
        str(c) for c in df_merchants['category'].unique()
        if pd.notna(c) and str(c).strip() != '' and str(c).strip() != 'nan'
    ]) if 'category' in df_merchants.columns else []

    # 3. 保障 segment 欄位有效與命名一致 (優先沿用 rfm_merchants 既有計算結果)
    if 'segment' in df_merchants.columns and not df_merchants['segment'].isna().all():
        df_merchants['segment'] = df_merchants['segment'].fillna('一般活躍 (Active)').replace({
            '潛力新星 (Rising)': '潛力商家 (Rising)',
            '流失商家 (Churned)': '流失高價值 (Churned)',
        })
    elif '180d_frequency' in df_merchants.columns and 'life_m_rank' in df_merchants.columns:
        is_high_val = _safe_to_numeric_series(df_merchants['life_m_rank'], df_merchants.index, 0.0) >= 0.8
        is_act = _safe_to_numeric_series(df_merchants['180d_frequency'], df_merchants.index, 0.0) > 0
        if '180d_m_rank' in df_merchants.columns:
            rank_180d = _safe_to_numeric_series(df_merchants['180d_m_rank'], df_merchants.index, 0.0)
        else:
            rank_180d = pd.Series(0.0, index=df_merchants.index)
        df_merchants['segment'] = '一般活躍 (Active)'
        df_merchants.loc[~is_act, 'segment'] = '沉睡 (Dormant)'
        df_merchants.loc[is_act & (rank_180d >= 0.8) & (~is_high_val), 'segment'] = '潛力商家 (Rising)'
        df_merchants.loc[is_high_val & (~is_act), 'segment'] = '流失高價值 (Churned)'
        df_merchants.loc[is_high_val & is_act, 'segment'] = '核心商家 (Core)'
    else:
        df_merchants['segment'] = '一般活躍 (Active)'

    m_col = f"{prefix}monetary" if f"{prefix}monetary" in df_merchants.columns else "life_monetary"
    f_col = f"{prefix}frequency" if f"{prefix}frequency" in df_merchants.columns else "life_frequency"
    r_col = f"{prefix}recency_days" if f"{prefix}recency_days" in df_merchants.columns else "life_recency_days"

    # 4. 計算各商家的單筆交易明細統計 (平均客單價 μ, 樣本標準差 σ, 變異係數 CV)
    merchant_stats: Dict[str, Dict[str, float]] = {}
    try:
        df_tx = df_tx_provider() if df_tx_provider is not None else prepare_analytics_dataset(time_window=window)
        merchant_stats = compute_merchant_ticket_stats(df_tx)
    except Exception as stat_err:
        logger.warning(f"⚠️ 計算單筆標準差統計失敗: {stat_err}")

    # 5. 計算各生活消費領域 Top 3 商家排行
    top_by_category = extract_top_merchants_by_category(df_merchants, m_col, f_col, r_col, category)

    # 6. 構建全量有效商家清單，以計算不隨分類篩選變動之「全類別中位數 (Global Medians)」
    df_merchants_sorted = df_merchants.sort_values(by=m_col, ascending=False) if m_col in df_merchants.columns else df_merchants.copy()

    all_merchants_processed = []
    for _, row in df_merchants_sorted.iterrows():
        name_str = str(row.get('normalized_merchant', '')).strip()
        m_val = _safe_float(row.get(m_col, 0.0))
        f_val = _safe_int(row.get(f_col, 0))
        r_val = _safe_int(row.get(r_col, 9999), default=9999)

        stats = merchant_stats.get(name_str)
        if stats:
            avg_ticket = stats['avg_ticket']
            std_ticket = stats['std_ticket']
            cv_val = stats['cv']
        else:
            avg_ticket = round(m_val / f_val, 2) if f_val > 0 else 0.0
            std_ticket = 0.0
            cv_val = 0.0

        sub_c = str(row.get('sub_category', '')).strip()
        if sub_c.lower() in ('nan', 'none'):
            sub_c = ''

        all_merchants_processed.append({
            "name": name_str,
            "recency": r_val,
            "frequency": f_val,
            "monetary": m_val,
            "avg_ticket": avg_ticket,
            "std_ticket": std_ticket,
            "cv": cv_val,
            "segment": str(row.get('segment', '一般活躍 (Active)')),
            "category": str(row.get('category', '未分類')),
            "sub_category": sub_c
        })

    # 計算全類別（Global）固定的客單價與標準差中位數 (預設基準為 0.0，不硬編碼任何歷史數值)
    global_median_avg, global_median_std = _calc_ticket_medians(
        all_merchants_processed,
        fallback_avg=0.0,
        fallback_std=0.0
    )

    # 7. 類別篩選 (若有傳入特定 category，則篩選子集；若為 all 則取全量)
    if category and category != 'all':
        merchants_filtered = [m for m in all_merchants_processed if m['category'] == category]
        cur_median_avg, cur_median_std = _calc_ticket_medians(
            merchants_filtered,
            fallback_avg=global_median_avg,
            fallback_std=global_median_std
        )
        merchants_list = merchants_filtered[:limit]
        df_filtered = df_merchants[df_merchants['category'] == category] if 'category' in df_merchants.columns else df_merchants
    else:
        cur_median_avg = global_median_avg
        cur_median_std = global_median_std
        merchants_list = all_merchants_processed[:limit]
        df_filtered = df_merchants

    # 8. 標註波動度象限分群（依目前類別之中位數基準分割）
    for m in merchants_list:
        mu = m['avg_ticket']
        sigma = m['std_ticket']
        if mu >= cur_median_avg and sigma < cur_median_std:
            vol_seg = "固定大額型 (Fixed High-Value)"
        elif mu >= cur_median_avg and sigma >= cur_median_std:
            vol_seg = "大額偶發型 (Spike Big-Ticket)"
        elif mu < cur_median_avg and sigma < cur_median_std:
            vol_seg = "微額日常型 (Micro-Routine)"
        else:
            vol_seg = "長尾混合型 (Elastic Long-Tail)"
        m['volatility_segment'] = vol_seg

    # 9. 客群分佈統計 (基於篩選後的商家資料)
    segment_counts = df_filtered['segment'].value_counts().to_dict() if 'segment' in df_filtered.columns else {}

    # 10. 卡片資料與 DEMO 模式釘選排序 (Cube, Uniopen, Unicard 置頂)
    cards_list = format_and_pin_cards(df_cards, m_col, f_col, r_col)

    return {
        "merchants": merchants_list,
        "segment_counts": segment_counts,
        "categories": all_categories,
        "top_by_category": top_by_category,
        "cards": cards_list,
        "median_avg_ticket": round(cur_median_avg, 2),
        "median_std_ticket": round(cur_median_std, 2),
        "current_median_avg_ticket": round(cur_median_avg, 2),
        "current_median_std_ticket": round(cur_median_std, 2),
        "global_median_avg_ticket": round(global_median_avg, 2),
        "global_median_std_ticket": round(global_median_std, 2)
    }


def get_dimension_volatility_bubble_data(
    window: Optional[str] = "life",
    group_mode: str = "payment_category",
    payment: Optional[str] = None,
    category: Optional[str] = None,
    card: Optional[str] = None,
    limit: int = 200,
    df_tx_provider: Optional[Callable[[], pd.DataFrame]] = None
) -> Dict[str, Any]:
    """
    Sankey 6 大流向維度消費波動通用聚合引擎：
    支援 6 種聚合分組模式：
    1. payment_category: 行動支付 ✕ 消費類別 (預設)
    2. card_category: 信用卡 ✕ 消費類別
    3. card_payment: 信用卡 ✕ 行動支付
    4. payment_only: 純依行動支付
    5. category_only: 純依消費類別
    6. card_only: 純依信用卡
    
    回傳各組之客單均值 (μ), 單筆標準差 (σ), 變異係數 (CV), 累積金額 (M), 筆數 (F), 中位數十字劃分與四象限型態。
    """
    try:
        df_tx = df_tx_provider() if df_tx_provider is not None else prepare_analytics_dataset(time_window=window)
    except Exception as e:
        logger.error(f"❌ [dimension_volatility] 提取交易數據失敗: {e}")
        df_tx = pd.DataFrame()

    empty_res = {
        "group_mode": group_mode,
        "groups": [],
        "total_groups": 0,
        "payments": [],
        "categories": [],
        "cards": [],
        "median_avg_ticket": 0.0,
        "median_std_ticket": 0.0,
        "current_median_avg_ticket": 0.0,
        "current_median_std_ticket": 0.0,
        "global_median_avg_ticket": 0.0,
        "global_median_std_ticket": 0.0,
        "volatility_counts": {"固定大額": 0, "大額偶發": 0, "微額日常": 0, "長尾混合": 0}
    }

    if df_tx is None or df_tx.empty or 'payment_amount' not in df_tx.columns:
        return empty_res

    df_clean = df_tx.copy()
    df_clean['payment_amount'] = _safe_to_numeric_series(df_clean['payment_amount'], df_clean.index, 0.0)
    df_clean = df_clean[df_clean['payment_amount'] > 0]

    if df_clean.empty:
        return empty_res

    # 欄位標準化補齊
    p_col = 'payment_process' if 'payment_process' in df_clean.columns else 'mobile_payment'
    if p_col not in df_clean.columns:
        df_clean[p_col] = '實體卡/其他'
    else:
        df_clean[p_col] = df_clean[p_col].fillna('實體卡/其他').astype(str).str.strip().replace({'': '實體卡/其他', 'nan': '實體卡/其他', 'None': '實體卡/其他'})

    if 'category' not in df_clean.columns:
        df_clean['category'] = '未分類'
    else:
        df_clean['category'] = df_clean['category'].fillna('未分類').astype(str).str.strip().replace({'': '未分類', 'nan': '未分類', 'None': '未分類'})

    c_col = 'card_type' if 'card_type' in df_clean.columns else 'card_name'
    if c_col not in df_clean.columns:
        df_clean[c_col] = '其他卡別'
    else:
        df_clean[c_col] = df_clean[c_col].fillna('其他卡別').astype(str).str.strip().replace({'': '其他卡別', 'nan': '其他卡別', 'None': '其他卡別'})

    # 提取全量維度清單以供前端下拉選單使用
    all_payments = sorted([p for p in df_clean[p_col].unique() if p and p != 'nan'])
    all_categories = sorted([c for c in df_clean['category'].unique() if c and c not in ('nan', '未分類')])
    all_cards = sorted([c for c in df_clean[c_col].unique() if c and c not in ('nan', '其他卡別')])

    # 決定聚合分組鍵值
    valid_modes = ['payment_category', 'card_category', 'card_payment', 'payment_only', 'category_only', 'card_only']
    if group_mode not in valid_modes:
        group_mode = 'payment_category'

    if group_mode == 'payment_category':
        group_cols = [p_col, 'category']
    elif group_mode == 'card_category':
        group_cols = [c_col, 'category']
    elif group_mode == 'card_payment':
        group_cols = [c_col, p_col]
    elif group_mode == 'payment_only':
        group_cols = [p_col]
    elif group_mode == 'category_only':
        group_cols = ['category']
    else:  # card_only
        group_cols = [c_col]

    # 向量化分組計算均值、標準差、金額加總與筆數
    grouped = df_clean.groupby(group_cols)['payment_amount']
    cnt_series = grouped.count()
    sum_series = grouped.sum()
    mean_series = grouped.mean()
    std_series = grouped.std(ddof=1).fillna(0.0)
    cv_raw = (std_series / mean_series).replace([np.inf, -np.inf], 0.0)
    cv_series = _safe_to_numeric_series(cv_raw, std_series.index, 0.0).round(3)

    all_groups = []
    for idx in cnt_series.index:
        cnt = int(cnt_series.at[idx])
        s_amt = round(float(sum_series.at[idx]), 2)
        m_amt = round(float(mean_series.at[idx]), 2) if cnt > 0 else 0.0
        sd_amt = round(float(std_series.at[idx]), 2) if cnt >= 2 else 0.0
        cv_amt = float(cv_series.at[idx]) if m_amt > 0 else 0.0

        p_val, cat_val, card_val = None, None, None
        if len(group_cols) == 2:
            val1, val2 = idx[0], idx[1]
            disp_name = f"{val1} ✕ {val2}"
            if group_mode == 'payment_category':
                p_val, cat_val = str(val1), str(val2)
            elif group_mode == 'card_category':
                card_val, cat_val = str(val1), str(val2)
            elif group_mode == 'card_payment':
                card_val, p_val = str(val1), str(val2)
        else:
            val1 = idx
            disp_name = str(val1)
            if group_mode == 'payment_only':
                p_val = str(val1)
            elif group_mode == 'category_only':
                cat_val = str(val1)
            else:
                card_val = str(val1)

        all_groups.append({
            "name": disp_name,
            "payment_process": p_val,
            "category": cat_val,
            "card_type": card_val,
            "avg_ticket": m_amt,
            "std_ticket": sd_amt,
            "cv": cv_amt,
            "monetary": s_amt,
            "frequency": cnt
        })

    if not all_groups:
        return empty_res

    # 計算全域固定的客單價與標準差中位數
    global_med_avg = float(pd.Series([g['avg_ticket'] for g in all_groups]).median())
    global_med_std = float(pd.Series([g['std_ticket'] for g in all_groups]).median())

    # 依使用者傳入的條件篩選
    filtered_groups = all_groups
    if payment and payment != 'all':
        filtered_groups = [g for g in filtered_groups if g['payment_process'] == payment]
    if category and category != 'all':
        filtered_groups = [g for g in filtered_groups if g['category'] == category]
    if card and card != 'all':
        filtered_groups = [g for g in filtered_groups if g['card_type'] == card]

    # 計算當前篩選下的中位數
    if filtered_groups:
        cur_med_avg = float(pd.Series([g['avg_ticket'] for g in filtered_groups]).median())
        cur_med_std = float(pd.Series([g['std_ticket'] for g in filtered_groups]).median())
    else:
        cur_med_avg = global_med_avg
        cur_med_std = global_med_std

    # 標註四象限波動型態與統計計數
    vol_counts = {"固定大額": 0, "大額偶發": 0, "微額日常": 0, "長尾混合": 0}
    for g in filtered_groups:
        mu = g['avg_ticket']
        sigma = g['std_ticket']
        if mu >= cur_med_avg and sigma < cur_med_std:
            v_seg = "固定大額型 (Fixed High-Value)"
            vol_counts["固定大額"] += 1
        elif mu >= cur_med_avg and sigma >= cur_med_std:
            v_seg = "大額偶發型 (Spike Big-Ticket)"
            vol_counts["大額偶發"] += 1
        elif mu < cur_med_avg and sigma < cur_med_std:
            v_seg = "微額日常型 (Micro-Routine)"
            vol_counts["微額日常"] += 1
        else:
            v_seg = "長尾混合型 (Elastic Long-Tail)"
            vol_counts["長尾混合"] += 1
        g['volatility_segment'] = v_seg

    # 依金額排序
    filtered_groups = sorted(filtered_groups, key=lambda x: x['monetary'], reverse=True)

    return {
        "group_mode": group_mode,
        "groups": filtered_groups[:limit],
        "total_groups": len(filtered_groups),
        "payments": all_payments,
        "categories": all_categories,
        "cards": all_cards,
        "median_avg_ticket": round(cur_med_avg, 2),
        "median_std_ticket": round(cur_med_std, 2),
        "current_median_avg_ticket": round(cur_med_avg, 2),
        "current_median_std_ticket": round(cur_med_std, 2),
        "global_median_avg_ticket": round(global_med_avg, 2),
        "global_median_std_ticket": round(global_med_std, 2),
        "volatility_counts": vol_counts
    }

