# analytics/matrix/modules.py
"""
消費交叉透視矩陣模型 (Spending Matrix Module)
支援三大維度 (商家/類別、付款管道、信用卡) 取二交叉透視、金額彙整、佔比運算與多時間視窗報表輸出
"""
import os
import re
import logging
import pandas as pd
from datetime import timedelta
from typing import List, Dict, Tuple, Any, Optional, cast

import const
from analytics import MATRIX_OUTPUT_DIR
from analytics.common import get_clean_df

from profiles.loaders.config_loader import ConfigLoader

logger = logging.getLogger(__name__)

# 排除不列入消費矩陣的類別
EXCLUDE_CATEGORIES = ['銀行費用', '未分類']

def _load_payment_tiers() -> Tuple[List[str], List[str]]:
    """
    從 dim_payment_process.csv 載入支付分層：
    - Tier 1: Priority 1 ~ 7 (主要通用支付：強制顯示獨立欄位，即使全為0亦保留)
    - Tier 2: Priority 8 ~ 16 (通路錢包：獨立欄位，但若該欄位全為0則不顯示)
    - Priority 17+ 歸類為 '其他'
    """
    tier1_names: List[str] = []
    tier2_names: List[str] = []
    
    try:
        df_pay = ConfigLoader.load_config(base_name='dim_payment_process')
        if not df_pay.empty and 'priority' in df_pay.columns:
            df_pay['priority'] = pd.to_numeric(df_pay['priority'], errors='coerce')
            name_col = 'payment_process'
            
            # 1. Tier 1 (1 <= priority <= 7)
            t1_mask = (df_pay['priority'] >= 1) & (df_pay['priority'] <= 7)
            df_t1 = cast(pd.DataFrame, df_pay[t1_mask]).sort_values(by='priority')
            for val in df_t1[name_col].dropna().unique():
                s = str(val).strip()
                if re.search(r'(?i)line.*pay', s):
                    s = 'Linepay'
                if s not in tier1_names:
                    tier1_names.append(s)
                    
            # 2. Tier 2 (8 <= priority <= 16)
            t2_mask = (df_pay['priority'] >= 8) & (df_pay['priority'] <= 16)
            df_t2 = cast(pd.DataFrame, df_pay[t2_mask]).sort_values(by='priority')
            for val in df_t2[name_col].dropna().unique():
                s = str(val).strip()
                if s not in tier2_names:
                    tier2_names.append(s)
                    
            if tier1_names or tier2_names:
                return tier1_names, tier2_names
    except Exception as e:
        logger.warning(f"⚠️ 透過 ConfigLoader 載入 dim_payment_process 分層失敗: {e}")

    # Fallback 預設清單 (以 payment_process 為準)
    default_t1 = ['Linepay', '街口支付', '悠遊付', 'icash Pay', '一卡通', '全盈+PAY', '全支付']
    default_t2 = ['橘子支付', '台灣pay', '玉山Wallet', 'OPEN錢包', 'Famipay', 'PXPay']
    return default_t1, default_t2

def _standardize_payment_tier_name(pay_val: Any, tier1_names: List[str], tier2_names: List[str]) -> str:
    """
    將交易紀錄中的支付方式標準化至 Tier 1、Tier 2 或 '其他' (Priority >= 17)
    """
    if pd.isna(pay_val) or not str(pay_val).strip():
        return '實體卡/虛擬卡'
        
    s = str(pay_val).strip()
    if s in ['實體卡/其他', '實體卡', '虛擬卡', '實體卡/虛擬卡']:
        return '實體卡/虛擬卡'
        
    if re.search(r'(?i)line.*pay|連加', s):
        return 'Linepay'
        
    # 比對 Tier 1 (Priority 1 ~ 7)
    for t1 in tier1_names:
        if s.lower() == t1.lower() or t1.lower() in s.lower():
            return t1
            
    # 比對 Tier 2 (Priority 8 ~ 16)
    for t2 in tier2_names:
        if s.lower() == t2.lower() or t2.lower() in s.lower():
            return t2
            
    # 其餘 (Priority >= 17 或其他未知管道) 歸入 '其他'
    return '其他'

