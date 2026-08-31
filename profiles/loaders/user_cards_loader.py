# profiles/loaders/user_cards_loader.py
"""
用戶持卡 JSON (bridge_user_cards.json) 展開、載入與 VLOOKUP 檢索引擎模組

職責：
1. UserCardsLoader: 讀取並展平 bridge_user_cards.json 為 1D DataFrame 與 3NF DataFrames。
2. UserCardRelationalBuilder: 抽象化建構相容 3NF 的三張 DataFrames (products, histories, vpc_pay)。
3. UserCardVLookupEngine: 提供帶參數的精確 VLOOKUP 查詢服務，避免 ETL 階段的「資料膨脹」。
"""
import os
import json
import re
import logging
from typing import Optional, List, Dict, Any

import pandas as pd
import const

logger = logging.getLogger(__name__)


class UserCardRelationalBuilder:
    """
    專責解析 bridge_user_cards.json 並建構標準 3NF 關聯 DataFrames:
    - user_card_products: 卡片產品主檔
    - user_card_histories: 實體卡履歷
    - user_card_vpc_pay: 虛擬卡/行動支付綁定
    """
    def __init__(self, raw_json_data: List[Dict[str, Any]]):
        self.raw_data = raw_json_data or []

    def build_3nf_tables(self) -> Dict[str, pd.DataFrame]:
        prod_rows = []
        hist_rows = []
        vpc_rows = []

        hist_counter = 1
        vpc_counter = 1

        for card_prod in self.raw_data:
            c_id = str(card_prod.get('card_id', '')).strip()
            b_no = str(card_prod.get('bank_no', '')).strip()
            c_type = str(card_prod.get('card_type', '')).strip()

            prod_rows.append({
                'card_id': c_id,
                'bank_no': b_no,
                'card_type': c_type
            })

            histories = card_prod.get('card_history', [])
            for hist in histories:
                h_id = f"HIST_{hist_counter:04d}"
                hist_counter += 1

                c_no = str(hist.get('card_no', '')).strip()
                s_date = hist.get('card_start_date') or hist.get('start_date', None)
                e_date = hist.get('card_end_date') or hist.get('end_date', None)
                is_act = hist.get('is_active')
                if is_act is None:
                    is_act = (hist.get('status') == 'active') if not e_date else False

                hist_rows.append({
                    'history_id': h_id,
                    'card_id': c_id,
                    'bank_no': b_no,
                    'card_no': c_no,
                    'card_network': hist.get('card_network', 'VISA'),
                    'smart_card_type': hist.get('smart_card_type', 'NONE'),
                    'is_co_branded': bool(hist.get('is_co_branded', False)),
                    'is_dual_currency': bool(hist.get('is_dual_currency', False)),
                    'fx_type': hist.get('fx_type', None),
                    'card_start_date': s_date,
                    'card_end_date': e_date,
                    'is_active': is_act,
                    'is_enable_reward_calc': hist.get('is_enable_reward_calc', True),
                    'status': hist.get('status', 'active'),
                    'note': hist.get('note', '')
                })

                vpcs = hist.get('vpc_pay', [])
                for vpc in vpcs:
                    vpc_id = f"VPC_{vpc_counter:05d}"
                    vpc_counter += 1

                    vpc_rows.append({
                        'vpc_id': vpc_id,
                        'history_id': h_id,
                        'card_no': c_no,
                        'vpc_no': str(vpc.get('vpc_no', '')).strip() or c_no,
                        'vpc_type': vpc.get('vpc_type', 'CARD')
                    })

        df_prods = pd.DataFrame(prod_rows).drop_duplicates() if prod_rows else pd.DataFrame(columns=['card_id', 'bank_no', 'card_type'])
        df_hists = pd.DataFrame(hist_rows) if hist_rows else pd.DataFrame(columns=['history_id', 'card_id', 'bank_no', 'card_no', 'card_network', 'smart_card_type', 'is_co_branded', 'is_dual_currency', 'fx_type', 'card_start_date', 'card_end_date', 'is_active', 'is_enable_reward_calc', 'status', 'note'])
        df_vpcs = pd.DataFrame(vpc_rows) if vpc_rows else pd.DataFrame(columns=['vpc_id', 'history_id', 'card_no', 'vpc_no', 'vpc_type'])

        return {
            'user_card_products': df_prods,
            'user_card_histories': df_hists,
            'user_card_vpc_pay': df_vpcs
        }


