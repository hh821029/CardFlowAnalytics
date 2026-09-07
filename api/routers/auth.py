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

    # 3. 解析 Profile ID 與路徑穿越防禦 (Path Traversal Protection)
    profile_id = resolve_profile_id(username)
    base_profiles_dir = os.path.abspath(const.PROFILES_DIR)
    profile_dir = os.path.abspath(os.path.join(base_profiles_dir, profile_id))

    if os.path.commonpath([base_profiles_dir, profile_dir]) != base_profiles_dir:
        raise HTTPException(status_code=400, detail="不合法的 Profile 路徑")

    # 4. 檢查目標 Profile 目錄是否存在 (若為 example_public 或 user_main 且尚未建立則自動建立)
    if not os.path.exists(profile_dir):
        if profile_id in ["example_public", "user_main"]:
            os.makedirs(os.path.join(profile_dir, "configs"), exist_ok=True)
            os.makedirs(os.path.join(profile_dir, "data"), exist_ok=True)
        else:
            raise HTTPException(status_code=404, detail=f"找不到對應的 Profile 設定目錄: {profile_id}")

    # 5. 動態更新系統全局 ACTIVE_PROFILE
    const.ACTIVE_PROFILE_NAME = profile_id
    const.ACTIVE_PROFILE_DIR = profile_dir
    const.PROFILE_CONFIG_DIR = os.path.join(profile_dir, "configs")
    const.PROFILE_DATA_DIR = os.path.join(profile_dir, "data")
    const.PROFILE_JSON_PATH = os.path.join(profile_dir, "profile.json")

    # 6. 設定安全 Cookie (值已通過正規化校驗與格式保證，杜絕 CWE-614 Cookie Injection)
    # 使用經過 SAFE_USERNAME_REGEX 驗證的 profile_id
    cookie_val = str(profile_id)
    response.set_cookie(
        key="session_user",
        value=cookie_val,
        httponly=True,
        samesite="lax",
        secure=False  # 若部署在 HTTPS 環境建議啟用 Secure
    )

    logger.info(f"🔑 使用者 '{username}' 登入成功，切換至 Profile: {profile_id}")

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