def _get_fixed_category_order(df_clean: pd.DataFrame) -> List[str]:
    """
    依據 dim_categories.yaml 的 category 順序固定輸出 (排除 '銀行費用' 與 '未分類')
    """
    ordered_cats: List[str] = []
    
    # 1. 優先透過 ConfigLoader 讀取 dim_categories.yaml
    try:
        data = ConfigLoader.load_yaml(base_name='dim_categories')
        if isinstance(data, dict) and 'category' in data and isinstance(data['category'], list):
            for c in data['category']:
                c_str = str(c).strip()
                if c_str and c_str not in EXCLUDE_CATEGORIES and c_str not in ordered_cats:
                    ordered_cats.append(c_str)
    except Exception as e:
        logger.warning(f"⚠️ 讀取 dim_categories.yaml 排序失敗: {e}")

    # 2. 保底 fallback 清單
    if not ordered_cats:
        ordered_cats = ['百貨量販', '便利商店', '連鎖飲食', '商圈', '生活服務', '電子商務', '保險費用']

    # 3. 檢查資料中是否有未在 YAML 列出的其他合法類別，追加進來（保持保險費用在最後）
    if 'category' in df_clean.columns and not df_clean.empty:
        actual_cats = df_clean['category'].dropna().unique()
        insurance_cats = [c for c in ordered_cats if '保險' in c]
        non_insurance_ordered = [c for c in ordered_cats if '保險' not in c]
        
        for c in actual_cats:
            c_str = str(c).strip()
            if c_str and c_str not in EXCLUDE_CATEGORIES and c_str not in ordered_cats:
                if '保險' in c_str:
                    insurance_cats.append(c_str)
                else:
                    non_insurance_ordered.append(c_str)
        return non_insurance_ordered + insurance_cats

    return ordered_cats

