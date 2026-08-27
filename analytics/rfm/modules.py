# analytics/rfm/modules.py
"""
RFM 價值分群模型核心模組
支援三大維度 (商家、付款管道、信用卡) 與雙維度交叉之多時間視窗 RFM 計算與 Segment 分群
"""
import logging
import pandas as pd
import numpy as np
from datetime import timedelta
from typing import List, Dict, Any, Union, Optional, cast

from analytics.common import get_clean_df, add_rfm_ranks
from profiles.loaders.config_loader import ConfigLoader

logger = logging.getLogger(__name__)

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
            rfm_part_clean = rfm_part.drop(columns=cols_to_drop) if cols_to_drop else rfm_part
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

def _load_merchant_dim_mapping() -> Dict[str, Dict[str, str]]:
    """
    從 dim_merchants (ConfigLoader) 載入 normalized_merchant -> {category, sub_category} 映射
    """
    mapping: Dict[str, Dict[str, str]] = {}
    try:
        df_dim = ConfigLoader.load_config(base_name='dim_merchants')
        if not df_dim.empty and 'normalized_merchant' in df_dim.columns:
            if 'priority' in df_dim.columns:
                p_num = pd.to_numeric(df_dim['priority'], errors='coerce')
                if isinstance(p_num, pd.Series):
                    df_dim['priority_num'] = p_num.fillna(999.0)
                else:
                    df_dim['priority_num'] = 999.0 if pd.isna(p_num) else p_num
                df_dim = df_dim.sort_values('priority_num')
            for _, row in df_dim.iterrows():
                m_name = str(row.get('normalized_merchant', '')).strip()
                if not m_name or m_name in mapping:
                    continue
                cat = str(row.get('category', '')).strip() if pd.notna(row.get('category')) else ''
                sub_cat = str(row.get('sub_category', '')).strip() if pd.notna(row.get('sub_category')) else ''
                if cat and cat.lower() != 'nan':
                    mapping[m_name] = {'category': cat, 'sub_category': sub_cat if sub_cat.lower() != 'nan' else ''}
    except Exception as e:
        logger.debug(f"讀取 dim_merchants 失敗: {e}")
    return mapping

