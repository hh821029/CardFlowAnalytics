import os
import json
import pandas as pd
import yaml
import logging
from typing import Optional, Union, Dict, Any

import const
from database.loaders.schema_enforcer import SchemaEnforcer
from database.loaders.db_reader import DBReader

logger = logging.getLogger(__name__)

class ConfigLoader:
    """
    通用配置載入器 (Phase 4.1 重構)：
    1. 優先讀取 active profile (預設 user_main) 的 profile.json 設定檔
    2. 自動雙層疊加：`configs/` (Public 通用檔) + `profiles/<active>/configs/` (Personal 個人檔)
    3. 支援 Replace (個人檔優先取代) / Append (個人檔追加) 策略
    4. 移除 `_private.csv` 硬編碼檔名，同時提供向下相容 fallback 降級機制
    5. 編碼嘗試：UTF-8 -> Big5 -> cp950
    """

    @classmethod
    def get_active_profile(cls, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """讀取 Profile 設定檔 profile.json"""
        target_profile = profile_name or getattr(const, 'ACTIVE_PROFILE_NAME', 'user_main')
        profile_json_path = os.path.join(const.PROFILES_DIR, target_profile, 'profile.json')
        
        if os.path.exists(profile_json_path):
            try:
                with open(profile_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data
            except Exception as e:
                logger.warning(f"⚠️ 讀取 Profile JSON 失敗 ({profile_json_path}): {e}")
        
        # 預設相容 Profile 結構
        return {
            "profile_id": target_profile,
            "name": target_profile,
            "paths": {
                "configs_dir": os.path.join(const.PROFILES_DIR, target_profile, 'configs'),
                "data_dir": os.path.join(const.PROFILES_DIR, target_profile, 'data')
            }
        }

    @classmethod
    def get_profile_config_dir(cls, profile_name: Optional[str] = None) -> str:
        """取得 active profile 的 configs 資料夾路徑"""
        target_profile = profile_name or getattr(const, 'ACTIVE_PROFILE_NAME', 'user_main')
        return os.path.join(const.PROFILES_DIR, target_profile, 'configs')

    @staticmethod
    def _read_csv_with_encoding(file_path: str) -> pd.DataFrame:
        """依序嘗試編碼讀取 CSV"""
        encodings = ['utf-8', 'big5', 'cp950']
        for enc in encodings:
            try:
                df = pd.read_csv(file_path, encoding=enc, dtype=str)
                df.columns = df.columns.str.strip()
                logger.info(f"✅ 成功使用 {enc} 讀取: {os.path.basename(file_path)}")
                return df
            except (UnicodeDecodeError, LookupError):
                continue
            except Exception as e:
                logger.error(f"❌ 讀取 {file_path} 時發生非預期錯誤 ({enc}): {e}")
                break
        
        logger.error(f"❌ 無法識別 {file_path} 的編碼 (嘗試過 UTF-8, Big5, cp950)")
        return pd.DataFrame()

    @classmethod
    def load_config(
        cls, 
        config_dir: Optional[str] = None, 
        base_name: str = "", 
        strategy: str = 'append',
        profile_name: Optional[str] = None
    ) -> pd.DataFrame:
        """
        載入配置的主入口
        :param config_dir: 設定檔目錄 (預設使用 const.CONFIG_DIR)
        :param base_name: 基礎檔名 (不含副檔名，如 'dim_merchants')
        :param strategy: 'append' (合併) 或 'replace' (個人檔優先且取代)
        :param profile_name: 指定使用的 Profile 名稱 (預設為 const.ACTIVE_PROFILE_NAME)
        :return: 合併與型別執法後的 DataFrame
        """
        common_dir = getattr(const, 'COMMON_CONFIG_DIR', const.CONFIG_DIR)
        public_dir = config_dir if config_dir else common_dir
        personal_dir = cls.get_profile_config_dir(profile_name)

        # 淨化 base_name (如傳入帶有 _private 則自動剝離，以維護標準檔名一致性)
        clean_base = base_name.rsplit('_private', 1)[0] if base_name.endswith('_private') else base_name

        # 特殊處理：bridge_user_cards 優先從 bridge_user_cards.json 讀取並展平
        if clean_base == 'bridge_user_cards':
            try:
                from profiles.loaders.user_cards_loader import UserCardsLoader
                u_loader = UserCardsLoader(profile_name=profile_name)
                df_json = u_loader.to_flat_dataframe()
                if not df_json.empty:
                    logger.info(f"✅ 透過 UserCardsLoader 成功從 JSON 載入 bridge_user_cards，共 {len(df_json)} 筆")
                    return SchemaEnforcer.enforce(df_json)
            except Exception as e:
                logger.warning(f"⚠️ 嘗試從 JSON 載入 bridge_user_cards 失敗，降級嘗試 CSV: {e}")

        # 1. 尋找 Public 基礎檔 (按優先順序: profiles/common/configs -> root configs)
        public_file_candidates = [
            os.path.join(public_dir, f"{clean_base}.csv"),
            os.path.join(const.CONFIG_DIR, f"{clean_base}.csv")
        ]
        
        df_base = pd.DataFrame()
        for pub_file in public_file_candidates:
            if os.path.exists(pub_file):
                df_base = cls._read_csv_with_encoding(pub_file)
                break
        
        if df_base.empty:
            logger.debug(f"ℹ️ 公開基礎檔不存在: {clean_base}.csv")

        # 2. 尋找 Personal 個人檔 (按優先順序：Profile標準檔 -> Profile私有檔 -> Public私有檔)
        personal_file_candidates = [
            os.path.join(personal_dir, f"{clean_base}.csv"),
            os.path.join(personal_dir, f"{clean_base}_private.csv"),
            os.path.join(public_dir, f"{clean_base}_private.csv")
        ]
        
        df_personal = pd.DataFrame()
        for p_file in personal_file_candidates:
            if os.path.exists(p_file):
                logger.info(f"🔍 找到個人對應設定檔: {p_file}")
                df_personal = cls._read_csv_with_encoding(p_file)
                if not df_personal.empty:
                    break

        # 3. 執行疊加策略 (Strategy)
        df_result = pd.DataFrame()
        if strategy == 'replace':
            if not df_personal.empty:
                logger.info(f"🔄 套用 Replace 策略：選用個人設定檔取代通用檔 ({clean_base})")
                df_result = df_personal
            else:
                df_result = df_base
        else: # append
            if not df_base.empty and not df_personal.empty:
                logger.info(f"➕ 套用 Append 策略：合併通用檔與個人設定檔 ({clean_base})")
                df_result = pd.concat([df_base, df_personal], ignore_index=True)
            elif not df_personal.empty:
                df_result = df_personal
            else:
                df_result = df_base

        # 4. 執法修復 (Schema Enforcement)
        if not df_result.empty:
            df_result = SchemaEnforcer.enforce(df_result)

        return df_result

    @classmethod
    def load_yaml(
        cls, 
        base_name: str,
        config_dir: Optional[str] = None,
        profile_name: Optional[str] = None
    ) -> Union[Dict[str, Any], list]:
        """
        載入 YAML 格式的微型配置 (亦支援 Profile 雙層疊加/覆蓋)
        """
        public_dir = config_dir if config_dir else const.CONFIG_DIR
        personal_dir = cls.get_profile_config_dir(profile_name)
        clean_base = base_name.rsplit('.yaml', 1)[0].rsplit('.yml', 1)[0]

        # 尋找候選檔案 (優先 Profile，次選 Public)
        file_candidates = [
            os.path.join(personal_dir, f"{clean_base}.yaml"),
            os.path.join(personal_dir, f"{clean_base}.yml"),
            os.path.join(public_dir, f"{clean_base}.yaml"),
            os.path.join(public_dir, f"{clean_base}.yml")
        ]

        for filepath in file_candidates:
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                        logger.debug(f"✅ 成功載入 YAML 配置: {os.path.basename(filepath)}")
                        return data if data is not None else {}
                except Exception as e:
                    logger.error(f"❌ 讀取 YAML 配置失敗 ({filepath}): {e}")

        logger.warning(f"⚠️ 找不到對應的 YAML 配置檔: {clean_base}.yaml")
        return {}

    @classmethod
    def load_json(
        cls, 
        base_name: str,
        config_dir: Optional[str] = None,
        profile_name: Optional[str] = None
    ) -> Union[Dict[str, Any], list]:
        """
        載入 JSON 格式的配置檔 (支援 Profile 雙層疊加/覆蓋與多重編碼嘗試)
        """
        public_dir = config_dir if config_dir else const.CONFIG_DIR
        personal_dir = cls.get_profile_config_dir(profile_name)
        clean_base = base_name.rsplit('.json', 1)[0]

        # 尋找候選檔案 (優先 Personal Profile，次選 Public Common)
        file_candidates = [
            os.path.join(personal_dir, f"{clean_base}.json"),
            os.path.join(public_dir, f"{clean_base}.json")
        ]

        for filepath in file_candidates:
            if os.path.exists(filepath):
                encodings = ['utf-8', 'utf-8-sig', 'cp950', 'big5']
                for enc in encodings:
                    try:
                        with open(filepath, 'r', encoding=enc) as f:
                            data = json.load(f)
                            logger.debug(f"✅ 成功使用 {enc} 載入 JSON 配置: {os.path.basename(filepath)}")
                            return data if data is not None else {}
                    except UnicodeDecodeError:
                        continue
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ JSON 格式解析錯誤 ({filepath}): {e}")
                        break
                    except Exception as e:
                        logger.warning(f"⚠️ 讀取 JSON 失敗 ({filepath}, {enc}): {e}")
                        break

        logger.debug(f"ℹ️ 找不到對應的 JSON 配置檔: {clean_base}.json")
        return {}

class ConfigFilter:
    """
    [設定與篩選條件載入器]
    負責讀取系統中可用於前端下拉選單或進階篩選的可分析維度 (銀行、卡片、第三方支付、國家地點、消費類別與次分類)
    """
    @classmethod
    def get_analyzable_data(cls, db_path: Optional[str] = None) -> dict:
        target_db_path = db_path or const.CONFIGS_DB_PATH
        logger.info(f"💾 開始讀取可分析資料欄位，資料庫路徑: {target_db_path}")
        
        result = {
            "banks": [],
            "cards": [],
            "payment_processes": [],
            "locations": [],
            "categories": [],
            "sub_categories": [],
            "category_sub_map": {}
        }
        
        try:
            # 1. 取得不重複的銀行名 (來自 dim_banks.yaml -> const.get_all_banks)
            try:
                result["banks"] = [
                    {"id": b.get("bank_id"), "name": b.get("bills_mapping_name", b.get("bank_name", ""))}
                    for b in const.get_all_banks()
                ]
                logger.info(f"🔍 讀取銀行名成功 (from const.get_all_banks)，共 {len(result['banks'])} 筆")
            except Exception as e:
                logger.warning(f"⚠️ 無法從 const.get_all_banks 讀取 bank_name: {e}")
                
            # 2. 取得不重複的卡片名 (優先從 PostgreSQL / SQLite 之 bridge_user_cards 表格讀取)
            try:
                df_cards = DBReader.read_sql("SELECT DISTINCT card_type FROM bridge_user_cards WHERE card_type IS NOT NULL AND card_type != ''", db_path=target_db_path)
                if df_cards.empty:
                    # 相容舊版檢視表 fallback
                    df_cards = DBReader.read_sql("SELECT DISTINCT card_type FROM dim_cards WHERE card_type IS NOT NULL AND card_type != ''", db_path=target_db_path)
                if not df_cards.empty and 'card_type' in df_cards.columns:
                    result["cards"] = [str(c) for c in df_cards['card_type'].tolist()]
                logger.info(f"🔍 讀取卡片名成功 (from bridge_user_cards)，共 {len(result['cards'])} 筆")
            except Exception as e:
                logger.warning(f"⚠️ 無法從 bridge_user_cards / dim_cards 讀取 card_type: {e}")
                
            # 3. 取得不重複的第三方支付 (priority < 25)
            try:
                df_pay = DBReader.read_sql("SELECT DISTINCT payment_process FROM dim_payment_process WHERE priority < 25 AND payment_process IS NOT NULL AND payment_process != '' ORDER BY priority", db_path=target_db_path)
                if not df_pay.empty and 'payment_process' in df_pay.columns:
                    result["payment_processes"] = [str(p) for p in df_pay['payment_process'].tolist()]
                logger.info(f"🔍 讀取第三方支付成功，共 {len(result['payment_processes'])} 筆")
            except Exception as e:
                logger.warning(f"⚠️ 無法從 dim_payment_process 讀取 payment_process: {e}")
                
            # 4. 取得國家代碼 (從 const.Location Enum)
            try:
                result["locations"] = [str(loc.alpha_2) for loc in const.Location]
                logger.info(f"🔍 讀取國家代碼成功，共 {len(result['locations'])} 筆")
            except Exception as e:
                logger.warning(f"⚠️ 無法從 const.Location 讀取 locations: {e}")
                
            # 5. 取得消費類別 (從 dim_merchants.csv)
            try:
                merchants_path = os.path.join(const.CONFIG_DIR, 'dim_merchants.csv')
                if os.path.exists(merchants_path):
                    m_df = pd.read_csv(merchants_path, dtype=str)
                    if 'category' in m_df.columns:
                        cats = m_df['category'].dropna().unique().tolist()
                        result["categories"] = sorted([str(c).strip() for c in cats if str(c).strip()])
                logger.info(f"🔍 讀取消費類別成功，共 {len(result['categories'])} 筆")
            except Exception as e:
                logger.warning(f"⚠️ 無法從 dim_merchants.csv 讀取 categories: {e}")
                
            # 6. 建立消費主類別與次類別的對應關係與次分類清單 (從 dim_merchants.csv)
            try:
                merchants_path = os.path.join(const.CONFIG_DIR, 'dim_merchants.csv')
                if os.path.exists(merchants_path):
                    m_df = pd.read_csv(merchants_path, dtype=str)
                    if 'category' in m_df.columns and 'sub_category' in m_df.columns:
                        m_df['category'] = m_df['category'].astype(str).str.strip()
                        m_df['sub_category'] = m_df['sub_category'].astype(str).str.strip()
                        
                        valid_df = m_df[
                            m_df['category'].notna() & (m_df['category'] != '') & (m_df['category'] != 'nan')
                        ]
                        
                        cat_sub_map = {}
                        all_sub_cats = set()
                        for _, row in valid_df.iterrows():
                            cat = str(row['category']).strip()
                            raw_sub = str(row['sub_category']).strip() if pd.notna(row['sub_category']) else ''
                            sub_cat = raw_sub if (raw_sub and raw_sub.lower() != 'nan') else '無次分類'
                            if cat not in cat_sub_map:
                                cat_sub_map[cat] = set()
                            cat_sub_map[cat].add(sub_cat)
                            all_sub_cats.add(sub_cat)
                        
                        def sort_sub_cats(sub_list):
                            subs = list(sub_list)
                            regular_subs = sorted([s for s in subs if s != '無次分類'])
                            if '無次分類' in subs:
                                regular_subs.append('無次分類')
                            return regular_subs

                        result["category_sub_map"] = {str(k): sort_sub_cats(v) for k, v in cat_sub_map.items()}
                        result["sub_categories"] = sort_sub_cats(all_sub_cats)
                logger.info(f"🔍 讀取消費主次分類對應關係成功，共 {len(result['category_sub_map'])} 組主分類，共 {len(result['sub_categories'])} 個次分類")
            except Exception as e:
                logger.warning(f"⚠️ 無法從 dim_merchants.csv 讀取主次分類對應關係: {e}")
                
        except Exception as e:
            logger.error(f"❌ 讀取可分析資料失敗: {e}", exc_info=True)
            raise e
            
        return result