def create_pivot_matrix(
    df: pd.DataFrame, 
    index_col: str = 'category', 
    column_col: str = 'payment_process', 
    value_col: str = 'payment_amount',
    fixed_index_order: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    消費類別 × 支付管道交叉樞紐矩陣生成與百分比佔比計算
    三層欄位規則：
    1. 實體卡/虛擬卡 + Tier 1 (Priority 1 ~ 7 主流通用支付)：強制顯示獨立欄位 (有0亦顯示)
    2. Tier 2 (Priority 8 ~ 16 通路錢包)：獨立欄位，但全為0時不顯示
    3. Tier 3 (Priority 17+ 及其他)：合併為「其他」欄位
    """
    if df.empty or index_col not in df.columns or column_col not in df.columns:
        return pd.DataFrame()
        
    tier1_names, tier2_names = _load_payment_tiers()
    
    # 複製並標準化支付方式
    df_pivot = df.copy()
    df_pivot[column_col] = df_pivot[column_col].apply(lambda x: _standardize_payment_tier_name(x, tier1_names, tier2_names))
    
    matrix = df_pivot.pivot_table(
        values=value_col, 
        index=index_col, 
        columns=column_col, 
        aggfunc='sum', 
        fill_value=0
    )
    
    if matrix.empty:
        return pd.DataFrame()
        
    # 計算各類別總金額 (Total_Amount)
    row_sum = matrix.sum(axis=1)
    
    # 轉換為橫向佔比百分比 (Percentage Share)
    matrix_pct = (matrix.div(row_sum, axis=0) * 100).fillna(0)
    
    # 對齊縱軸 (Category Index) 順序
    if fixed_index_order:
        matrix_pct = matrix_pct.reindex(index=fixed_index_order, fill_value=0)
        total_series = row_sum.reindex(index=fixed_index_order, fill_value=0)
    else:
        total_series = row_sum.sort_values(ascending=False)
        matrix_pct = matrix_pct.reindex(total_series.index)
    
    # ==========================================
    # 三層自訂欄位順序組織
    # ==========================================
    ordered_cols: List[str] = ['實體卡/虛擬卡']
    
    # 第 1 部分 (Priority 1 ~ 7)：主要通用支付，強制顯示 (補 0)
    for t1 in tier1_names:
        if t1 not in ordered_cols:
            ordered_cols.append(t1)
            
    # 第 2 部分 (Priority 8 ~ 16)：通路錢包，僅在該視窗有消費 (sum > 0) 時顯示
    for t2 in tier2_names:
        if t2 in matrix.columns and matrix[t2].sum() > 0:
            if t2 not in ordered_cols:
                ordered_cols.append(t2)
                
    # 第 3 部分 (Priority 17+ 及其他)：合併為「其他」，若有消費則顯示
    if '其他' in matrix.columns and matrix['其他'].sum() > 0:
        ordered_cols.append('其他')
    elif '其他' in matrix_pct.columns and matrix_pct['其他'].sum() > 0:
        ordered_cols.append('其他')
        
    matrix_pct = matrix_pct.reindex(columns=ordered_cols, fill_value=0)
    matrix_pct.insert(0, 'Total_Amount', total_series)
    
    return matrix_pct

def generate_spending_matrix(
    df_raw: pd.DataFrame, 
    time_windows: Optional[List[Dict[str, Any]]] = None,
    output_dir: str = MATRIX_OUTPUT_DIR
) -> List[Tuple[str, pd.DataFrame]]:
    """
    產生消費類別 × 支付管道之多時間視窗消費矩陣報表
    1. 排除 '銀行費用' 與 '未分類'
    2. 統一以全期 (Lifetime) 類別排序輸出，並固定將 '保險費用' 置於最後一列
    """
    if time_windows is None or df_raw is None or df_raw.empty:
        return []
    
    df_clean = get_clean_df(df_raw)
    if df_clean.empty:
        return []
        
    # 1. 排除掉 '銀行費用' 與 '未分類'
    if 'category' in df_clean.columns:
        df_clean = cast(pd.DataFrame, df_clean[~df_clean['category'].isin(EXCLUDE_CATEGORIES)].copy())
        
    if df_clean.empty:
        return []
        
    # 2. 預先取得全歷史固定類別順序 (保險置底)
    fixed_categories = _get_fixed_category_order(df_clean)
    pay_col = 'payment_process' if 'payment_process' in df_clean.columns else 'mobile_payment'
    
    latest_date = df_clean['transaction_date'].max()
    results = []
    
    for window in time_windows:
        days = window.get('days')
        suffix = window.get('suffix', 'custom') 
        
        if days:
            cutoff = latest_date - timedelta(days=days)
            df_subset = cast(pd.DataFrame, df_clean[df_clean['transaction_date'] >= cutoff].copy())
        else:
            df_subset = df_clean
            
        if df_subset.empty:
            continue
            
        matrix_pct = create_pivot_matrix(
            df_subset, 
            index_col='category', 
            column_col=pay_col, 
            fixed_index_order=fixed_categories
        )
        if matrix_pct.empty:
            continue
            
        filename = f"spending_matrix_{suffix}.csv"
        results.append((filename, matrix_pct))
        
    return results

def save_spending_matrix_reports(
    matrix_results: List[Tuple[str, pd.DataFrame]], 
    output_dir: str = MATRIX_OUTPUT_DIR
) -> None:
    """
    將產出之矩陣結果寫入 CSV 檔案 (以 category 作為第一欄欄位名稱)
    """
    os.makedirs(output_dir, exist_ok=True)
    for filename, df_matrix in matrix_results:
        csv_path = os.path.join(output_dir, filename)
        df_matrix.round(2).to_csv(csv_path, index=True, index_label='category', encoding='utf-8-sig')
        logger.info(f"   ✅ [Matrix CSV] 報表已儲存: {csv_path}")