def calculate_merchant_rfm(df_raw: pd.DataFrame, windows_config: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    商家維度 RFM 分群計算 (以 normalized_merchant 聚合)
    """
    df_clean = get_clean_df(df_raw)
    if 'normalized_merchant' not in df_clean.columns:
        if 'merchant_display' in df_clean.columns:
            df_clean['normalized_merchant'] = df_clean['merchant_display']
        elif 'merchant' in df_clean.columns:
            df_clean['normalized_merchant'] = df_clean['merchant']
        else:
            df_clean['normalized_merchant'] = ''
    else:
        fallback = df_clean['merchant_display'] if 'merchant_display' in df_clean.columns else (
            df_clean['merchant'] if 'merchant' in df_clean.columns else ''
        )
        df_clean['normalized_merchant'] = df_clean['normalized_merchant'].fillna(fallback)
        
    final_df = calculate_multi_window_rfm(df_clean, 'normalized_merchant', windows_config)
    
    if final_df.empty:
        return pd.DataFrame()
        
    # 1. 建立全域類別映射 (從 df_clean 提取非空的最新/眾數分類)
    global_cat_map: Dict[str, Dict[str, str]] = {}
    if 'category' in df_clean.columns:
        valid_cat_df = df_clean[df_clean['category'].notna() & (df_clean['category'] != '') & (df_clean['category'] != '未分類')]
        for m_name, group in valid_cat_df.groupby('normalized_merchant'):
            cat = group['category'].mode().iloc[0] if not group['category'].empty else ''
            sub_cat = ''
            if 'sub_category' in group.columns:
                valid_sub = group[group['sub_category'].notna() & (group['sub_category'] != '')]
                if not valid_sub.empty:
                    sub_cat = valid_sub['sub_category'].mode().iloc[0]
            global_cat_map[str(m_name).strip()] = {'category': cat, 'sub_category': sub_cat}

    # 2. 載入 dim_merchants 維度表作為 Fallback 補齊
    dim_map = _load_merchant_dim_mapping()

    # 3. 填補 category 與 sub_category
    cats = []
    sub_cats = []
    for idx, row in final_df.iterrows():
        m_name = idx.strip() if isinstance(idx, str) else str(row.name).strip()
        curr_cat = row.get('category', '')
        curr_sub = row.get('sub_category', '')

        if not curr_cat or curr_cat == '未分類':
            if m_name in global_cat_map:
                curr_cat = global_cat_map[m_name]['category']
                curr_sub = global_cat_map[m_name]['sub_category']
            elif m_name in dim_map:
                curr_cat = dim_map[m_name]['category']
                curr_sub = dim_map[m_name]['sub_category']
            else:
                curr_cat = '未分類'
                curr_sub = ''
        cats.append(curr_cat if curr_cat else '未分類')
        sub_cats.append(curr_sub if curr_sub else '')

    final_df['category'] = cats
    final_df['sub_category'] = sub_cats

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
    res_df = final_df.reset_index()
    
    # 組織欄位順序: normalized_merchant, category, sub_category, segment, ... 其餘指標
    lead_cols = ['normalized_merchant', 'category', 'sub_category', 'segment']
    other_cols = [c for c in res_df.columns if c not in lead_cols]
    ordered_cols = [c for c in lead_cols if c in res_df.columns] + other_cols
    return cast(pd.DataFrame, res_df[ordered_cols])

def calculate_category_rfm(df_raw: pd.DataFrame, windows_config: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    消費類別維度 RFM 分群計算 (以 category 聚合)
    """
    df_clean = get_clean_df(df_raw)
    if 'category' not in df_clean.columns:
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

def _load_card_status_mapping() -> Dict[str, str]:
    """
    從 bridge_user_cards (優先讀 JSON，次讀 CSV) 載入 card_type -> status 映射
    若該 card_type 底下有任一卡片為 active，則整體判定為 active；若全部為 cancelled 則為 cancelled。
    """
    status_map: Dict[str, str] = {}
    
    # 1. 優先嘗試讀取 bridge_user_cards.json
    try:
        data = ConfigLoader.load_json(base_name='bridge_user_cards')
        if isinstance(data, list):
            for card_item in data:
                if isinstance(card_item, dict):
                    ctype = str(card_item.get('card_type', '')).strip()
                    if not ctype:
                        continue
                    history = card_item.get('card_history', [])
                    is_active = any(
                        str(h.get('status', '')).lower() == 'active' 
                        for h in history if isinstance(h, dict)
                    )
                    status_map[ctype] = 'active' if is_active else 'cancelled'
    except Exception as e:
        logger.debug(f"讀取 bridge_user_cards.json 失敗: {e}")
        
    # 2. 若為空，嘗試透過 ConfigLoader.load_config 讀取 CSV
    if not status_map:
        try:
            df_cards = ConfigLoader.load_config(base_name='bridge_user_cards')
            if not df_cards.empty and 'card_type' in df_cards.columns:
                status_col = 'status' if 'status' in df_cards.columns else 'is_active'
                if status_col in df_cards.columns:
                    for ctype, group in df_cards.groupby('card_type'):
                        vals = group[status_col].astype(str).str.lower().tolist()
                        has_active = any(v in ['active', 'true', '1'] for v in vals)
                        status_map[str(ctype).strip()] = 'active' if has_active else 'cancelled'
        except Exception as e:
            logger.debug(f"讀取 bridge_user_cards.csv 失敗: {e}")
            
    return status_map

def calculate_card_rfm(df_raw: pd.DataFrame, windows_config: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    信用卡維度 RFM 分群計算 (以 bank_name, card_type 聚合)
    輸出欄位包含 status (active/cancelled) 與 segment 並列於前置欄位
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
            return "👑 主要使用卡片"
        elif f_rank < 0.5 and m_rank >= 0.5:
            return "🎯 特定用途使用卡片" 
        elif f_rank >= 0.5 and m_rank < 0.5:
            return "🔄 備用卡片" 
        else:
            return "📉 不常用卡片"
        
    final_df['segment'] = final_df.apply(_label_segment, axis=1)
    res_df = final_df.reset_index()
    
    # 載入持卡狀態 (active / cancelled)
    status_map = _load_card_status_mapping()
    res_df['status'] = res_df['card_type'].apply(lambda x: status_map.get(str(x).strip(), 'active'))
    
    # 組織欄位順序: bank_name, card_type, status, segment, ... 其餘指標
    lead_cols = ['bank_name', 'card_type', 'status', 'segment']
    other_cols = [c for c in res_df.columns if c not in lead_cols]
    ordered_cols = [c for c in lead_cols if c in res_df.columns] + other_cols
    
    return cast(pd.DataFrame, res_df[ordered_cols])
