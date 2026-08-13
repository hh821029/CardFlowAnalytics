# rfm_analysis/rfm_utils.py
import pandas as pd

def calculate_rfm_base(df_subset, analysis_date, group_cols, prefix=''):
    """
    基礎 RFM 計算核心 (不含 Rank)
    """
    if df_subset.empty: return pd.DataFrame()

    # 1. 定義聚合規則
    agg_rules = {
        'transaction_date': lambda x: (analysis_date - x.max()).days,
        'transaction_id': 'nunique', # Frequency: 交易次數
        'payment_amount': 'sum'      # Monetary: 交易總額
    }
    
    # 兼容 Category (V2 寫入 DB 時是小寫)
    if 'category' in df_subset.columns: agg_rules['category'] = 'first'
    
    # 2. 執行 GroupBy
    rfm = df_subset.groupby(group_cols).agg(agg_rules).rename(columns={
        'transaction_date': f'{prefix}recency_days',
        'transaction_id': f'{prefix}frequency',
        'payment_amount': f'{prefix}monetary'
    })
    
    return rfm

def add_rfm_ranks(rfm_df, prefix=''):
    """
    為 RFM 結果加上百分比排名 (PR值, 0~1)
    """
    if rfm_df.empty: return rfm_df
    
    rfm_df[f'{prefix}r_rank'] = rfm_df[f'{prefix}recency_days'].rank(pct=True, ascending=False)
    rfm_df[f'{prefix}f_rank'] = rfm_df[f'{prefix}frequency'].rank(pct=True, ascending=True)
    rfm_df[f'{prefix}m_rank'] = rfm_df[f'{prefix}monetary'].rank(pct=True, ascending=True)
    
    return rfm_df
