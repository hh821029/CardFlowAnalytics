# analytics/common/ranking.py
"""
百分比排名 (PR Rank) 通用計算工具
"""
import pandas as pd

def add_rfm_ranks(rfm_df: pd.DataFrame, prefix: str = '') -> pd.DataFrame:
    """
    為 RFM 結果加上百分比排名 (PR值, 0~1)
    - Recency: 天數越少越好 (ascending=False)
    - Frequency: 次數越多越好 (ascending=True)
    - Monetary: 金額越高越好 (ascending=True)
    """
    if rfm_df.empty:
        return rfm_df
        
    rec_col = f'{prefix}recency_days'
    freq_col = f'{prefix}frequency'
    mon_col = f'{prefix}monetary'
    
    if rec_col in rfm_df.columns:
        rfm_df[f'{prefix}r_rank'] = rfm_df[rec_col].rank(pct=True, ascending=False)
        
    if freq_col in rfm_df.columns:
        rfm_df[f'{prefix}f_rank'] = rfm_df[freq_col].rank(pct=True, ascending=True)
        
    if mon_col in rfm_df.columns:
        rfm_df[f'{prefix}m_rank'] = rfm_df[mon_col].rank(pct=True, ascending=True)
        
    return rfm_df
