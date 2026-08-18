# analytics/rfm/modules.py
"""
RFM 價值分群模型核心模組
支援三大維度 (商家、付款管道、信用卡) 與雙維度交叉之多時間視窗 RFM 計算與 Segment 分群
"""
import pandas as pd
import numpy as np
from datetime import timedelta
from typing import List, Dict, Any, Union, Optional, cast

from analytics.common import get_clean_df, add_rfm_ranks

def calculate_rfm_base(
    df_subset: pd.DataFrame, 
    analysis_date: pd.Timestamp, 
    group_cols: Union[str, List[str]], 
    prefix: str = ''
) -> pd.DataFrame:
    """
    基礎 RFM 指標計算核心 (不含 Rank)
    - Recency: 距離基準日天數
    - Frequency: 交易次數 (transaction_id nunique)
    - Monetary: 交易總金額 (payment_amount sum)
    """
    if df_subset.empty:
        return pd.DataFrame()

    agg_rules = {
        'transaction_date': lambda x: (analysis_date - x.max()).days,
        'transaction_id': 'nunique',
        'payment_amount': 'sum'
    }
    
    group_list = [group_cols] if isinstance(group_cols, str) else list(group_cols)
    if 'category' in df_subset.columns and 'category' not in group_list:
        agg_rules['category'] = 'first'
    if 'sub_category' in df_subset.columns and 'sub_category' not in group_list:
        agg_rules['sub_category'] = 'first'
        
    rfm = df_subset.groupby(group_cols).agg(agg_rules).rename(columns={
        'transaction_date': f'{prefix}recency_days',
        'transaction_id': f'{prefix}frequency',
        'payment_amount': f'{prefix}monetary'
    })
    
    return rfm

def calculate_multi_window_rfm(
    df_clean: pd.DataFrame, 
    group_cols: Union[str, List[str]], 
    time_windows: List[Dict[str, Any]]
) -> pd.DataFrame:
    """
    多時間視窗迴圈計算 (Wide Table Loop)
    """
    if df_clean.empty or not time_windows: 
        return pd.DataFrame()
    
    analysis_date = df_clean['transaction_date'].max() + timedelta(days=1)
    final_df = None
    
    for window in time_windows:
        days = window.get('days')
        prefix = window.get('prefix', '')
        
        if days:
            cutoff = analysis_date - timedelta(days=days)
            df_subset = cast(pd.DataFrame, df_clean[df_clean['transaction_date'] >= cutoff].copy())
        else:
            df_subset = df_clean
            
        rfm_part = calculate_rfm_base(df_subset, analysis_date, group_cols, prefix)
        rfm_part = add_rfm_ranks(rfm_part, prefix)
        
        if final_df is None:
            final_df = rfm_part
        else:
            cols_to_drop = [col for col in rfm_part.columns if col in ['category', 'sub_category']]
            rfm_part_clean = rfm_part.drop(columns=cols_to_drop)
            final_df = final_df.join(rfm_part_clean, how='outer')
            
    if final_df is None:
        return pd.DataFrame()

    # 根據欄位屬性填補空值
    fill_values = {}
    for col in final_df.columns:
        if col == 'category':
            fill_values[col] = '未分類'
        elif col == 'sub_category':
            fill_values[col] = ''
        elif 'recency_days' in col:
            fill_values[col] = 9999
        else:
            fill_values[col] = 0
            
    final_df = final_df.fillna(value=fill_values)
    return final_df

