# rfm_analysis/rfm_modules.py
import pandas as pd
from datetime import timedelta
import numpy as np
from typing import cast

from rfm_analysis import rfm_utils

# 定義不列入 RFM 計算的交易類型 (防護網)
EXCLUDE_TYPES = ['繳款', '各項費用', '退刷', '紅利折抵']

def _get_clean_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    """過濾掉非消費類型的紀錄"""
    mask = ~df_raw['transaction_type'].isin(EXCLUDE_TYPES)
    return cast(pd.DataFrame, df_raw[mask].copy())

def _calculate_multi_window_rfm(df_clean, group_cols, time_windows):
    """內部通用邏輯：多視窗迴圈計算 (Wide Table Loop)"""
    if df_clean.empty or not time_windows: 
        return pd.DataFrame()
    
    analysis_date = df_clean['transaction_date'].max() + timedelta(days=1)
    final_df = None
    
    for window in time_windows:
        days = window['days']
        prefix = window['prefix']
        
        if days:
            cutoff = analysis_date - timedelta(days=days)
            df_subset = df_clean[df_clean['transaction_date'] >= cutoff]
        else:
            df_subset = df_clean
            
        rfm_part = rfm_utils.calculate_rfm_base(df_subset, analysis_date, group_cols, prefix)
        rfm_part = rfm_utils.add_rfm_ranks(rfm_part, prefix)
        
        if final_df is None:
            final_df = rfm_part
        else:
            cols_to_drop = [col for col in rfm_part.columns if col in ['category']]
            rfm_part_clean = rfm_part.drop(columns=cols_to_drop)
            final_df = final_df.join(rfm_part_clean, how='outer')
            
    if final_df is None:
        return pd.DataFrame()

    # 根據不同欄位屬性進行精確的空值填充，避免型態警告與資料污染
    fill_values = {}
    for col in final_df.columns:
        if col == 'category':
            fill_values[col] = '未分類'
        elif 'recency_days' in col:
            fill_values[col] = 9999
        else:
            fill_values[col] = 0
            
    final_df = final_df.fillna(value=fill_values)
                
    return final_df

def calculate_merchant_rfm(df_raw, windows_config):
    df_clean = _get_clean_df(df_raw)
    final_df = _calculate_multi_window_rfm(df_clean, 'merchant_display', windows_config)
    
    short_prefix = windows_config[-1]['prefix']
    
    def _label_segment(row):
        if 'life_m_rank' not in row or f'{short_prefix}frequency' not in row: return "資料不足"
        is_high_value = row['life_m_rank'] >= 0.8
        is_active = row[f'{short_prefix}frequency'] > 0
        
        if is_high_value and is_active: return "核心商家 (Core)"
        elif is_high_value and not is_active: return "流失高價值 (Churned)"
        elif not is_high_value and is_active and row.get(f'{short_prefix}m_rank', 0) >= 0.8: return "潛力新星 (Rising)"
        elif is_active: return "一般活躍 (Active)"
        else: return "沉睡 (Dormant)"

    if not final_df.empty:
        final_df['segment'] = final_df.apply(_label_segment, axis=1)
        return final_df.reset_index()
    return pd.DataFrame()

def calculate_payment_rfm(df_raw, windows_config):
    df_clean = _get_clean_df(df_raw)
    
    # 支付管道欄位相容處理，統一補位
    pay_col = 'payment_process' if 'payment_process' in df_clean.columns else 'mobile_payment'
    df_clean[pay_col] = df_clean[pay_col].fillna('實體卡/其他')
    
    final_df = _calculate_multi_window_rfm(df_clean, pay_col, windows_config)
    
    if 'category' in final_df.columns:
        final_df = final_df.drop(columns=['category'])
        
    def _label_segment(row):
        short_freq = row.get(f"{windows_config[-1]['prefix']}frequency", 0)
        life_f_rank = row.get('life_f_rank', 0)
        
        is_high_freq = life_f_rank >= 0.7
        is_active = short_freq > 0
        
        if is_high_freq and is_active: return "主力支付 (Main)"
        elif is_high_freq and not is_active: return "已棄用 (Abandoned)"
        elif not is_high_freq and is_active: return "輔助支付 (Backup)"
        else: return "冷門支付 (Rare)"

    if not final_df.empty:
        final_df['segment'] = final_df.apply(_label_segment, axis=1)
        return final_df.reset_index()
    return pd.DataFrame()

def calculate_card_rfm(df_raw, windows_config):
    df_clean = _get_clean_df(df_raw)
    df_clean = df_clean[df_clean['card_type'].notna() & (df_clean['card_type'] != '')]
    
    final_df = _calculate_multi_window_rfm(df_clean, ['bank_name', 'card_type'], windows_config)
    
    if 'category' in final_df.columns:
        final_df = final_df.drop(columns=['category'])
        
    short_prefix = windows_config[-1]['prefix']
    if not final_df.empty:
        if f'{short_prefix}frequency' in final_df.columns:
            final_df['avg_ticket'] = (
                final_df[f'{short_prefix}monetary'] / final_df[f'{short_prefix}frequency']
                ).replace([np.inf, -np.inf], 0).fillna(0).astype(int)

        def _label_segment(row):
            recency = row.get(f'{short_prefix}recency_days', 9999)
            if recency > 180: return "❄️ 冷凍/沉睡"
            f_rank = row.get(f'{short_prefix}f_rank', 0)
            m_rank = row.get(f'{short_prefix}m_rank', 0)
            
            if f_rank >= 0.5 and m_rank >= 0.5: return "👑 主力攻擊手"
            elif f_rank < 0.5 and m_rank >= 0.5: return "🎯 狙擊手" 
            elif f_rank >= 0.5 and m_rank < 0.5: return "🔄 後勤補給" 
            else: return "📉 低效冗餘"
            
        final_df['segment'] = final_df.apply(_label_segment, axis=1)
        return final_df.reset_index()
    return pd.DataFrame()

def generate_spending_matrix(df_raw, time_windows=None):
    if time_windows is None: return []
    
    df_clean = _get_clean_df(df_raw)
    pay_col = 'payment_process' if 'payment_process' in df_clean.columns else 'mobile_payment'
    df_clean[pay_col] = df_clean[pay_col].fillna('實體卡/其他')
    
    latest_date = df_clean['transaction_date'].max()
    results = []
    
    for window in time_windows:
        days = window['days']
        suffix = window.get('suffix', 'custom') 
        
        df_subset = df_clean[df_clean['transaction_date'] >= (latest_date - timedelta(days=days))] if days else df_clean
        if df_subset.empty: continue
        df_subset_df = cast(pd.DataFrame, df_subset)
        matrix = df_subset_df.pivot_table(
            values='payment_amount', 
            index='category', 
            columns=pay_col, 
            aggfunc='sum', 
            fill_value=0
        )
        
        matrix_pct = (matrix.div(matrix.sum(axis=1), axis=0) * 100).fillna(0)
        total_series = matrix.sum(axis=1).sort_values(ascending=False)
        matrix_pct = matrix_pct.reindex(total_series.index)
        matrix_pct.insert(0, 'Total_Amount', total_series)
        
        filename = f"spending_matrix_{suffix}.csv"
        results.append((filename, matrix_pct))
        
    return results
