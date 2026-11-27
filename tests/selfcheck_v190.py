#!/usr/bin/env python3
"""v1.9.0 成长中心验收：A–E 临时档案、API、导出与安全检查。"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

TEMP = Path(tempfile.mkdtemp(prefix="专注小蛙-v190-"))
os.environ["FOCUS_FROG_DATA_DIR"] = str(TEMP)
os.environ["FOCUS_FROG_IMPORT_LEGACY"] = "0"
os.environ["FOCUS_FROG_SESSION_TTL_SEC"] = "0"

from fixtures_v190 import build_fixture  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from app import growth  # noqa: E402
from app.server import app  # noqa: E402
from app.storage import StorageManager, storage  # noqa: E402

checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    if not cond:
        print(f"[FAIL] {name} {detail}")
    else:
        print(f"[OK] {name}")


def close(actual, expected, tolerance=0.002):
    return actual is not None and abs(float(actual) - float(expected)) <= tolerance


def main():
    fixture = build_fixture(TEMP)
    users = fixture["users"]
    client = TestClient(app)

    # 1. A 空状态
    a = client.get("/api/growth/diary", params={"user_id": users["A"]["user_id"]})
    ar = client.get("/api/growth/report", params={"user_id": users["A"]["user_id"], "range": "30d"})
    check("1 A 空状态", a.status_code == 200 and a.json()["has_data"] is False
          and ar.status_code == 200 and ar.json()["has_data"] is False,
          f"{a.status_code}/{ar.status_code}")
    check("1b A 缺失值不是 0", a.json()["summary"]["play_seconds"] is None
          and ar.json()["behavior"]["successful_jumps"] is None)

    # 2. B 历史汇总
    b_uid = users["B"]["user_id"]
    b = client.get("/api/growth/report", params={"user_id": b_uid, "range": "30d"}).json()
    check("2 B 30 天游戏汇总", b["usage"]["formal_game_count"] == 30
          and b["behavior"]["successful_jumps"] == 180
          and close(b["behavior"]["click_success_rate"], 0.75, 0.001),
          str(b["usage"]["formal_game_count"]))
    check("2b B 游戏积分与时长", b["behavior"]["score"] == 1836
          and close(b["usage"]["play_seconds"], 7560, 1), str(b["usage"]["play_seconds"]))

    # 3. 多用户隔离
    e_uid = users["E"]["user_id"]
    b_sid = b["sessions"][0]["session_id"]
    cross = client.get(f"/api/growth/sessions/{b_sid}", params={"user_id": e_uid})
    e = client.get("/api/growth/report", params={"user_id": e_uid, "range": "30d"}).json()
    check("3 多用户隔离", cross.status_code == 403 and e["usage"]["formal_game_count"] == 4,
          f"{cross.status_code}/{e['usage']['formal_game_count']}")

    # 4. 日期范围
    b7 = client.get("/api/growth/report", params={"user_id": b_uid, "range": "7d"}).json()
    today = date.today()
    custom = client.get("/api/growth/report", params={
        "user_id": b_uid, "range": "custom",
        "start": (today - timedelta(days=2)).isoformat(), "end": today.isoformat(),
    }).json()
    dates = [d["date"] for d in custom["daily"] if d["has_data"]]
    check("4 近 7 天与自定义筛选", b7["usage"]["formal_game_count"] == 7
          and len(dates) <= 3 and all((today - timedelta(days=2)).isoformat() <= x <= today.isoformat() for x in dates),
          f"7d={b7['usage']['formal_game_count']} custom={len(dates)}")

    # 5. 难度历史
    check("5 难度历史阶梯", b["difficulty"]["current_factor"] == 0.9
          and len(b["difficulty"]["points"]) == 3,
          str(b["difficulty"]))

    # 6. C 更换参考基线分段
    c = client.get("/api/growth/report", params={"user_id": users["C"]["user_id"], "range": "30d"}).json()
    segments = c["assessments"]["trend"]["segments"]
    check("6 C 参考基线分段", len(segments) == 2
          and segments[0]["count"] == 2 and segments[1]["count"] == 2
          and "长期参考基线变化" in segments[1]["segment_reason"],
          str([(x["count"], x["segment_reason"]) for x in segments]))

    # 7. 模拟/不兼容不比较
    d = client.get("/api/growth/report", params={"user_id": users["D"]["user_id"], "range": "30d"}).json()
    sim_items = [x for x in d["assessments"]["items"] if x["simulation"]]
    check("7 模拟评估不比较", len(sim_items) == 1 and sim_items[0]["comparable"] is False
          and sim_items[0]["comparison_reasons"],
          str(sim_items))

    # 7b. 设备/算法条件不同不能拼成同一段
    def fake_assessment(i, key, algorithm):
        return {
            "comparable": True, "condition_key": key, "condition_label": key,
            "date": "2026-11-%02d" % (10 + i), "assessment_id": "asm_test_%d" % i,
            "conditions": {"device_key": "dev-a" if i < 2 else "dev-b",
                           "algorithm_version": algorithm},
            "reference_score": 50 + i, "pre_map_score": 0.5, "click_success_rate": 0.8,
            "reaction_median": 0.8, "net_charge_median": 7.0, "valid_signal_ratio": 0.95,
        }
    segments = growth._assessment_segments([
        fake_assessment(0, "a", "algo-v1"),
        fake_assessment(1, "a", "algo-v1"),
        fake_assessment(2, "b", "algo-v2"),
    ])["segments"]
    check("7b 设备/算法不同分段", len(segments) == 2
          and segments[0]["count"] == 2 and segments[1]["count"] == 1
          and segments[1]["trend_available"] is False,
          str([(x["count"], x["conditions"]) for x in segments]))

    # 8. 缺失/低质量
    check("8 缺失与低质量处理", d["quality"]["sessions_low_quality"] == 1
          and d["quality"]["sessions_missing_rounds"] == 1
          and d["behavior"]["valid_signal_ratio"] is not None
          and close(d["behavior"]["valid_signal_ratio"], 0.52, 0.01),
          str(d["quality"]))
    check("8b 模拟/回放不进入正式列表", d["usage"]["formal_game_count"] == 2
          and d["usage"]["category_counts"]["replay"] == 1
          and d["usage"]["category_counts"]["simulation"] == 1)

    # 9. 点击成功率与反应时间
    check("9 点击成功率与反应中位数", close(b["behavior"]["click_success_rate"], 0.75, 0.001)
          and b["behavior"]["reaction_median"] is not None
          and b["behavior"]["reaction_count"] == 180,
          str(b["behavior"].get("reaction_median")))

    # 10. 未完成轮次不进入净蓄力
    sample = {"actions": {"rounds": [
        {"success": True, "eval_sec": 6.0, "reaction_sec": 0.8},
        {"success": False, "eval_sec": 8.0, "reaction_sec": None},
    ], "incomplete_round": {"entered": True, "eval_sec": 99.0}}}
    metrics = growth._report_metrics(sample)
    check("10 未完成轮次单列", metrics["incomplete_rounds"] == 1
          and close(metrics["net_charge_median"], 7.0, 0.001)
          and metrics["zone_entries"] == 3,
          str(metrics))

    # 11. 模拟数据不污染真实趋势
    check("11 真实/模拟趋势隔离", c["assessments"]["simulation_count"] == 0
          and d["assessments"]["simulation_count"] == 1
          and d["assessments"]["real_count"] == 0)

    # 12. Session 回收后读取
    detail = client.get(f"/api/growth/sessions/{b_sid}", params={
        "user_id": b_uid, "include_rounds": "true"}).json()
    check("12 SQLite 历史详情", detail["storage"] == "sqlite"
          and len(detail["rounds"]) == 8 and detail["played_sec"] is not None)

    # 13-15. 四种导出、中文路径、PDF/Excel
    exported = {}
    for fmt in ("json", "csv", "pdf", "xlsx"):
        response = client.get(f"/api/growth/export/{fmt}", params={"user_id": b_uid, "range": "30d"})
        exported[fmt] = response
        check(f"13 {fmt} 导出", response.status_code == 200 and len(response.content) > 100,
              f"{response.status_code}/{len(response.content)}")
    check("15 中文路径", "专注小蛙" in TEMP.name and all(
        "专注小蛙" in unquote(exported[fmt].headers.get("X-Report-Filename") or "") for fmt in exported
    ), str(TEMP))
    pdf = exported["pdf"]
    reader = PdfReader(io.BytesIO(pdf.content))
    text = "".join((p.extract_text() or "") for p in reader.pages)
    check("14 PDF 中文与多页", len(reader.pages) >= 2 and "小满" in text and "标准评估" in text,
          f"pages={len(reader.pages)}")
    wb = load_workbook(io.BytesIO(exported["xlsx"].content), read_only=True)
    check("14b Excel 分类工作表", "标准评估" in wb.sheetnames
          and "每日使用" in wb.sheetnames and "正式游戏" in wb.sheetnames
          and len(wb.sheetnames) >= 7, str(wb.sheetnames))
    report_files = list((TEMP / "reports").glob("专注小蛙_成长报告_*.pdf"))
    check("15b 报告默认保存 reports/", bool(report_files))

    # 16. 重启/重新打开
    reopened = StorageManager(TEMP)
    check("16 重启后仍可读", reopened.get_user(b_uid)["nickname"] == "小满"
          and len(reopened.list_sessions(b_uid, 100)) >= 30)

    # 17. 离线资源
    html = "\n".join((ROOT / "web" / n).read_text(encoding="utf-8")
                     for n in ("growth.html", "parent.html", "history.html"))
    check("17 无外部 CDN", "http://" not in html and "https://" not in html
          and "cdn" not in html.lower())

    # 18. 儿童页面无脑电分数
    child_html = (ROOT / "web" / "growth.html").read_text(encoding="utf-8")
    child_js = (ROOT / "web" / "assets" / "growth-diary.js").read_text(encoding="utf-8")
    check("18 儿童日记无脑电分数", "focus_mean" not in child_js
          and "focus_mean" not in child_html and "monitor" not in child_html
          and "不会展示脑电分数" in child_html)

    # 19. 开发者工作台入口/旧 API 仍存在
    paths = {r.path for r in app.routes}
    check("19 开发者工作台保留", "/api/dev/workbench" in paths and "/api/dev/current" in paths)

    # 20. Schema 4 与旧 health
    status = client.get("/api/storage/status")
    check("20 Schema 4 与基础接口", status.status_code == 200
          and status.json()["schema_version"] == 4)

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\nv1.9.0 selfcheck: {passed}/{total} passed")
    print(f"fixture: {TEMP}")
    if passed != total:
        raise SystemExit(1)
    print("ALL_OK")


if __name__ == "__main__":
    try:
        main()
    finally:
        # 保留失败现场供排查；成功也保留路径供截图/报告使用。
        pass
