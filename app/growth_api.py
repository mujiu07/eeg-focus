"""v1.9.0 个人成长中心 API。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query, Response

from . import growth, growth_export
from .export import content_disposition
from .storage import StorageError, storage

router = APIRouter(prefix="/api/growth", tags=["growth"])

ALLOWED_FORMATS = ("pdf", "xlsx", "json", "csv")


def _uid(user_id: Optional[str], x_user_id: Optional[str]) -> str:
    uid = (user_id or x_user_id or "").strip()
    if not uid:
        raise HTTPException(400, "必须指定 user_id")
    try:
        user = storage.get_user(uid)
    except StorageError as exc:
        raise HTTPException(400, str(exc))
    if not user:
        raise HTTPException(404, "个人档案不存在")
    return uid


def _range(preset: Optional[str], start: Optional[str], end: Optional[str],
           tz_offset_min: Optional[int]):
    try:
        return growth.resolve_range(preset, start, end, tz_offset_min)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/diary")
def diary(user_id: Optional[str] = Query(None),
          tz_offset_min: Optional[int] = Query(None),
          x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _uid(user_id, x_user_id)
    try:
        return growth.build_diary(uid, tz_offset_min)
    except StorageError as exc:
        raise HTTPException(404, str(exc))


@router.get("/report")
def report(range: str = Query("7d"), start: Optional[str] = Query(None),
           end: Optional[str] = Query(None), user_id: Optional[str] = Query(None),
           tz_offset_min: Optional[int] = Query(None),
           x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _uid(user_id, x_user_id)
    date_range = _range(range, start, end, tz_offset_min)
    try:
        data = growth.build_report(uid, date_range)
    except StorageError as exc:
        raise HTTPException(404, str(exc))
    return data


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, include_rounds: bool = Query(False),
                   user_id: Optional[str] = Query(None),
                   tz_offset_min: Optional[int] = Query(None),
                   x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _uid(user_id, x_user_id)
    try:
        return growth.build_session_detail(uid, session_id, include_rounds, tz_offset_min)
    except StorageError as exc:
        message = str(exc)
        status = 403 if "无权" in message else 404
        raise HTTPException(status, message)


@router.get("/export/{fmt}")
def export_report(fmt: str, range: str = Query("7d"), start: Optional[str] = Query(None),
                  end: Optional[str] = Query(None), user_id: Optional[str] = Query(None),
                  tz_offset_min: Optional[int] = Query(None),
                  x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _uid(user_id, x_user_id)
    fmt = str(fmt or "").lower()
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(400, "导出格式只支持 pdf、xlsx、json、csv")
    date_range = _range(range, start, end, tz_offset_min)
    try:
        data = growth.build_report(uid, date_range)
        if not data.get("has_data"):
            raise HTTPException(409, "所选日期范围内没有可导出的记录")
        payload = growth_export.build_export(data, fmt)
        if not payload:
            raise HTTPException(500, "导出结果为空，未生成文件")
        meta = growth.export_metadata(data, fmt)
        reports_dir = Path(storage.reports_dir)
        reports_dir.mkdir(parents=True, exist_ok=True)
        target = reports_dir / meta["filename"]
        if target.exists():
            stem, suffix = os.path.splitext(meta["filename"])
            target = reports_dir / f"{stem}_{int(__import__('time').time())}{suffix}"
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if not tmp.exists() or tmp.stat().st_size <= 0:
            tmp.unlink(missing_ok=True)
            raise HTTPException(500, "导出文件写入失败")
        os.replace(tmp, target)
    except HTTPException:
        raise
    except growth_export.GrowthExportError as exc:
        raise HTTPException(500, str(exc))
    except StorageError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"导出失败：{exc}")
    relative = f"reports/{target.name}"
    headers = {
        "Content-Disposition": content_disposition(meta["filename"]),
        "X-Report-Filename": quote(meta["filename"], safe=""),
        "X-Report-Relative-Path": quote(relative, safe=""),
        "X-Report-Encrypted": "false",
        "Cache-Control": "no-store",
    }
    return Response(content=payload, media_type=meta["media_type"], headers=headers)
