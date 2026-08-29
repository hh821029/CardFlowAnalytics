# analytics/sankeyflow/modules.py
"""
金流桑基圖計算引擎 (Sankey Flow Engine)
負責將交易明細轉化為多層級金流流向 (信用卡 ➔ 支付管道 ➔ 消費類別 ➔ 核心商家)，
產出符合 ECharts / Plotly 標準之 nodes 與 links 數據結構
"""
import logging
import pandas as pd
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def build_sankey_flow(
    df: pd.DataFrame,
    include_merchants: bool = False,
    top_merchants_limit: int = 10,
    min_amount_threshold: float = 0.0
) -> Dict[str, Any]:
    """
    從交易明細建立多層級桑基圖資料結構：
    - Layer 1: 信用卡 (card_type) ➔ 支付管道 (payment_process)
    - Layer 2: 支付管道 (payment_process) ➔ 消費類別 (category)
    - (選填) Layer 3: 消費類別 (category) ➔ 前 N 大商家 (normalized_merchant)

    回傳:
        {
            "nodes": [{"name": "node_name"}, ...],
            "links": [{"source": "s", "target": "t", "value": 100.0}, ...],
            "summary": { ... }
        }
    """
    if df.empty:
        return {"nodes": [], "links": [], "summary": {"total_amount": 0, "node_count": 0, "link_count": 0}}

    df_work = df.copy()
    amount_col = 'payment_amount' if 'payment_amount' in df_work.columns else 'pay_amount'
    
    # 欄位防護與預設值
    if 'card_type' not in df_work.columns:
        df_work['card_type'] = '其他卡片'
    else:
        df_work['card_type'] = df_work['card_type'].fillna('其他卡片').replace('', '其他卡片')
        
    if 'payment_process' not in df_work.columns:
        df_work['payment_process'] = '一般實體刷卡'
    else:
        df_work['payment_process'] = df_work['payment_process'].fillna('一般實體刷卡').replace('', '一般實體刷卡')
        
    if 'category' not in df_work.columns:
        df_work['category'] = '未分類'
    else:
        df_work['category'] = df_work['category'].fillna('未分類').replace('', '未分類')

    links_list: List[Dict[str, Any]] = []

    # 1. 第一層流向：信用卡 ➔ 支付管道
    g1 = df_work.groupby(['card_type', 'payment_process'], as_index=False)[amount_col].sum()
    for _, row in g1.iterrows():
        val = round(float(row[amount_col]), 2)
        if val > min_amount_threshold:
            links_list.append({
                'source': str(row['card_type']).strip(),
                'target': str(row['payment_process']).strip(),
                'value': val,
                'layer': 'card_to_payment'
            })

    # 2. 第二層流向：支付管道 ➔ 消費類別
    g2 = df_work.groupby(['payment_process', 'category'], as_index=False)[amount_col].sum()
    for _, row in g2.iterrows():
        val = round(float(row[amount_col]), 2)
        if val > min_amount_threshold:
            links_list.append({
                'source': str(row['payment_process']).strip(),
                'target': str(row['category']).strip(),
                'value': val,
                'layer': 'payment_to_category'
            })

    # 3. (選填) 第三層流向：消費類別 ➔ 前 N 大商家
    if include_merchants and ('normalized_merchant' in df_work.columns or 'merchant_display' in df_work.columns):
        m_col = 'normalized_merchant' if 'normalized_merchant' in df_work.columns else 'merchant_display'
        df_work[m_col] = df_work[m_col].fillna('其他商家').replace('', '其他商家')
        
        # 取得前 N 大商家清單
        merchant_sums = df_work.groupby(m_col)[amount_col].sum()
        top_merchants = list(merchant_sums.nlargest(top_merchants_limit).index)
        
        df_m = df_work[df_work[m_col].isin(top_merchants)]
        g3 = df_m.groupby(['category', m_col], as_index=False)[amount_col].sum()
        for _, row in g3.iterrows():
            val = round(float(row[amount_col]), 2)
            if val > min_amount_threshold:
                links_list.append({
                    'source': str(row['category']).strip(),
                    'target': str(row[m_col]).strip(),
                    'value': val,
                    'layer': 'category_to_merchant'
                })

    # 4. 彙整所有節點 (Nodes) 確保唯一
    node_names = set()
    for link in links_list:
        node_names.add(link['source'])
        node_names.add(link['target'])

    nodes = [{'name': name} for name in sorted(node_names)]
    total_amount = round(float(df_work[amount_col].sum()), 2)

    return {
        "nodes": nodes,
        "links": links_list,
        "summary": {
            "total_amount": total_amount,
            "node_count": len(nodes),
            "link_count": len(links_list),
            "card_count": df_work['card_type'].nunique(),
            "payment_count": df_work['payment_process'].nunique(),
            "category_count": df_work['category'].nunique()
        }
    }


def build_sankey_dataframe(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """產出便於入庫或存為 CSV 的 DataFrame 結構"""
    res = build_sankey_flow(df, **kwargs)
    if not res['links']:
        return pd.DataFrame(columns=['source', 'target', 'value', 'layer'])
    return pd.DataFrame(res['links'])