def calculate_merchant_rfm(df_raw: pd.DataFrame, windows_config: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    商家維度 RFM 分群計算 (以 normalized_merchant 聚合)
    """
    df_clean = get_clean_df(df_raw)
    if 'normalized_merchant' not in df_clean.columns or df_clean['normalized_merchant'].dropna().empty:
        df_clean['normalized_merchant'] = df_clean.get('merchant_display', df_clean.get('merchant', ''))
    else:
        df_clean['normalized_merchant'] = df_clean['normalized_merchant'].fillna(df_clean.get('merchant_display', ''))
        
    final_df = calculate_multi_window_rfm(df_clean, 'normalized_merchant', windows_config)
    
    if final_df.empty:
        return pd.DataFrame()
        
    short_prefix = windows_config[-1]['prefix']
    
    def _label_segment(row):
        if 'life_m_rank' not in row or f'{short_prefix}frequency' not in row:
            return "資料不足"
        is_high_value = row.get('life_m_rank', 0) >= 0.8
        is_active = row.get(f'{short_prefix}frequency', 0) > 0
        
        if is_high_value and is_active:
            return "核心商家 (Core)"
        elif is_high_value and not is_active:
            return "流失高價值 (Churned)"
        elif not is_high_value and is_active and row.get(f'{short_prefix}m_rank', 0) >= 0.8:
            return "潛力新星 (Rising)"
        elif is_active:
            return "一般活躍 (Active)"
        else:
            return "沉睡 (Dormant)"

    final_df['segment'] = final_df.apply(_label_segment, axis=1)
    return final_df.reset_index()

def calculate_category_rfm(df_raw: pd.DataFrame, windows_config: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    消費類別維度 RFM 分群計算 (以 category 聚合)
    """
    df_clean = get_clean_df(df_raw)
    if 'category' not in df_clean.columns or df_clean['category'].dropna().empty:
        df_clean['category'] = '未分類'
    else:
        df_clean['category'] = df_clean['category'].fillna('未分類')
        
    final_df = calculate_multi_window_rfm(df_clean, 'category', windows_config)
    
    if final_df.empty:
        return pd.DataFrame()
        
    for drop_c in ['category', 'sub_category']:
        if drop_c in final_df.columns:
            final_df = final_df.drop(columns=[drop_c])
        
    short_prefix = windows_config[-1]['prefix']
    
    def _label_segment(row):
        if 'life_m_rank' not in row or f'{short_prefix}frequency' not in row:
            return "資料不足"
        is_high_value = row.get('life_m_rank', 0) >= 0.8
        is_active = row.get(f'{short_prefix}frequency', 0) > 0
        
        if is_high_value and is_active:
            return "核心類別 (Core)"
        elif is_high_value and not is_active:
            return "流失高價值類別 (Churned)"
        elif not is_high_value and is_active and row.get(f'{short_prefix}m_rank', 0) >= 0.8:
            return "潛力新興類別 (Rising)"
        elif is_active:
            return "一般活躍類別 (Active)"
        else:
            return "沉睡類別 (Dormant)"

    final_df['segment'] = final_df.apply(_label_segment, axis=1)
    return final_df.reset_index()

def calculate_payment_rfm(df_raw: pd.DataFrame, windows_config: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    付款管道維度 RFM 分群計算 (以 payment_process 聚合)
    """
    df_clean = get_clean_df(df_raw)
    pay_col = 'payment_process' if 'payment_process' in df_clean.columns else 'mobile_payment'
    df_clean[pay_col] = df_clean[pay_col].fillna('實體卡/其他')
    
    final_df = calculate_multi_window_rfm(df_clean, pay_col, windows_config)
    
    if final_df.empty:
        return pd.DataFrame()
        
    for drop_c in ['category', 'sub_category']:
        if drop_c in final_df.columns:
            final_df = final_df.drop(columns=[drop_c])
        
    def _label_segment(row):
        short_freq = row.get(f"{windows_config[-1]['prefix']}frequency", 0)
        life_f_rank = row.get('life_f_rank', 0)
        
        is_high_freq = life_f_rank >= 0.7
        is_active = short_freq > 0
        
        if is_high_freq and is_active:
            return "主力支付 (Main)"
        elif is_high_freq and not is_active:
            return "已棄用 (Abandoned)"
        elif not is_high_freq and is_active:
            return "輔助支付 (Backup)"
        else:
            return "冷門支付 (Rare)"

    final_df['segment'] = final_df.apply(_label_segment, axis=1)
    return final_df.reset_index()

def calculate_card_rfm(df_raw: pd.DataFrame, windows_config: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    信用卡維度 RFM 分群計算 (以 bank_name, card_type 聚合)
    """
    df_clean = get_clean_df(df_raw)
    card_mask = df_clean['card_type'].notna() & (df_clean['card_type'] != '')
    df_clean = cast(pd.DataFrame, df_clean[card_mask].copy())
    
    final_df = calculate_multi_window_rfm(df_clean, ['bank_name', 'card_type'], windows_config)
    
    if final_df.empty:
        return pd.DataFrame()
        
    for drop_c in ['category', 'sub_category']:
        if drop_c in final_df.columns:
            final_df = final_df.drop(columns=[drop_c])
        
    short_prefix = windows_config[-1]['prefix']
    if f'{short_prefix}frequency' in final_df.columns:
        final_df['avg_ticket'] = (
            final_df[f'{short_prefix}monetary'] / final_df[f'{short_prefix}frequency']
        ).replace([np.inf, -np.inf], 0).fillna(0).astype(int)

    def _label_segment(row):
        recency = row.get(f'{short_prefix}recency_days', 9999)
        if recency > 180:
            return "❄️ 冷凍/沉睡"
        f_rank = row.get(f'{short_prefix}f_rank', 0)
        m_rank = row.get(f'{short_prefix}m_rank', 0)
        
        if f_rank >= 0.5 and m_rank >= 0.5:
            return "👑 主力攻擊手"
        elif f_rank < 0.5 and m_rank >= 0.5:
            return "🎯 狙擊手" 
        elif f_rank >= 0.5 and m_rank < 0.5:
            return "🔄 後勤補給" 
        else:
            return "📉 低效冗餘"
        
    final_df['segment'] = final_df.apply(_label_segment, axis=1)
    return final_df.reset_index()
