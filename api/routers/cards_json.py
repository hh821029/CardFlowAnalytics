# api/routers/cards_json.py
"""
個人持卡對照表 JSON (bridge_user_cards.json) 可視化 CRUD API 路由器
支援原子安全寫入 (Atomic Write) 與自動 DB 同步
"""
import os
import json
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Body

import const
from profiles.profiles_api import run_config_card_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cards", tags=["User Cards JSON"])

def get_cards_json_path() -> str:
    """取得當前 active profile 的 bridge_user_cards.json 絕對路徑"""
    active_profile = getattr(const, 'ACTIVE_PROFILE_NAME', 'user_main')
    config_dir = os.path.join(const.PROFILES_DIR, active_profile, 'configs')
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'bridge_user_cards.json')

@router.get("/banks")
async def api_get_banks():
    """取得全量合法銀行清單 (自 dim_banks.yaml)"""
    banks = const.get_all_banks()
    return {"status": "ok", "banks": banks}

@router.get("/products")
async def api_get_card_products():
    """取得全量卡片產品定義 (自 dim_credit_card_products.csv)"""
    try:
        from profiles.loaders.config_loader import ConfigLoader
        df = ConfigLoader.load_config(base_name="dim_credit_card_products")
        if df.empty:
            return {"status": "ok", "products": []}
        df = df.fillna("")
        products = df.to_dict(orient="records")
        return {"status": "ok", "products": products}
    except Exception as e:
        logger.error(f"❌ 讀取卡片產品維度表失敗: {e}")
        raise HTTPException(status_code=500, detail=f"讀取卡片產品失敗: {e}")

@router.get("/json")
async def api_get_user_cards_json():
    """讀取當前 Profile 之下 bridge_user_cards.json 的卡片清單"""
    json_path = get_cards_json_path()
    if not os.path.exists(json_path):
        logger.info(f"ℹ️ 檔案不存在 ({json_path})，回傳空清單。")
        return {"status": "ok", "cards": [], "file_path": json_path}

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                # 若先前是單一物件，包裝為 List
                data = [data] if isinstance(data, dict) else []
            return {"status": "ok", "cards": data, "file_path": json_path}
    except Exception as e:
        logger.error(f"❌ 讀取 JSON 失敗 ({json_path}): {e}")
        raise HTTPException(status_code=500, detail=f"讀取卡片 JSON 失敗: {e}")

@router.post("/json")
async def api_save_user_cards_json(
    cards: Any = Body(...),
    sync_db: bool = Query(True, description="是否自動同步更新至資料庫")
):
    """
    更新整包卡片 JSON 檔案 (採用 Atomic Write 安全寫入)
    可自動觸發 DB 同步
    """
    if not isinstance(cards, list):
        raise HTTPException(status_code=400, detail="卡片資料格式錯誤，最外層必須為 JSON Array 陣列 [ ... ]")

    # 校驗銀行代碼 (bank_no)
    valid_banks = const.get_all_banks()
    if valid_banks:
        valid_bank_nos = {str(b.get("bank_no", "")).strip() for b in valid_banks if b.get("bank_no")}
        for c in cards:
            c_bank_no = str(c.get("bank_no", "")).strip()
            if not c_bank_no or c_bank_no not in valid_bank_nos:
                raise HTTPException(
                    status_code=400,
                    detail=f"不合法的銀行代碼: '{c_bank_no}'。銀行代碼必須為維度表 (dim_banks.yaml) 中定義的合法代碼。"
                )

    json_path = get_cards_json_path()
    tmp_path = f"{json_path}.tmp"

    try:
        # 1. 寫入臨時檔
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=4)

        # 2. 原子替換
        os.replace(tmp_path, json_path)
        logger.info(f"💾 成功原子寫入卡片 JSON ({json_path})，共 {len(cards)} 筆卡片產品。")

        # 3. 視參數選擇同步 DB
        db_synced = False
        if sync_db:
            try:
                run_config_card_sync()
                db_synced = True
                logger.info("✅ 已自動觸發 DB 卡片維度表同步。")
            except Exception as sync_err:
                logger.warning(f"⚠️ 卡片 JSON 儲存成功，但同步至 DB 時發生錯誤: {sync_err}")

        return {
            "status": "ok",
            "message": f"卡片設定已成功儲存！{' (已同步至資料庫)' if db_synced else ''}",
            "count": len(cards),
            "file_path": json_path,
            "db_synced": db_synced
        }

    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        logger.error(f"❌ 寫入卡片 JSON 失敗: {e}")
        raise HTTPException(status_code=500, detail=f"儲存卡片 JSON 失敗: {e}")
