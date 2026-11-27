"""本地档案、数据目录与备份 API（v1.8.1）。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .storage import AVATARS, AVATAR_LABELS, StorageError, storage

router = APIRouter(prefix="/api")


def _fail(exc: Exception, status: int = 400):
    raise HTTPException(status, str(exc))


class ProfileCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=20)
    avatar: str = "frog"


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=20)
    avatar: Optional[str] = None
    status: Optional[str] = None


class SyncBody(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    wallet: Optional[dict[str, Any]] = None
    owned: Optional[list[str]] = None
    outfits: Optional[dict[str, Any]] = None
    achievements: Optional[dict[str, Any]] = None
    idempotency_key: Optional[str] = None


class LegacyBody(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    wallet: Optional[dict[str, Any]] = None
    owned: Optional[list[str]] = None
    achievements: Optional[dict[str, Any]] = None
    calibration: Optional[dict[str, Any]] = None


class LocationBody(BaseModel):
    path: str = Field(min_length=1)
    confirm: bool = False
    migrate: bool = True


class RestoreBody(BaseModel):
    filename: str = Field(min_length=1)
    confirm: bool = False


@router.get("/storage/status")
def storage_status():
    status = storage.status()
    status["avatars"] = [{"id": a, "label": AVATAR_LABELS[a]} for a in AVATARS]
    status["profiles"] = storage.list_users() if status.get("ok") else []
    return status


@router.get("/storage/backups")
def storage_backups():
    return {"backups": storage.backups(), "data_dir": str(storage.root)}


@router.post("/storage/backup")
def storage_backup():
    try:
        return storage.backup("manual")
    except StorageError as exc:
        _fail(exc)


@router.post("/storage/restore")
def storage_restore(body: RestoreBody):
    try:
        return storage.restore(body.filename, body.confirm)
    except StorageError as exc:
        _fail(exc)


@router.post("/storage/open")
def storage_open():
    try:
        return storage.open_folder()
    except StorageError as exc:
        raise HTTPException(501, str(exc))


@router.post("/storage/location")
def storage_location(body: LocationBody):
    try:
        return storage.set_data_dir(body.path, confirm=body.confirm, migrate=body.migrate)
    except StorageError as exc:
        _fail(exc)


@router.get("/profiles")
def profiles():
    return {"profiles": storage.list_users(), "max": 12,
            "storage": storage.status()}


@router.post("/profiles")
def create_profile(body: ProfileCreate):
    try:
        user = storage.create_user(body.nickname, body.avatar)
        return {"ok": True, "profile": user}
    except StorageError as exc:
        _fail(exc)


@router.patch("/profiles/{user_id}")
def update_profile(user_id: str, body: ProfileUpdate):
    try:
        user = storage.update_user(user_id, body.nickname, body.avatar, body.status)
        return {"ok": True, "profile": user}
    except StorageError as exc:
        _fail(exc)


@router.delete("/profiles/{user_id}")
def delete_profile(user_id: str, confirm: bool = Query(False)):
    try:
        return storage.delete_user(user_id, confirm=confirm)
    except StorageError as exc:
        _fail(exc)


@router.post("/profiles/{user_id}/select")
def select_profile(user_id: str):
    try:
        user = storage.ensure_user(user_id)
        storage.touch_user(user_id)
        return {"ok": True, "profile": user}
    except StorageError as exc:
        _fail(exc)


@router.get("/profiles/{user_id}/bootstrap")
def bootstrap(user_id: str):
    try:
        return storage.bootstrap(user_id)
    except StorageError as exc:
        _fail(exc)


@router.post("/profiles/{user_id}/sync")
def sync_profile(user_id: str, body: SyncBody):
    try:
        return storage.sync_state(user_id, body.model_dump(exclude_none=True))
    except StorageError as exc:
        _fail(exc)


@router.post("/profiles/{user_id}/import-legacy")
def import_legacy(user_id: str, body: LegacyBody):
    try:
        return storage.import_browser_legacy(user_id, body.model_dump(exclude_none=True))
    except StorageError as exc:
        _fail(exc)


@router.get("/profiles/{user_id}/reports")
def profile_reports(user_id: str, limit: int = Query(20, ge=1, le=200)):
    try:
        storage.ensure_user(user_id)
        return {"reports": storage.list_sessions(user_id, limit)}
    except StorageError as exc:
        _fail(exc)
