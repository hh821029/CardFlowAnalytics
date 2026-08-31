# const.py
import pandas as pd
import os
import yaml
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, NamedTuple, Literal
from dotenv import load_dotenv


# 自動載入本機 .env 設定檔 (若無 .env 則自動降級載入 .env.example)
try:
    _env_file = os.path.join(os.path.dirname(__file__), '.env')
    _example_file = os.path.join(os.path.dirname(__file__), '.env.example')
    
    if os.path.exists(_env_file):
        load_dotenv(_env_file)
    if os.path.exists(_example_file):
        load_dotenv(_example_file, override=False)
except ImportError:
    for _fname in ['.env', '.env.example']:
        _fpath = os.path.join(os.path.dirname(__file__), _fname)
        if os.path.exists(_fpath):
            with open(_fpath, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith('#') and '=' in _line:
                        _k, _v = _line.split('=', 1)
                        _k, _v = _k.strip(), _v.strip().strip("'\"")
                        if _k not in os.environ:
                            os.environ[_k] = _v


pd.set_option('future.no_silent_downcasting', True)

DType = Literal['date', 'str', 'float', 'int', 'bool']

class ColumnSpec(NamedTuple):
    col_name: str
    dtype: DType
    max_length: Optional[int]
    sql_name: Optional[str]


# ==========================================
# 1. 資料定義列舉 (Enum) 
# ==========================================

class TransactionColumn(Enum):
    # 定義格式: (csv_col_name, data_type, max_length, sql_name)
    # 包含交易資料的各個資料型態，欄位名稱，以及對應的 SQL 欄位名稱
    # 另外也定義回饋規則相關的欄位，方便後續擴展和統一管理

    # 識別碼資訊
    TXN_ID = ColumnSpec('transaction_id', 'str', 32, 'transaction_id')

    # 交易日期資訊
    TXN_DATE = ColumnSpec('transaction_date', 'date', None, 'transaction_date')
    POST_DATE = ColumnSpec('posting_date', 'date', None, 'posting_date')
    CONV_DATE = ColumnSpec('conversion_date', 'date', None, 'conversion_date')
    STAT_MON = ColumnSpec('statement_month', 'date', None, 'statement_month')
    CLOSING_DATE = ColumnSpec('closing_date', 'date', None, 'closing_date')
    ACT_CLOSING_DATE = ColumnSpec('actual_closing_date', 'date', None, 'actual_closing_date')
    
    # 商店消費資訊
    MERCHANT = ColumnSpec('merchant', 'str', 500, 'merchant_name')
    MERCHANT_PATTERN = ColumnSpec('merchant_pattern', 'str', 500, 'merchant_pattern') # 用於規則匹配的商家名稱欄位
    MERCHANT_DISPLAY = ColumnSpec('merchant_display', 'str', 500, 'merchant_display')
    NORMALIZED_MERCHANT = ColumnSpec('normalized_merchant', 'str', 500, 'normalized_merchant')
    LOCATION = ColumnSpec('merchant_location', 'str', 2, 'merchant_location')
    CONSUMPTION_PLACE = ColumnSpec('consumption_place', 'str', 255, 'consumption_place')
    PAYMENT_PROCESS = ColumnSpec('payment_process', 'str', 100, 'payment_process')
    TXN_TYPE = ColumnSpec('transaction_type', 'str', 50, 'transaction_type')
    CATEGORY = ColumnSpec('category', 'str', 100, 'category')
    SUB_CATEGORY = ColumnSpec('sub_category', 'str', 100, 'sub_category')
    PROCESS_PATTERN = ColumnSpec('payment_process_pattern', 'str', 100, 'payment_process_pattern')
    PROCESS_PREFIX = ColumnSpec('process_prefix', 'str', 50, 'process_prefix')
    EC_PLATFORM = ColumnSpec('ec_platform', 'str', 100, 'ec_platform')
    EC_PLATFORM_PATTERN = ColumnSpec('ec_platform_pattern', 'str', 100, 'ec_platform_pattern')
    EC_CATEGORY = ColumnSpec('ec_category', 'str', 100, 'ec_category')
    EC_SUB_CATEGORY = ColumnSpec('ec_sub_category', 'str', 100, 'ec_sub_category')

    # 消費金額資訊
    CURRENCY = ColumnSpec('currency_type', 'str', 3, 'currency_type')
    CURR_AMOUNT = ColumnSpec('currency_amount', 'float', None, 'currency_amount')
    PAY_AMOUNT = ColumnSpec('payment_amount', 'float', None, 'payment_amount')
    PAY_CURR = ColumnSpec('payment_currency', 'str', 3, 'payment_currency')
    AMOUNT = ColumnSpec('amount', 'float', None, 'amount')

    # 卡片資訊
    BANK_NO = ColumnSpec('bank_no', 'str', 3, 'bank_no')
    BANK_NAME = ColumnSpec('bank_name', 'str', 50, 'bank_name')

    CARD_NO = ColumnSpec('card_no', 'str', 4, 'card_no')
    CARD_ID = ColumnSpec('card_id', 'str', 255, 'card_id')
    CARD_TYPE = ColumnSpec('card_type', 'str', 255, 'card_type')
    VPC_NO = ColumnSpec('vpc_no', 'str', 4, 'vpc_no')
    VPC_TYPE = ColumnSpec('vpc_type', 'str', 50, 'vpc_type')

    CARD_NETWORK = ColumnSpec('card_network', 'str', 50, 'card_network')
    SMART_CARD_TYPE = ColumnSpec('smart_card_type', 'str', 50, 'smart_card_type')
    IS_CO_BRANDED = ColumnSpec('is_co_branded', 'str', 10, 'is_co_branded')
    IS_DUAL_CURRENCY = ColumnSpec('is_dual_currency', 'str', 10, 'is_dual_currency')
    FX_TYPE = ColumnSpec('fx_type', 'str', 5, 'fx_type')
    ACTIVE_STATUS = ColumnSpec('active_status', 'str', 20, 'active_status')
    ENABLE_REWARD_CALC = ColumnSpec('enable_reward_calc', 'str', 10, 'enable_reward_calc')

    CARD_START_DATE = ColumnSpec('card_start_date', 'date', None, 'card_start_date')
    CARD_END_DATE = ColumnSpec('card_end_date', 'date', None, 'card_end_date')
    IS_ACTIVE = ColumnSpec('is_active', 'str', 10, 'is_active')

    # 回饋資訊
    # 整合所有回饋方案的相關欄位
    REWARD_ID = ColumnSpec('reward_id', 'str', 255, 'reward_id')
    MERCHANT_REWARD_POOLS_ID = ColumnSpec('merchant_reward_pools_id', 'str', 255, 'merchant_reward_pools_id')
    REWARD_PROGRAM = ColumnSpec('reward_program', 'str', 100, 'reward_program')
    REWARD_RATE = ColumnSpec('reward_rate', 'float', None, 'reward_rate')
    REWARD_CYCLE = ColumnSpec('reward_cycle', 'str', 50, 'reward_cycle')
    PROGRAM_START_DATE = ColumnSpec('start_date', 'date', None, 'start_date')
    PROGRAM_END_DATE = ColumnSpec('end_date', 'date', None, 'end_date')
    CAP_AMOUNT = ColumnSpec('cap_amount', 'float', None, 'cap_amount')
    MAX_POSTING_DATE = ColumnSpec('max_posting_date', 'date', None, 'max_posting_date')
    REWARD_TYPE = ColumnSpec('reward_type', 'str', 50, 'reward_type')
    CALC_METHOD = ColumnSpec('calc_method', 'str', 50, 'calc_method')
    ROUND_STRATEGY = ColumnSpec('round_strategy', 'str', 50, 'round_strategy')
    MERCHANT_RATE = ColumnSpec('merchant_rate', 'float', None, 'merchant_rate')
    REWARD_CAL_BREAK = ColumnSpec('reward_cal_break', 'str', 10, 'reward_cal_break')
    CONDITION = ColumnSpec('condition', 'str', 255, 'condition')
    MIN_SINGLE_TRANSACTION = ColumnSpec('min_single_transaction', 'float', None, 'min_single_transaction')
    CUMULATIVE_SPEND_THRESHOLD = ColumnSpec('cumulative_spend_threshold', 'float', None, 'cumulative_spend_threshold')
    IS_ENABLE_REWARD_CALC = ColumnSpec('is_enable_reward_calc', 'str', 10, 'is_enable_reward_calc')
    
    # 適用於回饋方案本身( base )之相關欄位
    BASE_REWARD_ID = ColumnSpec('base_reward_id', 'str', 255, 'base_reward_id')
    BASE_REWARD_PROGRAM = ColumnSpec('base_reward_program', 'str', 100, 'base_reward_program')
    BASE_REWARD_RATE = ColumnSpec('base_reward_rate', 'float', None, 'base_reward_rate')
    
    # 適用於加碼回饋活動( campaign )之相關欄位
    CAMPAIGN_REWARD_ID = ColumnSpec('campaign_reward_id', 'str', 255, 'campaign_reward_id')
    CAMPAIGN_REWARD_PROGRAM = ColumnSpec('campaign_reward_program', 'str', 100, 'campaign_reward_program')
    CAMPAIGN_REWARD_RATE = ColumnSpec('campaign_reward_rate', 'float', None, 'campaign_reward_rate')
    RULES_REWARD_PROGRAM = ColumnSpec('rules_reward_program', 'str', 100, 'rules_reward_program')
    
    # 適用於特店回饋池 (Reward Pools) 之相關欄位
    POOL_NAME = ColumnSpec('pool_name', 'str', 255, 'pool_name')
    RULE_TYPE = ColumnSpec('rule_type', 'str', 50, 'rule_type')
    PASS_RULES = ColumnSpec('pass_rules', 'str', None, 'pass_rules')
    RULES = ColumnSpec('rules', 'str', None, 'rules')

    # 匯率資訊涉及雙幣卡的回饋計算，因此放在回饋資訊補充。
    FX_RATE = ColumnSpec('exchange_rate', 'float', None, 'exchange_rate')

    # 維度表與控制輔助欄位
    PRIORITY = ColumnSpec('priority', 'int', None, 'priority')
    RFM_EXCLUSION = ColumnSpec('rfm_exclusion', 'str', 10, 'rfm_exclusion')
    IS_NCCC_LISTED = ColumnSpec('is_nccc_listed', 'str', 10, 'is_nccc_listed')
    EC_PLATFORM_TYPE = ColumnSpec('ec_platform_type', 'str', 50, 'ec_platform_type')

    # 其他資訊(像是分期資訊等)
    INS_PLN = ColumnSpec('installment_plan', 'str', 100, 'installment_plan')
    REMARK = ColumnSpec('remark', 'str', 1000, 'remark')

    # 暫存/運算用欄位 (Virtual Columns，不寫入資料庫)
    # 將 sql_name 設為 None，讓 mapping 自動攔截
    # TEMP_CALC_FLAG = ColumnSpec('temp_calc_flag', 'bool', None, None)

    @property
    def col_name(self): return self.value[0]
    @property
    def dtype(self): return self.value[1]
    @property
    def max_length(self): return self.value[2]
    @property
    def sql_name(self): return self.value[3]

    @classmethod
    def get_mapping(cls, *members):
        """
        動態產生欄位的映射表 (csv_col_name -> sql_name)。
        - 傳入 Enum 成員：自動建立 col_name -> sql_name
        - 傳入 Tuple (source, target)：建立 source -> target 的客製化映射 (用於處理改名邏輯)
        """
        mapping = {}
        for item in members:
            if isinstance(item, tuple) and len(item) == 2:
                src, tgt = item
                src_name = src.col_name if isinstance(src, cls) else src
                tgt_name = tgt.sql_name if isinstance(tgt, cls) else tgt
                if tgt_name is not None:
                    mapping[src_name] = tgt_name
            elif isinstance(item, cls):
                if item.sql_name is not None:
                    mapping[item.col_name] = item.sql_name
            else:
                # 攔截預期外的輸入型態（防呆機制）
                raise TypeError(f"不支援的傳入參數型態: {type(item)}")
        return mapping

    @classmethod
    def get_sql_dtypes(cls, df: pd.DataFrame) -> dict:
        """
        依據 DataFrame 的欄位與 TransactionColumn 的定義，動態產出 SQLAlchemy 欄位原生型態字典 (Date, Float, Boolean, String)
        """
        try:
            from sqlalchemy import Date, Float, Integer, Boolean, String, Text
        except ImportError:
            return {}

        dtype_dict = {}
        spec_map = {}
        for member in cls:
            if member.sql_name:
                spec_map[member.sql_name] = member
            spec_map[member.col_name] = member

        for col in df.columns:
            if col in spec_map:
                spec = spec_map[col]
                t = spec.dtype
                if t == 'date':
                    dtype_dict[col] = Date()
                elif t == 'float':
                    dtype_dict[col] = Float()
                elif t == 'int':
                    dtype_dict[col] = Integer()
                elif t == 'bool':
                    dtype_dict[col] = Boolean()
                elif t == 'str':
                    if spec.max_length:
                        dtype_dict[col] = String(spec.max_length)
                    else:
                        dtype_dict[col] = Text()

        return dtype_dict

class TransactionType(Enum):
    PAYMENT = '繳款'
    REDEMPTION = '紅利折抵'
    FEE = '各項費用'
    REFUND = '退刷'
    FOREIGN = '一般國外交易'
    FOREIGN_TWD = '台幣跨境交易'
    FOREIGN_DUAL = '一般雙幣交易'
    GENERAL = '交易'
    VERIFY = '驗證/零元'
    UNKNOWN = '未分類'

    @property
    def label(self):
        return self.value

class Location(Enum):
    TW = ('TW', 'TWN')
    US = ('US', 'USA')
    JP = ('JP', 'JPN')
    KR = ('KR', 'KOR')
    HK = ('HK', 'HKG')
    SG = ('SG', 'SGP')
    GB = ('GB', 'GBR')
    CN = ('CN', 'CHN')
    IE = ('IE', 'IRL')
    DE = ('DE', 'DEU')
    FR = ('FR', 'FRA')
    AU = ('AU', 'AUS')
    VN = ('VN', 'VNM')
    TH = ('TH', 'THA')
    MY = ('MY', 'MYS')
    ID = ('ID', 'IDN')

    @property
    def alpha_2(self):
        """兩碼國別代碼 (ISO 3166-1 alpha-2)"""
        return self.value[0]

    @property
    def alpha_3(self):
        """三碼國別代碼 (ISO 3166-1 alpha-3)"""
        return self.value[1]

    @classmethod
    def _missing_(cls, value):
        """支援智慧查找：輸入兩碼或三碼均可匹配到成員"""
        # 預防性檢查：若是 None 或非字串，直接回傳 None (由 Enum 丟出 ValueError 或由 normalize 處理)
        if not isinstance(value, str) or not value.strip():
            return None
        
        c = value.upper().strip()
        for member in cls:
            if c == member.alpha_2 or c == member.alpha_3:
                return member
        return None

    @classmethod
    def normalize(cls, code):
        """標準化輸出：將任意格式國別轉為兩碼。若無法識別或為空則回傳原值。"""
        if pd.isna(code) or str(code).strip() == '' or str(code).upper() == 'NONE':
            return code
        
        try:
            loc = cls(code) # 會觸發 _missing_
            return loc.alpha_2 if loc else code
        except (ValueError, TypeError):
            return code

class Currency(Enum):
    TWD = ('TWD', 'NTD', '新臺幣')
    USD = ('USD', 'US DOLLAR', '美元')
    JPY = ('JPY', 'YEN', '日圓')
    EUR = ('EUR', 'EURO', '歐元')
    HKD = ('HKD', 'HK DOLLAR', '港幣')
    GBP = ('GBP', 'POUND', '英鎊')
    AUD = ('AUD', 'AU DOLLAR', '澳幣')
    CAD = ('CAD', 'CA DOLLAR', '加拿大元')
    CHF = ('CHF', 'SWISS FRANC', '瑞士法郎')
    CNY = ('CNY', 'RMB', '人民幣')
    THB = ('THB', 'BAHT', '泰銖')
    KRW = ('KRW', 'WON', '韓元')
    IDR = ('IDR', 'RUPIAH', '印尼盾')

    @property
    def code(self):
        """標準三碼幣別代碼 (ISO 4217)"""
        return self.value[0]

    @classmethod
    def _missing_(cls, value):
        """支援智慧查找：支援別名 (如 NTD) 或中文名稱"""
        if not isinstance(value, str) or not value.strip():
            return None
        
        c = value.upper().strip()
        for member in cls:
            if c == member.code or c in member.value:
                return member
        return None

    @classmethod
    def normalize(cls, value):
        """標準化輸出：將各種幣別寫法轉為標準三碼。若無法識別或為空則回傳原值。"""
        if pd.isna(value) or str(value).strip() == '' or str(value).upper() == 'NONE':
            return value
            
        try:
            curr = cls(value)
            return curr.code if curr else value
        except (ValueError, TypeError):
            return value

class CardNetwork(Enum):
    VISA = 'VISA'
    MASTERCARD = 'MASTERCARD'
    JCB = 'JCB'
    AMEX = 'AMEX'
    UNIONPAY = 'UNIONPAY'
    DISCOVER = 'DISCOVER'
    OTHER = 'OTHER'

    @property
    def label(self):
        return self.value

class SmartCardType(Enum):
    EASY_CARD = ('EasyCard','悠遊卡')
    I_PASS = ('iPASS','一卡通')
    ICASH = ('iCash','愛金卡')
    NONE = ('NONE','無')

    @property
    def code(self):
        return self.value[0]
    
    @property
    def smartcard_name(self):
        return self.value[1]

class VPCType(Enum):
    CARD = ('CARD','實體卡')
    APPLE_PAY = ('ApplePay','Apple Pay')
    GOOGLE_PAY = ('GooglePay','Google Pay')
    SAMSUNG_PAY = ('SamsungPay','Samsung Pay')
    HAMI_PAY = ('HamiPay','HamiPay虛擬卡')
    TQ_PAY = ('台灣行動支付感應','台灣行動支付感應')
    
    @property
    def code(self):
        return self.value[0]
    
    @property
    def vpc_name(self):
        return self.value[1]

import functools

@functools.lru_cache(maxsize=32)
def get_all_banks() -> list:
    """從 dim_banks.yaml 動態載入全量銀行清單 (帶 LRU 快取)"""
    try:
        from profiles.loaders.config_loader import ConfigLoader
        data = ConfigLoader.load_yaml("dim_banks")
        return data.get('banks', []) if isinstance(data, dict) else []
    except Exception:
        return []

def clear_bank_cache():
    """清除銀行清單快取 (當設定檔有變更時呼叫)"""
    get_all_banks.cache_clear()
def get_bank_by_keyword(keyword: str) -> Optional[dict]:
    """取代原 Bank.from_keyword()，依關鍵字搜尋對應銀行字典"""
    if not keyword:
        return None
    kw_upper = keyword.upper()
    for bank in get_all_banks():
        for k in bank.get('keywords', []):
            if k.upper() in kw_upper:
                return bank
    return None


class RewardType(Enum):
    # 格式: (reward_unit_name, conversion_rate, rounding_strategy, rounding_digits)
    CASHBACK_FLOOR = ('cashback', 1, 'floor', 0)     # 1 cashback = 1 TWD
    CASHBACK_ROUND = ('cashback', 1, 'round', 0)     # 1 cashback = 1 TWD
    TREEPOINTS = ('tree_points', 1, 'round', 0)      # 1 tree point = 1 TWD
    ESUNPOINT_FLOOR = ('e_points', 1, 'floor', 0)    # 1 e-point = 1 TWD
    ESUNPOINT_ROUND = ('e_points', 1, 'round', 0)    # 1 e-point = 1 TWD
    OPENPOINT = ('openpoint', 1, 'round', 2)         # 1 openpoint = 1 TWD, 但允許小數點後兩位
    LINEPOINT = ('line_points', 1, 'round', 0)       # 1 line point = 1 TWD
    HAMIPOINT = ('hami_points', 1, 'round', 0)       # 1 hami point = 1 TWD

    @property
    def reward_unit_name(self):
        return self.value[0]
    
    @property
    def conversion_rate(self):  
        return self.value[1]

    @property
    def rounding_strategy(self):
        return self.value[2]
    
    @property
    def rounding_digits(self):
        return self.value[3]

    @classmethod
    def to_records(cls):
        """
        動態產生所有回饋類型的配置列表 (List of Dicts)。
        非常適合直接轉為 DataFrame 並寫入資料庫做為維度表 (dim_reward_types)。
        """
        return [
            {
                'reward_type_name': member.name,
                'reward_unit_name': member.reward_unit_name,
                'conversion_rate': member.conversion_rate,
                'rounding_strategy': member.rounding_strategy,
                'rounding_digits': member.rounding_digits
            }
            for member in cls
        ]

    @classmethod
    def get_lookup_map(cls):
        """
        動態產生 lookup dictionary，方便在計算引擎中直接透過字串名稱查找對應設定。
        格式：{'CASHBACK_FLOOR': {'reward_unit_name': 'cashback', ...}, ...}
        """
        return {
            member.name: {
                'reward_unit_name': member.reward_unit_name,
                'conversion_rate': member.conversion_rate,
                'rounding_strategy': member.rounding_strategy,
                'rounding_digits': member.rounding_digits
            } 
            for member in cls
        }

class TimeWindow(Enum):
    LAST_MONTH = (30, '近一個月', '30d', '30d_')
    LAST_QUARTER = (90, '近一季', '90d', '90d_')
    LAST_HALF_YEAR = (180, '近半年', '180d', '180d_')
    LAST_YEAR = (365, '近一年', '365d', '365d_')
    LAST_2_YEARS = (730, '近兩年', '730d', '730d_')
    THIS_YEAR = ('THIS_YEAR', '今年', 'this_year', 'this_year_')
    LAST_CALENDAR_YEAR = ('LAST_CALENDAR_YEAR', '去年(曆年)', 'prev_year', 'prev_year_')
    LIFETIME = (None, '全歷史', 'life', 'life_')

    @property
    def days(self) -> Optional[int]:
        val = self.value[0]
        return val if isinstance(val, int) else None

    @property
    def desc(self) -> str:
        return self.value[1]

    @property
    def key_suffix(self) -> str:
        return self.value[2]

    @property
    def prefix(self) -> str:
        return self.value[3]

    def get_date_range(self, anchor_date: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """
        根據基準日動態計算起始與結束日期 (YYYY-MM-DD, YYYY-MM-DD)。
        """
        base_dt = datetime.strptime(anchor_date, "%Y-%m-%d") if anchor_date else datetime.today()
        base_year = base_dt.year

        if self == TimeWindow.LIFETIME or self.value[0] is None:
            return None, None
        elif self == TimeWindow.THIS_YEAR or self.name == 'THIS_YEAR':
            # 今年：當年 1 月 1 日 ~ 基準日 (今天或最新交易日)
            start_date = f"{base_year}-01-01"
            end_date = anchor_date or base_dt.strftime("%Y-%m-%d")
            return start_date, end_date
        elif self == TimeWindow.LAST_CALENDAR_YEAR or self.name == 'LAST_CALENDAR_YEAR':
            # 去年 (曆年)：前一年 1 月 1 日 ~ 前一年 12 月 31 日
            start_date = f"{base_year - 1}-01-01"
            end_date = f"{base_year - 1}-12-31"
            return start_date, end_date
        elif isinstance(self.value[0], int):
            # 滾動天數 (30d, 90d, 180d, 365d, 730d)
            start_dt = base_dt - timedelta(days=self.value[0])
            end_date = anchor_date or base_dt.strftime("%Y-%m-%d")
            return start_dt.strftime("%Y-%m-%d"), end_date

        return None, None

    def get_start_date(self, anchor_date: Optional[str] = None) -> Optional[str]:
        """相容舊版：取得起始日期"""
        start, _ = self.get_date_range(anchor_date)
        return start

    @classmethod
    def resolve_range(cls, time_window_str: Optional[str], anchor_date: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """
        將任意前端傳入的時間視窗字串 (包含 THIS_YEAR, LAST_CALENDAR_YEAR, 1Y, 3M, 6M, 2Y, LAST_YEAR 等)
        解析為精確的 (start_date, end_date)
        """
        if not time_window_str or time_window_str.upper() in ('LIFETIME', 'ALL', '全歷史', '全時段', 'NONE'):
            return None, None

        tw = time_window_str.strip().upper()
        base_dt = datetime.strptime(anchor_date, "%Y-%m-%d") if anchor_date else datetime.today()
        base_year = base_dt.year
        end_anchor = anchor_date or base_dt.strftime("%Y-%m-%d")

        # 1. 曆年：今年
        if tw in ('THIS_YEAR', 'THIS_CALENDAR_YEAR', '今年', 'YTD'):
            return f"{base_year}-01-01", end_anchor

        # 2. 曆年：去年
        if tw in ('LAST_CALENDAR_YEAR', 'PREV_YEAR', 'PREVIOUS_YEAR', '去年', 'LAST_YEAR_CALENDAR'):
            return f"{base_year - 1}-01-01", f"{base_year - 1}-12-31"

        # 3. 滾動區間 (月份/天數代碼)
        rolling_map = {
            '1M': 30, 'LAST_MONTH': 30, '30D': 30,
            '3M': 90, 'LAST_QUARTER': 90, '90D': 90,
            '6M': 180, 'LAST_HALF_YEAR': 180, '180D': 180,
            '1Y': 365, 'LAST_YEAR': 365, '365D': 365,
            '2Y': 730, 'LAST_2_YEARS': 730, '730D': 730
        }

        if tw in rolling_map:
            days = rolling_map[tw]
            start_dt = base_dt - timedelta(days=days)
            return start_dt.strftime("%Y-%m-%d"), end_anchor

        # 4. 嘗試 Enum 名稱匹配
        if tw in cls.__members__:
            return cls[tw].get_date_range(anchor_date)

        return None, None

    @classmethod
    def to_list(cls) -> List[Dict[str, Any]]:
        """
        轉換為相容新系統分析模組 (rfm_modules / matrix) 的字典陣列格式 (僅包含有效天數之成員)。
        """
        return [
            {
                'days': member.days,
                'desc': member.desc,
                'suffix': member.key_suffix,
                'prefix': member.prefix
            }
            for member in cls if member.days is not None or member == cls.LIFETIME
        ]
        
    @classmethod
    def to_legacy_list(cls) -> List[Dict[str, Any]]:
        """
        轉換為相容舊系統分析模組 (rfm_modules) 的字典陣列格式。
        """
        return [
            {
                'days': member.days,
                'prefix': f"{member.key_suffix}_",
                'suffix': member.key_suffix,
                'desc': member.desc 
            }
            for member in cls if member.days is not None or member == cls.LIFETIME
        ]

# ==========================================
# 2. 交易資料欄位 (Transactions)
# ==========================================
# 這些是我們希望在最終 CSV 看到的標準欄位名稱

# 識別碼資訊
COL_TXN_ID = TransactionColumn.TXN_ID.col_name

# 交易日期資訊
COL_TXN_DATE = TransactionColumn.TXN_DATE.col_name
COL_POST_DATE = TransactionColumn.POST_DATE.col_name
COL_CONV_DATE = TransactionColumn.CONV_DATE.col_name
COL_STAT_MON = TransactionColumn.STAT_MON.col_name
COL_CLOSING_DATE = TransactionColumn.CLOSING_DATE.col_name
COL_ACT_CLOSING_DATE = TransactionColumn.ACT_CLOSING_DATE.col_name

# 商店消費資訊
COL_MERCHANT = TransactionColumn.MERCHANT.col_name
COL_MERCHANT_PATTERN = TransactionColumn.MERCHANT_PATTERN.col_name
COL_MERCHANT_DISPLAY = TransactionColumn.MERCHANT_DISPLAY.col_name
COL_NORMALIZED_MERCHANT = TransactionColumn.NORMALIZED_MERCHANT.col_name
COL_LOCATION = TransactionColumn.LOCATION.col_name
COL_CONSUMPTION_PLACE = TransactionColumn.CONSUMPTION_PLACE.col_name
COL_TXN_TYPE = TransactionColumn.TXN_TYPE.col_name
COL_CATEGORY = TransactionColumn.CATEGORY.col_name
COL_SUB_CATEGORY = TransactionColumn.SUB_CATEGORY.col_name
COL_PROCESS_PATTERN = TransactionColumn.PROCESS_PATTERN.col_name
COL_PAYMENT_PROCESS = TransactionColumn.PAYMENT_PROCESS.col_name
COL_EC_PLATFORM_PATTERN = TransactionColumn.EC_PLATFORM_PATTERN.col_name

# 消費金額資訊
COL_CURRENCY = TransactionColumn.CURRENCY.col_name
COL_AMOUNT = TransactionColumn.AMOUNT.col_name
COL_CURR_AMOUNT = TransactionColumn.CURR_AMOUNT.col_name
COL_PAY_AMOUNT = TransactionColumn.PAY_AMOUNT.col_name
COL_PAY_CURR = TransactionColumn.PAY_CURR.col_name

# 卡片資訊
COL_BANK_NAME = TransactionColumn.BANK_NAME.col_name
COL_BANK_NO = TransactionColumn.BANK_NO.col_name
COL_CARD_NO = TransactionColumn.CARD_NO.col_name
COL_CARD_TYPE = TransactionColumn.CARD_TYPE.col_name
COL_IS_DUAL_CURRENCY = TransactionColumn.IS_DUAL_CURRENCY.col_name
COL_FX_TYPE = TransactionColumn.FX_TYPE.col_name
COL_ACTIVE_STATUS = TransactionColumn.ACTIVE_STATUS.col_name
COL_ENABLE_REWARD_CALC = TransactionColumn.ENABLE_REWARD_CALC.col_name
COL_VPC_NO = TransactionColumn.VPC_NO.col_name
COL_VPC_TYPE = TransactionColumn.VPC_TYPE.col_name

COL_INS_PLN = TransactionColumn.INS_PLN.col_name
COL_PAYMENT_PROCESS = TransactionColumn.PAYMENT_PROCESS.col_name
COL_PROCESS_PREFIX = TransactionColumn.PROCESS_PREFIX.col_name
COL_EC_PLATFORM = TransactionColumn.EC_PLATFORM.col_name
COL_EC_PLATFORM_TYPE = TransactionColumn.EC_PLATFORM_TYPE.col_name
COL_EC_CATEGORY = TransactionColumn.EC_CATEGORY.col_name
COL_EC_SUB_CATEGORY = TransactionColumn.EC_SUB_CATEGORY.col_name


# ==========================================
# 3. 回饋規則欄位 (Rewards Configs)
# ==========================================
COL_REWARD_PROGRAM = TransactionColumn.REWARD_PROGRAM.col_name       # 紅利/回饋計畫名稱
COL_START_DATE = TransactionColumn.PROGRAM_START_DATE.col_name       # 適用起始日
COL_END_DATE = TransactionColumn.PROGRAM_END_DATE.col_name           # 適用結束日
COL_REWARD_TYPE = TransactionColumn.REWARD_TYPE.col_name             # 回饋類型 (現金回饋、紅利點數、里程數等)
COL_REWARD_RATE = TransactionColumn.REWARD_RATE.col_name             # 回饋比率 (如一般消費的 0.01、網購的 0.02)
COL_REWARD_CYCLE = TransactionColumn.REWARD_CYCLE.col_name           # 回饋計算週期 (如依帳單結帳週期、依消費日曆月、依消費日等)
COL_MERCHANT_RATE = TransactionColumn.MERCHANT_RATE.col_name         # 特約商家回饋率 (同一個權益項目中，特店A回饋比率 0.02，特店B回饋比率 0.03)
COL_CAP_AMOUNT = TransactionColumn.CAP_AMOUNT.col_name               # 回饋上限
COL_CALC_METHOD = TransactionColumn.CALC_METHOD.col_name             # 計算策略 (PER_ITEM / AGGREGATE)
COL_ROUND_STRATEGY = TransactionColumn.ROUND_STRATEGY.col_name       # 四捨五入策略 (如無條件捨去、無條件進位、四捨五入到整數、四捨五入到小數點後兩位等)
COL_CONDITION = TransactionColumn.CONDITION.col_name                 # 條件標籤 (或 Regex 規則)

# ==========================================
# 4-2. 統一型別定義表 (The Law / Schema)
# ==========================================
# 用於 BaseParser 或 Enforcer 統一強制轉型
# 格式: { 欄位名: '目標型別' }

# 動態從 TransactionColumn 提取資料型態映射
# 避免與上方定義手動重複維護，確保資料唯一性 (Single Source of Truth)
COLUMN_TYPES = {
    col.col_name: col.dtype 
    for col in TransactionColumn
}


# ==========================================
# 5. 統一路徑配置 (Paths)
# ==========================================


# 專案根目錄 (假設 const.py 就在根目錄)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Profile 設定與個人化目錄位址 (Phase 4.1 重構)
PROFILES_DIR = os.path.join(ROOT_DIR, 'profiles')

EXAMPLE_PROFILE_DIR = os.path.join(PROFILES_DIR, 'example_profile')

COMMON_PROFILE_DIR = os.path.join(PROFILES_DIR, 'common')
COMMON_CONFIG_DIR = os.path.join(COMMON_PROFILE_DIR, 'configs')
COMMON_DATA_DIR = os.path.join(COMMON_PROFILE_DIR, 'data')

ACTIVE_PROFILE_NAME = os.getenv('ACTIVE_PROFILE', 'user_main')
ACTIVE_PROFILE_DIR = os.path.join(PROFILES_DIR, ACTIVE_PROFILE_NAME)
PROFILE_CONFIG_DIR = os.path.join(ACTIVE_PROFILE_DIR, 'configs')
PROFILE_DATA_DIR = os.path.join(ACTIVE_PROFILE_DIR, 'data')
PROFILE_JSON_PATH = os.path.join(ACTIVE_PROFILE_DIR, 'profile.json')
BRIDGE_REWARD_POOLS_PATH = os.path.join(COMMON_CONFIG_DIR, 'bridge_reward_pools.json')
BRIDGE_REWARD_POOLS_CSV_PATH = os.path.join(COMMON_CONFIG_DIR, 'bridge_reward_pools.csv')
BRIDGE_REWARD_LINKED_LISTS_PATH = os.path.join(COMMON_CONFIG_DIR, 'bridge_reward_linked_lists.csv')

# 核心目錄 (指向 profiles/common/)
DATA_DIR = COMMON_DATA_DIR                         # 輸入區 (profiles/common/data)
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')       # 輸出區
REWARD_DOTNET_OUTPUT_DIR = os.path.join(OUTPUT_DIR, 'reward_dotnet', 'detail')  # C# 回饋報表輸出區
CONFIG_DIR = COMMON_CONFIG_DIR                     # 規則設定檔區 (profiles/common/configs)
DATABASE_DIR = os.path.join(ROOT_DIR, 'database')    # 資料庫區

# 資料庫路徑 (多資料庫獨立設計)
TRANSACTIONS_DB_PATH = os.path.join(DATABASE_DIR, 'TransactionsBills.db')
CONFIGS_DB_PATH = os.path.join(DATABASE_DIR, 'TransactionsConfigs.db')
ANALYSIS_DB_PATH = os.path.join(DATABASE_DIR, 'TransactionsAnalysis.db')
# 向後相容別名：指向主要交易資料庫，避免專案其他地方崩潰
DB_PATH = TRANSACTIONS_DB_PATH


# 確保輸出目錄與 Profile 目錄存在
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(REWARD_DOTNET_OUTPUT_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(COMMON_CONFIG_DIR, exist_ok=True)
os.makedirs(COMMON_DATA_DIR, exist_ok=True)
os.makedirs(PROFILE_CONFIG_DIR, exist_ok=True)
os.makedirs(PROFILE_DATA_DIR, exist_ok=True)

BANK_REWARDS_DB_MAP = {
    b['bank_id']: os.path.join(DATABASE_DIR, f"RewardsConfigs_{b['bank_id']}.db")
    for b in get_all_banks()
}
REWARDS_CONFIGS_MOCK_DB_PATH = os.path.join(DATABASE_DIR, 'RewardsConfigs_mock.db')
BANK_REWARDS_DB_MAP['mock'] = REWARDS_CONFIGS_MOCK_DB_PATH

# 資料庫 Backend 設定 (支援: postgres (預設) / sqlite)
DEFAULT_DB_BACKEND = os.getenv('DB_BACKEND', 'postgres')

def _check_is_in_docker() -> bool:
    if os.getenv('IS_IN_DOCKER', '').lower() in ('true', '1'):
        return True
    if os.path.exists('/.dockerenv'):
        return True
    try:
        if os.path.exists('/proc/1/cgroup'):
            with open('/proc/1/cgroup', 'rt') as f:
                content = f.read()
                if any(k in content for k in ('docker', 'kubepods', 'containerd')):
                    return True
    except Exception:
        pass
    return False

IS_IN_DOCKER = _check_is_in_docker()
_raw_pg_host = os.getenv('POSTGRES_HOST') or os.getenv('PG_HOST')
if _raw_pg_host:
    if IS_IN_DOCKER:
        PG_HOST = 'db' if _raw_pg_host in ('127.0.0.1', 'localhost') else _raw_pg_host
    else:
        PG_HOST = '127.0.0.1' if _raw_pg_host in ('localhost', 'db') else _raw_pg_host
else:
    PG_HOST = 'db' if IS_IN_DOCKER else '127.0.0.1'

PG_PORT     = int(os.getenv('POSTGRES_PORT', '5432'))
PG_USER     = os.getenv('POSTGRES_USER',     'postgres')
PG_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'postgres')
PG_DATABASE = os.getenv('POSTGRES_DB',       'credit_card_db')

# 確保輸出目錄與 Profile 目錄存在
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PROFILE_CONFIG_DIR, exist_ok=True)
os.makedirs(PROFILE_DATA_DIR, exist_ok=True)

# C# 回饋引擎服務對接配置
CSHARP_REWARDS_API_URL = os.getenv('CSHARP_REWARDS_API_URL', 'http://127.0.0.1:5000/api/run/rewards')
USE_CSHARP_REWARDS_ENGINE = os.getenv('USE_CSHARP_REWARDS_ENGINE', 'True').lower() in ('true', '1', 'yes')


