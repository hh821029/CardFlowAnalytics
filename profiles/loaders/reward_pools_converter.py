"""
reward_pools_converter.py
-------------------------
提供 CSV 與 JSON 格式的雙向自動轉換工具，方便以 Excel / CSV 編輯特店回饋池規則，
並自動編譯為 .NET / C# 引擎所需的 bridge_reward_pools.json。
純 Python 標準庫實作（零第三方套件相依，支援 UTF-8-SIG Excel 編碼）。

使用方式：
1. 編輯完 CSV 後，將 CSV 轉為 JSON：
   python -m profiles.loaders.reward_pools_converter --to-json (預設)

2. 將現有 JSON 轉為 CSV (備份/還原)：
   python -m profiles.loaders.reward_pools_converter --to-csv
"""

import os
import csv
import json
import argparse
from typing import Any, Dict, List

DEFAULT_CSV_PATH = os.path.join("profiles", "common", "configs", "bridge_reward_pools.csv")
DEFAULT_JSON_PATH = os.path.join("profiles", "common", "configs", "bridge_reward_pools.json")

# 定義支援陣列拆分的欄位（若有多個值可用逗號隔開，例如 "JP, KR, TH" 或 "統一超商, 全家"）
ARRAY_FIELDS = [
    "normalized_merchant", "merchant_display", "payment_process",
    "ec_platform", "vpc_type", "card_id", "card_type", "merchant_location"
]

# 保留的元資料欄位 (不作為比對條件)
META_COLS = {"merchant_reward_pools_id", "pool_name", "rule_type"}

# 數值型欄位
NUMERIC_FIELDS = {"merchant_rate", "min_single_transaction"}

def _parse_field_value(val: Any, is_array_field: bool = False):
    """解析欄位值：支援空值、NONE、單一字串與逗號分隔清單"""
    if val is None:
        return None
    
    val_str = str(val).strip()
    if val_str == "" or val_str.lower() == "nan":
        return None
    
    if is_array_field:
        parts = [p.strip() for p in val_str.split(",") if p.strip()]
        if len(parts) > 1:
            return parts
        elif len(parts) == 1:
            return parts[0]
        return None
    
    return val_str

def csv_to_json(csv_path: str = DEFAULT_CSV_PATH, json_path: str = DEFAULT_JSON_PATH):
    """讀取 CSV 表格並轉換輸出為結構化的 bridge_reward_pools.json"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"找不到 CSV 檔案：{csv_path}")

    pools_dict: Dict[str, Dict[str, Any]] = {}
    
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pool_id = (row.get("merchant_reward_pools_id") or "").strip()
            if not pool_id:
                continue
            
            if pool_id not in pools_dict:
                pools_dict[pool_id] = {
                    "merchant_reward_pools_id": pool_id,
                    "pool_name": (row.get("pool_name") or "").strip() or None,
                    "pass_rules": [],
                    "rules": []
                }
                
            rule_type = (row.get("rule_type") or "rule").strip().lower()
            
            # 建立 rule item：動態支援所有 CSV 中的非元資料欄位
            rule_item: Dict[str, Any] = {}
            for col, val in row.items():
                if col in META_COLS or not col:
                    continue
                
                is_array = col in ARRAY_FIELDS
                if col in NUMERIC_FIELDS:
                    if val and str(val).strip() != "":
                        try:
                            rule_item[col] = float(val)
                        except ValueError:
                            pass
                else:
                    parsed = _parse_field_value(val, is_array_field=is_array)
                    if parsed is not None:
                        rule_item[col] = parsed
                    
            # 根據 rule_type 歸類
            if rule_type in ["pass", "pass_rule", "pass_rules"]:
                pools_dict[pool_id]["pass_rules"].append(rule_item)
            else:
                pools_dict[pool_id]["rules"].append(rule_item)

    # 輸出為 List
    pools_list = list(pools_dict.values())
    
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pools_list, f, ensure_ascii=False, indent=4)
        
    print(f"✅ 成功將 CSV [{csv_path}] 轉換為 JSON [{json_path}] (共 {len(pools_list)} 個回饋池)")

def json_to_csv(json_path: str = DEFAULT_JSON_PATH, csv_path: str = DEFAULT_CSV_PATH):
    """將現有的 bridge_reward_pools.json 逆向扁平化為 CSV，供 Excel 編輯"""
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"找不到 JSON 檔案：{json_path}")
        
    with open(json_path, "r", encoding="utf-8") as f:
        pools_data = json.load(f)
        
    # 預設偏好的欄位順序（包含 merchant_location）
    preferred_cols = [
        "merchant_reward_pools_id", "pool_name", "rule_type",
        "normalized_merchant", "merchant_display", "merchant_location",
        "payment_process", "ec_platform", "vpc_type",
        "card_id", "card_type", "merchant_rate", "start_date", "end_date", "note"
    ]
    
    rows = []
    dynamic_cols = set(preferred_cols)
    
    for pool in pools_data:
        pool_id = pool.get("merchant_reward_pools_id", "")
        pool_name = pool.get("pool_name", "")
        
        # 處理 pass_rules
        for p_rule in pool.get("pass_rules", []):
            row_dict = _flatten_rule_row(pool_id, pool_name, "pass", p_rule)
            dynamic_cols.update(row_dict.keys())
            rows.append(row_dict)
            
        # 處理 rules
        for rule in pool.get("rules", []):
            row_dict = _flatten_rule_row(pool_id, pool_name, "rule", rule)
            dynamic_cols.update(row_dict.keys())
            rows.append(row_dict)
            
    # 合併欄位順序：偏好欄位排前面，其餘動態欄位排後面
    final_cols = [c for c in preferred_cols if c in dynamic_cols] + [c for c in dynamic_cols if c not in preferred_cols]
            
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=final_cols)
        writer.writeheader()
        for r in rows:
            full_row = {col: r.get(col, "") for col in final_cols}
            writer.writerow(full_row)
            
    print(f"✅ 成功將 JSON [{json_path}] 轉換為 CSV [{csv_path}] (共 {len(rows)} 條規則)")

def _flatten_rule_row(pool_id: str, pool_name: str, rule_type: str, rule: Dict[str, Any]) -> Dict[str, Any]:
    """將單一規則物件轉為單行字典，陣列轉為逗號分隔字串"""
    row: Dict[str, Any] = {
        "merchant_reward_pools_id": pool_id,
        "pool_name": pool_name or "",
        "rule_type": rule_type
    }
    
    for k, v in rule.items():
        if isinstance(v, list):
            row[k] = ", ".join(str(item) for item in v)
        elif v is not None:
            row[k] = v
        else:
            row[k] = ""
            
    return row

def main():
    parser = argparse.ArgumentParser(description="回饋池 (Reward Pools) CSV 與 JSON 轉換工具")
    parser.add_argument("--to-json", action="store_true", help="將 CSV 轉換為 JSON")
    parser.add_argument("--to-csv", action="store_true", help="將 JSON 轉換為 CSV")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="指定 CSV 路徑")
    parser.add_argument("--json", default=DEFAULT_JSON_PATH, help="指定 JSON 路徑")
    
    args = parser.parse_args()
    
    if args.to_csv:
        json_to_csv(args.json, args.csv)
    else:
        # 預設執行 csv to json
        csv_to_json(args.csv, args.json)

if __name__ == "__main__":
    main()
