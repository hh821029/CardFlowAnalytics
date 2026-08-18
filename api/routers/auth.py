# api/routers/auth.py
"""
Profile 身份驗證與 active profile 切換路由器模組
支援將輸入帳號 (如 'example_public') 連動至 profiles/example_public/ 設定目錄
"""
import os
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Response, Request, Body

import const

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

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

@router.post("/login")
async def api_login(response: Response, payload: dict = Body(...)):
    """
    登入驗證 API
    帳號如帶入 'example_public'，會驗證並切換至 profiles/example_public/ 目錄
    """
    username = payload.get("username", "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="請提供使用者帳號 (如: example_public)")

    profile_id = resolve_profile_id(username)
    profile_dir = os.path.join(const.PROFILES_DIR, profile_id)

    # 檢查目標 Profile 目錄是否存在 (若為 example_public 或 user_main 且尚未建立則自動建立)
    if not os.path.exists(profile_dir):
        if profile_id in ["example_public", "user_main"]:
            os.makedirs(os.path.join(profile_dir, "configs"), exist_ok=True)
            os.makedirs(os.path.join(profile_dir, "data"), exist_ok=True)
        else:
            raise HTTPException(status_code=404, detail=f"找不到對應的 Profile 設定目錄: {profile_id}")

    # 動態更新系統全局 ACTIVE_PROFILE
    const.ACTIVE_PROFILE_NAME = profile_id
    const.ACTIVE_PROFILE_DIR = profile_dir
    const.PROFILE_CONFIG_DIR = os.path.join(profile_dir, "configs")
    const.PROFILE_DATA_DIR = os.path.join(profile_dir, "data")
    const.PROFILE_JSON_PATH = os.path.join(profile_dir, "profile.json")

    # 設定 HTTP-Only Cookie 標記 Session 並確認目前登記的資料夾狀態
    response.set_cookie(key="session_user", value=profile_id, httponly=True, samesite="lax")

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
