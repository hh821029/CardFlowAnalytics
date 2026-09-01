# analytics/sankeyflow/modules.py
"""
金流桑基圖計算引擎 (Sankey Flow Engine)
負責將交易明細轉化為多層級金流流向 (發卡行 ➔ 信用卡 ➔ 支付管道 ➔ 消費類別 ➔ 核心商家)，
產出符合 ECharts / Plotly 標準之 nodes 與 links 數據結構，並支援 DEMO 脫敏白名單機制
"""
import re
import logging
import pandas as pd
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# DEMO 模式預設白名單
DEFAULT_DEMO_CARD_KEYWORDS = ['cube', 'uniopen', 'unicard']
DEFAULT_DEMO_PAYMENTS = [
    'Line Pay', '街口支付', '悠遊付', '一卡通',
    'icash pay', '全支付', '全盈支付', '一般實體刷卡'
]


def _match_demo_payment(payment_str: str) -> Optional[str]:
    """模糊匹配並標準化 DEMO 支付管道名稱"""
    if not payment_str or not isinstance(payment_str, str):
        return None
    p_clean = payment_str.strip().lower()
    
    if 'line' in p_clean and 'pay' in p_clean:
        return 'Line Pay'
    if '街口' in p_clean or 'jko' in p_clean:
        return '街口支付'
    if '悠遊付' in p_clean or 'easywallet' in p_clean:
        return '悠遊付'
    if '一卡通' in p_clean or 'ipass' in p_clean:
        return '一卡通'
    if 'icash' in p_clean:
        return 'icash pay'
    if '全支付' in p_clean or 'pxpayplus' in p_clean:
        return '全支付'
    if '全盈' in p_clean or 'pluspay' in p_clean:
        return '全盈支付'
    if '實體' in p_clean or '一般' in p_clean:
        return '一般實體刷卡'
        
    for target in DEFAULT_DEMO_PAYMENTS:
        if target.lower() in p_clean or p_clean in target.lower():
            return target
    return None


def build_sankey_flow(
    df: pd.DataFrame,
    include_merchants: bool = False,
    top_merchants_limit: int = 10,
    min_amount_threshold: float = 0.0,
    demo_mode: bool = False,
    whitelist_card_keywords: Optional[List[str]] = None,
    whitelist_payments: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    從交易明細建立多層級桑基圖資料結構：
    - Layer 0: 發卡行 (bank_name) ➔ 信用卡 (card_type)
    - Layer 1: 信用卡 (card_type) ➔ 支付管道 (payment_process)
    - Layer 2: 支付管道 (payment_process) ➔ 消費類別 (category)
    - (選填) Layer 3: 消費類別 (category) ➔ 前 N 大商家 (normalized_merchant)

    回傳:
        {
            "nodes": [{"name": "node_name"}, ...],
            "links": [{"source": "s", "target": "t", "value": 100.0, "layer": "..."}, ...],
            "summary": { ... }
        }
    """
    if df.empty:
        return {"nodes": [], "links": [], "summary": {"total_amount": 0, "node_count": 0, "link_count": 0}}

    df_work = df.copy()
    amount_col = 'payment_amount' if 'payment_amount' in df_work.columns else 'pay_amount'
    
    # 基礎欄位補齊
    if 'bank_name' not in df_work.columns:
        df_work['bank_name'] = '其他發卡行'
    else:
        df_work['bank_name'] = df_work['bank_name'].fillna('其他發卡行').replace('', '其他發卡行')

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

    # ==========================================
    # DEMO 模式脫敏與白名單過濾
    # ==========================================
    if demo_mode:
        card_keywords = whitelist_card_keywords or DEFAULT_DEMO_CARD_KEYWORDS
        
        def mask_card_and_bank(row):
            card_str = str(row['card_type'])
            card_lower = card_str.lower()
            # 檢查卡片是否匹配白名單
            is_matched = any(kw.lower() in card_lower for kw in card_keywords)
            if not is_matched:
                return pd.Series({'bank_name': '其他發卡行', 'card_type': '其他卡片'})
            return pd.Series({'bank_name': str(row['bank_name']), 'card_type': card_str})

        masked_card_info = df_work.apply(mask_card_and_bank, axis=1)
        df_work['bank_name'] = masked_card_info['bank_name']
        df_work['card_type'] = masked_card_info['card_type']

        # 支付管道白名單過濾
        def mask_payment(val):
            matched = _match_demo_payment(str(val))
            return matched if matched else '其他支付'

        df_work['payment_process'] = df_work['payment_process'].apply(mask_payment)

    links_list: List[Dict[str, Any]] = []

    # 1. 第 0 層流向：發卡行 ➔ 信用卡
    g0 = df_work.groupby(['bank_name', 'card_type'], as_index=False)[amount_col].sum()
    for _, row in g0.iterrows():
        val = round(float(row[amount_col]), 2)
        if val > min_amount_threshold:
            links_list.append({
                'source': str(row['bank_name']).strip(),
                'target': str(row['card_type']).strip(),
                'value': val,
                'layer': 'bank_to_card'
            })

    # 2. 第 1 層流向：信用卡 ➔ 支付管道
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

    # 3. 第 2 層流向：支付管道 ➔ 消費類別
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

    # 4. (選填) 第 3 層流向：消費類別 ➔ 前 N 大商家
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

    # 5. 彙整所有節點 (Nodes) 確保唯一
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
            "bank_count": df_work['bank_name'].nunique(),
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
