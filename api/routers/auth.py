# api/routers/auth.py
"""
Profile 身份驗證與 active profile 切換路由器模組
支援將輸入帳號 (如 'example_public') 連動至 profiles/example_public/ 設定目錄
"""
import os
import re
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Response, Request, Body

import const

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# 限制使用者名稱/Profile 名稱僅允許英數字與底線，長度 1~32 字元，阻絕路徑穿越與 Cookie 注入 (CWE-614 / CWE-22)
SAFE_USERNAME_REGEX = re.compile(r'^[a-zA-Z0-9_]{1,32}$')

def resolve_profile_id(username: str) -> str:
    """將輸入帳號轉換為對應的 profile 資料夾名稱 (例如 example_public -> example_public, main -> user_main)"""
    username = username.strip()
    if username in ["example_public", "public"]:
        return "example_public"
    if username.startswith("user_"):
        return username
    if username == "main":
        return "user_main"
    return f"user_{username}"

def resolve_auth_user_key(username: str) -> str:
    """
    依系統安全性規範：傳入帳號比對 HASH 時，帳號一律補綴 'user_' 前綴。
    例如輸入帳號為 'userid' 時，比對 HASH 用的識別帳號鍵值為 'user_userid'。
    """
    username = username.strip()
    if username.startswith("user_"):
        return username
    return f"user_{username}"

@router.post("/login")
async def api_login(response: Response, payload: dict = Body(...)):
    """
    登入驗證 API
    帳號如帶入 'example_public'，會驗證並切換至 profiles/example_public/ 目錄
    比對 Hash 時統一使用 resolve_auth_user_key 轉換為 'user_<userid>'
    """
    raw_username = payload.get("username", "")
    if not isinstance(raw_username, str):
        raise HTTPException(status_code=400, detail="無效的使用者帳號格式")
    
    username = raw_username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="請提供使用者帳號 (如: example_public)")

    # 1. 嚴格格式校驗：防止 Cookie 注入與非法字元污染
    if not SAFE_USERNAME_REGEX.match(username):
        raise HTTPException(status_code=400, detail="使用者名稱格式不符規範 (僅允許 1~32 字元之英數字與底線)")

    # 2. Hash 驗證帳號鍵值規範 (user_<userid>)
    auth_user_key = resolve_auth_user_key(username)

    # 3. 解析 Profile ID 與路徑白名單安全映射 (CWE-22 / CWE-73 Path Traversal Defense)
    profile_id = resolve_profile_id(username)
    base_profiles_dir = os.path.abspath(const.PROFILES_DIR)

    # 採用白名單與已知合法 Profile 映射，阻絕未受信任輸入進入檔案系統 API (Sink)
    if profile_id == "example_public":
        safe_profile_id = "example_public"
        safe_profile_dir = os.path.join(base_profiles_dir, "example_public")
    elif profile_id == "user_main":
        safe_profile_id = "user_main"
        safe_profile_dir = os.path.join(base_profiles_dir, "user_main")
    else:
        # 動態掃描 profiles/ 目錄下實際存在的子目錄，構建受信任的白名單映射字典
        existing_profiles = {
            entry: os.path.join(base_profiles_dir, entry)
            for entry in os.listdir(base_profiles_dir)
            if os.path.isdir(os.path.join(base_profiles_dir, entry)) and not entry.startswith((".", "_"))
        }
        if profile_id not in existing_profiles:
            raise HTTPException(status_code=404, detail=f"找不到對應的 Profile 設定目錄: {profile_id}")
        safe_profile_id = profile_id
        safe_profile_dir = existing_profiles[profile_id]

    # 4. 僅允許內建展示帳號 (example_public / user_main) 於首次登入時自動初始化目錄
    if not os.path.exists(safe_profile_dir):
        if safe_profile_id in ["example_public", "user_main"]:
            os.makedirs(os.path.join(safe_profile_dir, "configs"), exist_ok=True)
            os.makedirs(os.path.join(safe_profile_dir, "data"), exist_ok=True)
        else:
            raise HTTPException(status_code=404, detail=f"找不到對應的 Profile 設定目錄: {safe_profile_id}")

    # 5. 動態更新系統全局 ACTIVE_PROFILE (使用已驗證之安全變數)
    const.ACTIVE_PROFILE_NAME = safe_profile_id
    const.ACTIVE_PROFILE_DIR = safe_profile_dir
    const.PROFILE_CONFIG_DIR = os.path.join(safe_profile_dir, "configs")
    const.PROFILE_DATA_DIR = os.path.join(safe_profile_dir, "data")
    const.PROFILE_JSON_PATH = os.path.join(safe_profile_dir, "profile.json")

    # 6. 設定安全 Cookie (使用經過白名單校驗的 safe_profile_id，徹底杜絕 CWE-614 污點流)
    cookie_val = str(safe_profile_id)
    response.set_cookie(
        key="session_user",
        value=cookie_val,
        httponly=True,
        samesite="lax",
        secure=False  # 若部署在 HTTPS 環境建議啟用 Secure
    )

    logger.info(f"🔑 使用者 '{username}' 登入成功，切換至 Profile: {safe_profile_id}")

    return {
        "status": "ok",
        "message": f"登入成功！已切換至 Profile: {profile_id}",
        "username": username,
        "profile_id": profile_id
    }

@router.get("/status")
async def api_auth_status(request: Request):
    """取得當前登入狀態與 Active Profile"""
    session_user = request.cookies.get("session_user") or getattr(const, 'ACTIVE_PROFILE_NAME', 'example_public')
    active_profile = getattr(const, 'ACTIVE_PROFILE_NAME', 'example_public')
    
    return {
        "logged_in": True if session_user else False,
        "username": session_user,
        "active_profile": active_profile,
        "profile_config_dir": getattr(const, 'PROFILE_CONFIG_DIR', '')
    }

@router.post("/logout")
async def api_logout(response: Response):
    """登出並清除 Session Cookie"""
    response.delete_cookie(key="session_user")
    return {"status": "ok", "message": "已成功登出"}