class UserCardVLookupEngine:
    """
    [精確 VLOOKUP 檢索引擎]
    避免 ETL 處理階段因 1-to-N 關聯造成的「資料膨脹」。
    比對規則：
    1. current_vpc_type 為非空值：直接保持原 vpc_type，不重複查找。
    2. vpc_no 檢核：若 vpc_no 為 4 位數字字串 (r'^\d{4}$'):
       - 觸發 vpc_no VLOOKUP 比對，回傳相對應的 vpc_type, card_type, bank_no 等。
       - 若非 4 位數字字串或為空：不觸發 vpc_no 查找，不傳入 card_no，直接維持原狀/回傳 None。
    """
    def __init__(self, loader: Optional['UserCardsLoader'] = None, profile_name: Optional[str] = None):
        if loader:
            self.loader = loader
        else:
            self.loader = UserCardsLoader(profile_name=profile_name)

        self._vpc_map = {}      # key: vpc_no, value: row dict
        self._card_no_map = {}  # key: card_no, value: row dict
        self._build_index()

    def _build_index(self):
        """建立極速 Hash 索引"""
        df_flat = self.loader.to_flat_dataframe()
        if df_flat.empty:
            return

        for _, row in df_flat.iterrows():
            r_dict = row.to_dict()
            v_no = str(r_dict.get('vpc_no', '')).strip() if r_dict.get('vpc_no') is not None else ''
            c_no = str(r_dict.get('card_no', '')).strip() if r_dict.get('card_no') is not None else ''

            if v_no and re.match(r'^\d{4}$', v_no):
                self._vpc_map[v_no] = r_dict

            if c_no and re.match(r'^\d{4}$', c_no):
                if c_no not in self._card_no_map:
                    self._card_no_map[c_no] = r_dict

    def lookup_vpc(
        self,
        vpc_no: Optional[str] = None,
        card_no: Optional[str] = None,
        current_vpc_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        精確 VLOOKUP 檢索方法:
        - 條件 1: 若 current_vpc_type 已有有效非空值 -> 直接保留原 vpc_type，不重複查找
        - 條件 2: 檢查 vpc_no 是否為 4 位數字 str:
          - 若是: 觸發 vpc_no 查找，回傳匹配到的屬性
          - 若否/為空: 不觸發 vpc_no 查找，不傳入 card_no
        """
        # 1. 判斷 current_vpc_type 是否已有非空有效值
        if current_vpc_type is not None and not pd.isna(current_vpc_type):
            str_curr = current_vpc_type.strip()
            if str_curr and str_curr.lower() not in ('none', 'nan'):
                return {
                    'matched': True,
                    'match_source': 'existing_vpc_type',
                    'vpc_type': str_curr,
                    'card_type': None,
                    'bank_no': None,
                    'card_id': None
                }

        # 2. 檢核 vpc_no 是否為 4 位數字字串 (r'^\d{4}$')
        str_vpc = vpc_no.strip() if vpc_no is not None and not pd.isna(vpc_no) else ''
        is_4_digits = bool(re.match(r'^\d{4}$', str_vpc))

        if is_4_digits:
            # 觸發 vpc_no 查找
            if str_vpc in self._vpc_map:
                match_info = self._vpc_map[str_vpc]
                return {
                    'matched': True,
                    'match_source': 'vpc_no_lookup',
                    'vpc_no': str_vpc,
                    'vpc_type': match_info.get('vpc_type'),
                    'card_type': match_info.get('card_type'),
                    'bank_no': match_info.get('bank_no'),
                    'card_id': match_info.get('card_id'),
                    'card_network': match_info.get('card_network'),
                    'smart_card_type': match_info.get('smart_card_type')
                }

        # 若不符合 4 位數字或為空：不觸發 vpc_no 查找，不傳入 card_no
        return {
            'matched': False,
            'match_source': None,
            'vpc_type': None,
            'card_type': None,
            'bank_no': None,
            'card_id': None
        }

    def enrich_dataframe(
        self,
        df_transactions: pd.DataFrame,
        vpc_no_col: str = 'vpc_no',
        vpc_type_col: str = 'vpc_type',
        card_type_col: str = 'card_type',
        bank_no_col: str = 'bank_no'
    ) -> pd.DataFrame:
        """
        批量擴充交易 DataFrame，零膨脹 (保持 100% 原總筆數)
        """
        if df_transactions is None or df_transactions.empty:
            return df_transactions

        df_enriched = df_transactions.copy()
        
        vpc_types = []
        card_types = []
        bank_nos = []

        for _, row in df_enriched.iterrows():
            raw_v_no = row.get(vpc_no_col) if vpc_no_col in df_enriched.columns else None
            raw_v_type = row.get(vpc_type_col) if vpc_type_col in df_enriched.columns else None

            res = self.lookup_vpc(vpc_no=raw_v_no, current_vpc_type=raw_v_type)
            
            vpc_types.append(res.get('vpc_type') or raw_v_type)
            card_types.append(res.get('card_type') or row.get(card_type_col))
            bank_nos.append(res.get('bank_no') or row.get(bank_no_col))

        df_enriched[vpc_type_col] = vpc_types
        df_enriched[card_type_col] = card_types
        df_enriched[bank_no_col] = bank_nos

        return df_enriched


class UserCardsLoader:
    """
    用戶持卡載入器 (Facade 入口)
    整合 UserCardRelationalBuilder 與 UserCardVLookupEngine
    """
    def __init__(self, profile_name: Optional[str] = None):
        self.profile_name = profile_name or getattr(const, 'ACTIVE_PROFILE_NAME', 'user_main')
        self.json_path = self._resolve_json_path()

    def _resolve_json_path(self) -> str:
        """取得目標 Profile 之下 bridge_user_cards.json 絕對路徑 (支援 bridge_user_cards.json 與 bridge_user_cards_mock.json)"""
        config_dir = os.path.join(const.PROFILES_DIR, self.profile_name, 'configs')
        p_std = os.path.join(config_dir, 'bridge_user_cards.json')
        if os.path.exists(p_std):
            return p_std
        p_mock = os.path.join(config_dir, 'bridge_user_cards_mock.json')
        if os.path.exists(p_mock):
            return p_mock
        return p_std

    def load_json(self) -> List[Dict[str, Any]]:
        """讀取 bridge_user_cards.json 原始串列"""
        if not os.path.exists(self.json_path):
            logger.info(f"ℹ️ 持卡 JSON 檔案不存在 ({self.json_path})，回傳空串列。")
            return []

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data = [data]
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"❌ 讀取持卡 JSON 失敗 ({self.json_path}): {e}")
            return []

    def to_flat_dataframe(self) -> pd.DataFrame:
        """
        將 JSON 展開為一維 (1D) 扁平 DataFrame。
        每一列 (Row) 代表一個 (card_product + history + vpc_pay) 的比對組合。
        """
        raw_data = self.load_json()
        if not raw_data:
            return pd.DataFrame(columns=[
                'card_id', 'bank_no', 'card_type', 'card_no', 'card_network',
                'smart_card_type', 'is_co_branded', 'is_dual_currency', 'fx_type',
                'card_start_date', 'card_end_date', 'is_active', 'is_enable_reward_calc',
                'status', 'note', 'vpc_no', 'vpc_type'
            ])

        rows = []
        for card_prod in raw_data:
            c_id = str(card_prod.get('card_id', '')).strip()
            b_no = str(card_prod.get('bank_no', '')).strip()
            c_type = str(card_prod.get('card_type', '')).strip()
            histories = card_prod.get('card_history', [])

            if not histories:
                rows.append({
                    'card_id': c_id,
                    'bank_no': b_no,
                    'card_type': c_type,
                    'card_no': None,
                    'card_network': None,
                    'smart_card_type': None,
                    'is_co_branded': False,
                    'is_dual_currency': False,
                    'fx_type': None,
                    'card_start_date': None,
                    'card_end_date': None,
                    'is_active': True,
                    'is_enable_reward_calc': True,
                    'status': 'active',
                    'note': None,
                    'vpc_no': None,
                    'vpc_type': 'CARD'
                })
            else:
                for hist in histories:
                    c_no = str(hist.get('card_no', '')).strip() or None
                    c_net = hist.get('card_network', 'VISA')
                    s_type = hist.get('smart_card_type', 'NONE')
                    co_brand = bool(hist.get('is_co_branded', False))
                    dual_curr = bool(hist.get('is_dual_currency', False))
                    fx_t = hist.get('fx_type', None)
                    s_date = hist.get('card_start_date') or hist.get('start_date', None)
                    e_date = hist.get('card_end_date') or hist.get('end_date', None)
                    is_act = hist.get('is_active')
                    if is_act is None:
                        is_act = (hist.get('status') == 'active') if not e_date else False
                    enable_rew = hist.get('is_enable_reward_calc', True)
                    status = hist.get('status', 'active')
                    note = hist.get('note', '')
                    vpcs = hist.get('vpc_pay', [])

                    if not vpcs:
                        rows.append({
                            'card_id': c_id,
                            'bank_no': b_no,
                            'card_type': c_type,
                            'card_no': c_no,
                            'card_network': c_net,
                            'smart_card_type': s_type,
                            'is_co_branded': co_brand,
                            'is_dual_currency': dual_curr,
                            'fx_type': fx_t,
                            'card_start_date': s_date,
                            'card_end_date': e_date,
                            'is_active': is_act,
                            'is_enable_reward_calc': enable_rew,
                            'status': status,
                            'note': note,
                            'vpc_no': c_no,
                            'vpc_type': 'CARD'
                        })
                    else:
                        for vpc in vpcs:
                            v_no = str(vpc.get('vpc_no', '')).strip() or c_no
                            v_type = vpc.get('vpc_type', 'CARD')
                            rows.append({
                                'card_id': c_id,
                                'bank_no': b_no,
                                'card_type': c_type,
                                'card_no': c_no,
                                'card_network': c_net,
                                'smart_card_type': s_type,
                                'is_co_branded': co_brand,
                                'is_dual_currency': dual_curr,
                                'fx_type': fx_t,
                                'card_start_date': s_date,
                                'card_end_date': e_date,
                                'is_active': is_act,
                                'is_enable_reward_calc': enable_rew,
                                'status': status,
                                'note': note,
                                'vpc_no': v_no,
                                'vpc_type': v_type
                            })

        return pd.DataFrame(rows)

    def to_relational_tables(self) -> Dict[str, pd.DataFrame]:
        """
        委派 UserCardRelationalBuilder 將 JSON 展開為相容 3NF 的三張關聯 DataFrames
        """
        raw_data = self.load_json()
        builder = UserCardRelationalBuilder(raw_data)
        return builder.build_3nf_tables()

    def create_vlookup_engine(self) -> UserCardVLookupEngine:
        """建立極速 VLOOKUP 檢索引擎」"""
        return UserCardVLookupEngine(loader=self)

    def export_to_csv(self, output_path: Optional[str] = None) -> str:
        """
        將展平後的 1D 扁平對照表匯出為 CSV (預設輸出至 output/bridge_user_cards.csv)
        遵循 GEMINI.md 規範：檢驗用的暫存檔統一輸出至 output/ 目錄。
        """
        df_flat = self.to_flat_dataframe()
        if output_path is None:
            output_path = os.path.join(const.OUTPUT_DIR, 'bridge_user_cards.csv')

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df_flat.to_csv(output_path, index=False, encoding='utf-8-sig')
        logger.info(f"✅ 成功將展平持卡資料匯出至 CSV: {output_path} (共 {len(df_flat)} 筆)")
        return output_path
