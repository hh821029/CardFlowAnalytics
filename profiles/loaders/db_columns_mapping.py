import const
import json
import pandas as pd

# 建立別名簡化程式碼 (Alias)
TC = const.TransactionColumn

def BANK_COL_MAPPING():
    """對應 dim_banks.yaml / dim_banks.csv"""
    return {
        'bank_no': 'bank_no',
        'bank_name': 'bank_name',
        'bills_mapping_name': 'bills_mapping_name'
    }

def CREDIT_CARD_PRODUCTS_COL_MAPPING():
    """對應 dim_credit_card_products.csv (公用產品主檔)"""
    return {
        'card_id': 'card_id',
        'bank_no': 'bank_no',
        'is_co_branded': 'is_co_branded',
        'is_dual_currency': 'is_dual_currency',
        'note': 'note'
    }

def BRIDGE_USER_CARDS_COL_MAPPING():
    """對應 bridge_user_cards.csv (個人持卡對照檔)"""
    return {
        'user_card_id': 'user_card_id',
        'bank_no': 'bank_no',
        'card_id': 'card_id',
        'card_type': 'card_type',
        'card_network': 'card_network',
        'smart_card_type': 'smart_card_type',
        'fx_type': 'fx_type',
        'card_no': 'card_no',
        'vpc_no': 'vpc_no',
        'vpc_type': 'vpc_type',
        'card_start_date': 'card_start_date',
        'card_end_date': 'card_end_date',
        'is_active': 'is_active',
        'is_enable_reward_calc': 'is_enable_reward_calc'
    }

def MERCHANT_COL_MAPPING():
    """對應 dim_merchants.csv"""
    return TC.get_mapping(
        TC.MERCHANT_PATTERN, TC.MERCHANT_DISPLAY,
        TC.PRIORITY, TC.CATEGORY, TC.SUB_CATEGORY, TC.RFM_EXCLUSION, TC.IS_NCCC_LISTED
    )

def PAYMENT_PROCESS_COL_MAPPING():
    """對應 dim_payment_process.csv"""
    return TC.get_mapping(
        TC.PROCESS_PATTERN, TC.PAYMENT_PROCESS, TC.PROCESS_PREFIX, TC.PRIORITY
    )

def EC_PLATFORM_COL_MAPPING():
    """對應 dim_ec_platform.csv"""
    return TC.get_mapping(
        TC.EC_PLATFORM_PATTERN, TC.EC_PLATFORM, TC.EC_PLATFORM_TYPE, TC.PRIORITY
    )

def REWARD_PROGRAM_COL_MAPPING():
    """對應 dim_card_rewards_base.csv"""
    return TC.get_mapping(
        TC.BASE_REWARD_ID,
        TC.BANK_NO, TC.BANK_NAME, TC.CARD_ID, TC.CARD_TYPE, TC.BASE_REWARD_PROGRAM, TC.BASE_REWARD_RATE,
        TC.REWARD_CYCLE, TC.CAP_AMOUNT, TC.REWARD_TYPE,
        TC.MIN_SINGLE_TRANSACTION,
        TC.PROGRAM_START_DATE, TC.PROGRAM_END_DATE, 
        TC.CALC_METHOD, TC.ROUND_STRATEGY, TC.PRIORITY, TC.REWARD_CAL_BREAK
    )

def REWARD_CAMPAIGN_COL_MAPPING():
    """對應 dim_card_rewards_campaigns.csv"""
    return TC.get_mapping(
        TC.CAMPAIGN_REWARD_ID,
        TC.BANK_NO, TC.BANK_NAME, TC.CARD_ID, TC.CARD_TYPE, TC.CAMPAIGN_REWARD_PROGRAM, TC.CAMPAIGN_REWARD_RATE,
        TC.REWARD_CYCLE, TC.CAP_AMOUNT, TC.REWARD_TYPE,
        TC.MIN_SINGLE_TRANSACTION,
        TC.PROGRAM_START_DATE, TC.PROGRAM_END_DATE, 
        TC.CALC_METHOD, TC.ROUND_STRATEGY, TC.PRIORITY, TC.REWARD_CAL_BREAK
    )

def BRIDGE_CUBE_SELECTION_COL_MAPPING():
    """對應 bridge_cube_selections_private.csv"""
    return TC.get_mapping(
        TC.BASE_REWARD_PROGRAM, TC.PROGRAM_START_DATE, TC.PROGRAM_END_DATE,
        ('備註', TC.REMARK)
    )

def BRIDGE_REWARD_LINKED_LISTS_COL_MAPPING():
    """對應 bridge_reward_linked_lists_private.csv"""
    return TC.get_mapping(
        TC.REWARD_ID, TC.MERCHANT_REWARD_POOLS_ID,('備註', TC.REMARK)
    )

def load_pools_json_to_df():
    """對應 bridge_reward_pools.json"""
    json_path = const.BRIDGE_REWARD_POOLS_PATH
    with open(json_path, 'r', encoding='utf-8') as f:
        pools_data = json.load(f)
        
    rows = []
    for p in pools_data:
        rows.append({
            'merchant_reward_pools_id': p.get('merchant_reward_pools_id'),
            'pool_name': p.get('pool_name'),
            'pass_rules': json.dumps(p.get('pass_rules', []), ensure_ascii=False), # 轉為 JSON 字串存入 JSONB
            'rules': json.dumps(p.get('rules', []), ensure_ascii=False)
        })
    return pd.DataFrame(rows)

def FX_TABLE_COL_MAPPING():
    """對應 dim_fx_table.csv"""
    return TC.get_mapping(
        TC.CONV_DATE, TC.BANK_NAME, TC.CURRENCY, TC.FX_RATE,
        ('備註', TC.REMARK)
    )

def BILLING_HISTORY_COL_MAPPING():
    """對應 dim_billing_history.csv"""
    return TC.get_mapping(
        TC.BANK_NAME, TC.CARD_TYPE,
        TC.STAT_MON, TC.CLOSING_DATE, TC.ACT_CLOSING_DATE
    )
