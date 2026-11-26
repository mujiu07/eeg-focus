"""
训练报告导出
=============
把一局游戏结束后的报告（``outputs/sessions/<sid>.json``）导出成可直接分享的文件：

  - PDF  : reportlab，嵌入中文字体 + 专注曲线图，适合打印 / 发给家长
  - XLSX : openpyxl，报告概览 + 逐点曲线 + 起跳事件 + 折线图
  - DOCX : python-docx，概览表 + 给家长的话，适合二次编辑
  - CSV  : 逐点曲线（带 UTF-8 BOM，Excel 双击不乱码）
  - JSON : 原始报告，便于归档或程序处理

设计原则：
  1) 导出只依赖报告 JSON，不依赖前端页面状态，接口可以单独调用；
  2) 前端会把页面上「给家长的话」的纯文本一起 POST 过来，保证文件与屏幕一致；
     直接 GET 时后端用同一套规则生成精简摘要兜底；
  3) 中文 PDF 优先嵌入系统字体（Windows / macOS / Linux 常见路径），
     都找不到时退回 reportlab 内置的 STSong-Light CID 字体。
"""

from __future__ import annotations

import csv
import io
import os
import platform
import re
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

DISCLAIMER = (
    "以上内容由本局游戏数据自动生成，仅供家长了解训练情况，不构成医学诊断、"
    "心理评估或治疗建议。脑波分数会受设备佩戴、疲劳、环境等因素影响，"
    "不能代表孩子的注意力水平。"
)
REFERENCE = (
    "参考依据：WHO 5–17 岁身体活动建议、AASM 儿童睡眠建议、"
    "AAP 屏幕使用建议、DSM-5 注意缺陷多动障碍诊断要点。"
)

SOURCE_LABELS = {
    "replay": "脑电回放",
    "manual": "手动模拟",
    "hardware": "Xmuse 脑电",
    "heart": "心率",
}


class ExportUnavailable(RuntimeError):
    """缺少导出所需的第三方库。"""


# ---------------------------------------------------------------------------
# 报告取值与派生指标
# ---------------------------------------------------------------------------
def describe_source(source: Optional[dict]) -> str:
    source = source or {}
    name = str(source.get("name") or "")
    raw = str(source.get("file") or "").replace("\\", "/")
    filename = raw.rsplit("/", 1)[-1] if raw else ""
    if filename:
        match = re.match(r"^Subject(\d+)_([12])\.edf$", filename, re.I)
        if match:
            segment = "放松段" if match.group(2) == "1" else "心算段"
            return f"脑电回放 · 被试 {match.group(1)} · {segment}"
        return f"脑电回放 · {filename}"
    return SOURCE_LABELS.get(name, name or "未知信号")


def fmt_num(value: Any, digits: int = 0, suffix: str = "") -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.{digits}f}" if digits else f"{round(number)}"
    return text + suffix


def fmt_duration(seconds: Any) -> str:
    if seconds is None:
        return "—"
    try:
        total = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "—"
    if total < 60:
        return f"{total} 秒"
    minutes, rest = divmod(total, 60)
    return f"{minutes} 分 {rest} 秒" if rest else f"{minutes} 分钟"


def score_points(report: dict) -> list[tuple[float, float]]:
    """曲线统一成 (秒, 0–100 分)；旧报告没有 score 时退回 focus*100。"""
    points: list[tuple[float, float]] = []
    for item in report.get("curve") or []:
        if not isinstance(item, dict):
            continue
        score = item.get("score")
        if score is None:
            focus = item.get("focus_fused")
            if focus is None:
                focus = item.get("focus")
            score = float(focus) * 100 if focus is not None else None
        if score is None or item.get("t") is None:
            continue
        try:
            t = float(item["t"])
            s = max(0.0, min(100.0, float(score)))
        except (TypeError, ValueError):
            continue
        points.append((t, s))
    return points


def heart_points(report: dict) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for item in report.get("hr_curve") or []:
        if not isinstance(item, dict) or item.get("bpm") is None or item.get("t") is None:
            continue
        try:
            points.append((float(item["t"]), float(item["bpm"])))
        except (TypeError, ValueError):
            continue
    return points


def process_stats(points: Sequence[tuple[float, float]]) -> dict:
    """波动、前后半段趋势、最长掉线、自己拉回次数。与报告页口径一致。"""
    stats = {
        "n": 0, "mean": None, "sd": None, "trend": None,
        "recoveries": 0, "worst_sec": 0, "dt": 1.0,
    }
    if not points:
        return stats
    values = [v for _, v in points]
    n = len(values)
    stats["n"] = n
    mean = sum(values) / n
    stats["mean"] = mean
    if n >= 3:
        stats["sd"] = (sum((v - mean) ** 2 for v in values) / n) ** 0.5
    if n >= 6:
        half = n // 2
        stats["trend"] = sum(values[half:]) / len(values[half:]) - sum(values[:half]) / len(values[:half])
    recoveries = 0
    streak = 0
    worst = 0
    for value in values:
        if value < 50:
            streak += 1
            worst = max(worst, streak)
        else:
            if streak:
                recoveries += 1
            streak = 0
    stats["recoveries"] = recoveries
    times = [t for t, _ in points]
    dt = abs(times[-1] - times[0]) / (n - 1) if n > 1 else 1.0
    stats["dt"] = dt or 1.0
    stats["worst_sec"] = int(round(worst * (stats["dt"] or 1.0)))
    return stats


def valid_ratio(report: dict) -> Optional[int]:
    total = report.get("n_frames")
    valid = report.get("n_valid_frames")
    if not total or valid is None:
        return None
    try:
        return int(round(float(valid) / float(total) * 100))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def above_ratio(report: dict) -> Optional[int]:
    value = report.get("above_mid_ratio")
    if value is None:
        value = report.get("above_baseline_ratio")
    if value is None:
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def report_time(report: dict) -> str:
    raw = report.get("created_at")
    if not raw:
        return "—"
    try:
        return str(raw).replace("T", " ")
    except Exception:  # noqa: BLE001 - 显示用，不阻断导出
        return str(raw)


def overview_rows(report: dict) -> list[tuple[str, str]]:
    """报告概览：PDF / DOCX / XLSX 用同一份，避免三个文件说法不一致。"""
    heart = report.get("heart") or {}
    actions = report.get("actions") or {}
    score_range = report.get("score_range") or (report.get("calibration") or {}).get("range") or {}

    # 旧报告没有 20–80 动态分，只有 0–1 的 focus，按页面同样的规则回退。
    def score_of(field: str, focus_field: str) -> Any:
        value = report.get(field)
        if value is not None:
            return value
        focus = report.get(focus_field)
        return None if focus is None else float(focus) * 100

    played = report.get("played_sec")
    if played is None:
        played = report.get("duration_sec")

    rows: list[tuple[str, str]] = [
        ("报告编号", str(report.get("session_id") or "—")),
        ("训练时间", report_time(report)),
        ("信号来源", describe_source(report.get("source"))),
        ("本局游戏积分", fmt_num(report.get("score"), suffix=" 分")),
        ("专注分均值", fmt_num(score_of("score_mean", "focus_mean"), suffix=" 分")),
        ("专注分最高 / 最低",
         f"{fmt_num(score_of('score_max', 'focus_max'))} / {fmt_num(score_of('score_min', 'focus_min'))} 分"),
        ("高于专注线时间占比", fmt_num(above_ratio(report), suffix="%")),
        ("有效数据占比", fmt_num(valid_ratio(report), suffix="%")),
        ("本局用时", fmt_duration(played)),
        ("定标区间",
         f"{fmt_num(score_range.get('low'), 2)} – {fmt_num(score_range.get('high'), 2)}"),
    ]
    if heart.get("n_frames") or heart.get("mean") is not None:
        mean = heart.get("mean")
        rest = heart.get("rest_bpm")
        delta = None
        if mean is not None and rest is not None:
            try:
                delta = round(float(mean) - float(rest))
            except (TypeError, ValueError):
                delta = None
        suffix = f"（较静息 {delta:+d}）" if delta is not None else ""
        rows.append(("平均心率", f"{fmt_num(mean)} BPM{suffix}"))
    if actions:
        perfect = actions.get("successful_jumps")
        missed = actions.get("missed_jumps")
        if perfect is None:
            perfect = actions.get("timed_jumps", 0)
        if missed is None:
            missed = actions.get("automatic_jumps", 0)
        text = f"完美起跳 {perfect} 次 · 错过金色区域 {missed} 次"
        rounds = [x for x in (actions.get("rounds") or []) if isinstance(x, dict)]
        if rounds:
            successes = sum(1 for x in rounds if x.get("success"))
            text += f" · 金色时机命中率 {round(successes / len(rounds) * 100)}%"
        elif perfect + missed > 0:
            text += f" · 金色时机命中率 {round(perfect / (perfect + missed) * 100)}%"
        early = actions.get("early_taps")
        if early:
            text += f" · 提前点击 {early} 次"
        cooldown = actions.get("cooldown_count")
        if cooldown:
            text += f" · 触发冷却 {cooldown} 次"
        if actions.get("targets_shown") is not None and actions.get("targets_hit") is not None:
            text += f" · 点中目标 {actions['targets_hit']}/{actions['targets_shown']}"
        rows.append(("本局操作", text))
        if rounds:
            bases = [float(x.get("potential")) for x in rounds
                     if x.get("potential") is not None]
            awards = [float(x.get("awarded")) for x in rounds
                      if x.get("awarded") is not None]
            if bases:
                rows.append(("每轮平均脑电基础得分",
                             f"{sum(bases) / len(bases):.0f} 分（共 {len(bases)} 轮）"))
            if awards:
                rows.append(("每轮平均实际得分",
                             f"{sum(awards) / len(awards):.0f} 分（共 {len(awards)} 轮）"))
    notes = report.get("notes")
    if notes:
        rows.append(("备注", str(notes)))
    return rows


def default_summary(report: dict) -> str:
    """GET 导出时的兜底摘要；前端 POST 了「给家长的话」则优先用前端的。"""
    points = score_points(report)
    stats = process_stats(points)
    mean = report.get("score_mean")
    if mean is None and stats["mean"] is not None:
        mean = stats["mean"]
    above = above_ratio(report)
    valid = valid_ratio(report)
    minutes = max(1, round((report.get("played_sec") or report.get("duration_sec") or 0) / 60))
    heart = report.get("heart") or {}
    hr_mean = heart.get("mean")
    hr_rest = heart.get("rest_bpm")

    chunks: list[str] = []
    if mean is None:
        return ("本局没有采集到足够的有效数据，暂时无法解读表现，"
                "先检查设备佩戴与信号再开始下一局。")

    mean = round(float(mean))
    if mean >= 75:
        chunks.append(f"本局专注均值 {mean}%，整体处在较好的水平。")
    elif mean >= 60:
        chunks.append(f"本局专注均值 {mean}%，中等偏稳，属于常见的波动范围。")
    else:
        chunks.append(f"本局专注均值 {mean}%，低于平时水平，先别急着归因于“不专心”。")

    if above is not None:
        if above >= 60:
            chunks.append(f"有 {above}% 的时间高于自己的专注线。")
        elif above >= 30:
            chunks.append(f"高于专注线的时间占 {above}%，状态时好时稳。")
        else:
            chunks.append(f"只有 {above}% 的时间高于专注线。")

    if stats["trend"] is not None and abs(stats["trend"]) >= 8:
        if stats["trend"] > 0:
            chunks.append(f"后半段比前半段高 {round(stats['trend'])} 分，是越玩越进入状态。")
        else:
            chunks.append(f"后半段比前半段低 {round(-stats['trend'])} 分，更像是中途累了。")

    if stats["recoveries"] >= 3:
        chunks.append(f"中途 {stats['recoveries']} 次掉下去又自己拉回来，这个过程值得肯定。")
    elif stats["recoveries"] == 0 and stats["worst_sec"] >= 15:
        chunks.append(f"有一段连续 {stats['worst_sec']} 秒没回到专注线。")

    if hr_mean is not None and hr_rest is not None:
        delta = round(float(hr_mean) - float(hr_rest))
        if abs(delta) >= 8:
            chunks.append(f"平均心率比静息{'高' if delta > 0 else '低'} {abs(delta)} BPM，身体状态也影响了这局。")

    if valid is not None and valid < 70:
        chunks.append(f"注意本局有效数据只有 {valid}%，结论要保守看。")

    tips: list[str] = []
    if valid is not None and valid < 70:
        tips.append("先把数据质量补上：确认头环贴合、电极湿润、周围没有大功率电器，再练一次对比。")
    if stats["sd"] is not None and stats["sd"] >= 18:
        tips.append(f"先求稳再求高：本局波动 ±{round(stats['sd'])} 分，偏大。"
                    f"把单局缩到 {max(3, minutes - 2)} 分钟，中间安排一次 30 秒深呼吸复位。")
    elif stats["sd"] is not None and stats["sd"] <= 12 and mean >= 60:
        tips.append("可以加难度：本局波动很小，下次把单局延长 1–2 分钟，或把目标基线提高 5 分。")
    if stats["trend"] is not None and stats["trend"] <= -8:
        tips.append(f"缩短单局：后半段掉了 {round(-stats['trend'])} 分，更像疲劳。"
                    f"下次控制在 {max(3, minutes - 2)} 分钟，练完先休息。")
    elif stats["trend"] is not None and stats["trend"] >= 8:
        tips.append("固定热身：后半段明显更好，说明需要时间进入状态。开局前做 30 秒慢呼吸。")
    if stats["worst_sec"] >= 20 and stats["recoveries"] <= 2:
        tips.append(f"盯住那次掉线：本局最长连续 {stats['worst_sec']} 秒低于专注线，"
                    "回想那段时间在做什么（说话、看旁边、揉眼睛），下次提前避免。")
    if stats["recoveries"] >= 4:
        tips.append(f"表扬恢复过程：本局 {stats['recoveries']} 次自己调整回来，"
                    "夸具体行为比夸“真聪明”更能强化这种能力。")
    if mean >= 60 and len(tips) < 2:
        tips.append("保持节奏：每次 5–10 分钟、每周 3–5 次即可，不需要一次练很久。")
    if len(tips) < 2:
        tips.append("从短局开始：把目标定为“单局 3 分钟、一半时间高于专注线”，做到再延长。")

    text = "本局表现\n" + "".join(chunks) + "\n\n针对性建议\n"
    text += "\n".join(f"· {tip}" for tip in tips[:4])
    text += "\n· 需要时求助：如果注意力困难持续 6 个月以上，并在多个场景影响学习或社交，建议做专业评估。"
    return text


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _safe_filename(report: dict, ext: str) -> str:
    sid = str(report.get("session_id") or "report")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"专注训练报告_{stamp}_{sid[:8]}.{ext}"


def content_disposition(filename: str) -> str:
    """中文文件名：ASCII 兜底 + RFC 5987 的 filename*。"""
    from urllib.parse import quote

    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    quoted = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def _parent_lines(parent_note: Optional[str]) -> list[str]:
    """把前端 innerText 拆成可排版的段落/条目。"""
    if not parent_note:
        return []
    lines: list[str] = []
    for raw in str(parent_note).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        # 去掉前端 bullet 图标，保留文字
        line = re.sub(r"^[•·●\-–]\s*", "", line)
        # PDF 的中文字体不含彩色 emoji，去掉装饰性表情避免出现方框
        line = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", line).strip()
        if line:
            lines.append(line)
    return lines


def _timeline_actions(report: dict) -> list[tuple[float, str]]:
    actions = report.get("actions") or {}
    events: list[tuple[float, str]] = []
    for item in actions.get("jumps") or []:
        if not isinstance(item, dict) or item.get("t") is None:
            continue
        try:
            events.append((float(item["t"]), "完美起跳" if item.get("timed") else "普通跳跃"))
        except (TypeError, ValueError):
            continue
    events.sort(key=lambda e: e[0])
    return events


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _register_cjk_font() -> str:
    """注册一个能显示中文的字体，返回字体名。"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates: list[tuple[str, int]] = []
    if platform.system() == "Windows":
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        candidates += [
            (os.path.join(fonts, "msyh.ttc"), 0),
            (os.path.join(fonts, "msyhbd.ttc"), 0),
            (os.path.join(fonts, "simhei.ttf"), 0),
            (os.path.join(fonts, "Deng.ttf"), 0),
            (os.path.join(fonts, "simsun.ttc"), 0),
        ]
    elif platform.system() == "Darwin":
        candidates += [
            ("/System/Library/Fonts/PingFang.ttc", 0),
            ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
            ("/Library/Fonts/Arial Unicode.ttf", 0),
        ]
    else:
        candidates += [
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
            ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf", 0),
            ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
            ("/usr/share/fonts/truetype/arphic/uming.ttc", 0),
        ]

    for path, index in candidates:
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("ReportCJK", path, subfontIndex=index))
            return "ReportCJK"
        except Exception:  # noqa: BLE001 - 换下一个候选字体
            continue

    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"
    except Exception as exc:  # noqa: BLE001
        raise ExportUnavailable(
            "未找到可用的中文字体，PDF 导出已跳过。请安装微软雅黑/黑体，"
            "或在 requirements.txt 里确认 reportlab 已正确安装。"
        ) from exc


def _curve_drawing(points: Sequence[tuple[float, float]], heart: Sequence[tuple[float, float]],
                   font: str, width: float = 465, height: float = 165):
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    from reportlab.lib import colors

    drawing = Drawing(width, height)
    left, right, top, bottom = 34, 30, 22, 20
    x0, y0 = left, bottom
    plot_w = width - left - right
    plot_h = height - top - bottom
    tmax = max([t for t, _ in points] + [10.0])
    grid = colors.HexColor("#DCE7E5")
    label = colors.HexColor("#7C9199")

    for i in range(5):
        y = y0 + plot_h * i / 4
        drawing.add(Line(x0, y, x0 + plot_w, y, strokeColor=grid, strokeWidth=0.6))
        drawing.add(String(x0 - 6, y - 3, str(i * 25), fontName=font,
                           fontSize=7, fillColor=label, textAnchor="end"))

    # 50 分专注线
    base_y = y0 + plot_h * 0.5
    drawing.add(Line(x0, base_y, x0 + plot_w, base_y, strokeColor=colors.HexColor("#EF8C1F"),
                     strokeWidth=1.0, strokeDashArray=[4, 3]))

    coords = [(x0 + plot_w * t / tmax,
               y0 + plot_h * min(100.0, max(0.0, v)) / 100.0) for t, v in points]
    if len(coords) >= 2:
        drawing.add(PolyLine(coords, strokeColor=colors.HexColor("#2F9C93"),
                             strokeWidth=2, strokeLineJoin=1))

    if len(heart) >= 2:
        def hr_y(bpm: float) -> float:
            return y0 + plot_h * min(1.0, max(0.0, (bpm - 40.0) / 100.0))
        hr_coords = [(x0 + plot_w * t / tmax, hr_y(bpm)) for t, bpm in heart]
        drawing.add(PolyLine(hr_coords, strokeColor=colors.HexColor("#E2554E"),
                             strokeWidth=1, strokeDashArray=[3, 2]))
        lo = round(min(b for _, b in heart))
        hi = round(max(b for _, b in heart))
        drawing.add(String(x0 + 2, height - 11,
                           f"心率 {lo}–{hi} BPM（红色虚线，仅趋势）",
                           fontName=font, fontSize=7,
                           fillColor=colors.HexColor("#C0443E")))

    drawing.add(String(x0, 5, "0s", fontName=font, fontSize=7, fillColor=label))
    drawing.add(String(x0 + plot_w, 5, f"{round(tmax)}s", fontName=font,
                       fontSize=7, fillColor=label, textAnchor="end"))
    return drawing


def build_pdf(report: dict, parent_note: Optional[str] = None) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError as exc:  # noqa: BLE001
        raise ExportUnavailable("缺少 reportlab，无法导出 PDF（pip install reportlab）") from exc

    font = _register_cjk_font()
    buf = io.BytesIO()

    title_style = ParagraphStyle("t", fontName=font, fontSize=20, leading=28,
                                 textColor=colors.HexColor("#1F4A44"), spaceAfter=2)
    sub_style = ParagraphStyle("s", fontName=font, fontSize=9.5, leading=15,
                               textColor=colors.HexColor("#6A828A"))
    head_style = ParagraphStyle("h", fontName=font, fontSize=12.5, leading=19,
                                textColor=colors.HexColor("#1F4A44"), spaceBefore=10, spaceAfter=6)
    body_style = ParagraphStyle("b", fontName=font, fontSize=10, leading=17,
                                textColor=colors.HexColor("#2A3E3C"), spaceAfter=4)
    small_style = ParagraphStyle("sm", fontName=font, fontSize=8.5, leading=14,
                                textColor=colors.HexColor("#7C9199"))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#9BB0B5"))
        canvas.drawString(18 * mm, 11 * mm, "专注小蛙 · 训练报告")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=18 * mm,
        title="专注小蛙 训练报告", author="专注小蛙",
    )

    story: list = [
        Paragraph("专注小蛙 · 训练报告", title_style),
        Paragraph(f"{report_time(report)} · 报告编号 {report.get('session_id') or '—'}", sub_style),
        Spacer(1, 8),
    ]

    rows = overview_rows(report)
    table_data = [[Paragraph("项目", small_style), Paragraph("结果", small_style)]]
    for label, value in rows:
        table_data.append([Paragraph(label, body_style), Paragraph(value, body_style)])
    table = Table(table_data, colWidths=[62 * mm, 112 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF4F1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F4A44")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D3E2DE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FBFA")]),
    ]))
    story.append(table)

    points = score_points(report)
    heart = heart_points(report)
    if points:
        story.append(Paragraph("专注曲线", head_style))
        story.append(Paragraph(
            f"纵轴为 0–100 分（20–80 动态定标），橙色虚线为 50 分专注线，共 {len(points)} 个有效采样点。",
            small_style))
        story.append(Spacer(1, 4))
        story.append(_curve_drawing(points, heart, font))

    events = _timeline_actions(report)
    if events:
        story.append(Paragraph("起跳事件", head_style))
        chips = [f"{t:g}s {'完美' if kind == '完美起跳' else '普通'}" for t, kind in events[:60]]
        extra = f"（共 {len(events)} 次，仅列前 60 次）" if len(events) > 60 else ""
        story.append(Paragraph(" · ".join(chips) + extra, body_style))

    note_lines = _parent_lines(parent_note)
    story.append(Paragraph("给家长的话", head_style))
    if note_lines:
        for line in note_lines:
            if line in ("本局表现", "针对性建议"):
                story.append(Paragraph(f"<b>{line}</b>", body_style))
            else:
                story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;")
                                       .replace(">", "&gt;"), body_style))
    else:
        for block in default_summary(report).split("\n\n"):
            for line in block.split("\n"):
                story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;")
                                       .replace(">", "&gt;"), body_style))

    story.append(Spacer(1, 10))
    story.append(KeepTogether([
        Paragraph(f"<b>仅供参考：</b>{DISCLAIMER}", small_style),
        Paragraph(REFERENCE, small_style),
    ]))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def build_xlsx(report: dict, parent_note: Optional[str] = None) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.chart import LineChart, Reference
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # noqa: BLE001
        raise ExportUnavailable("缺少 openpyxl，无法导出 Excel（pip install openpyxl）") from exc

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="EAF4F1")
    head_font = Font(bold=True, color="1F4A44")
    wrap = Alignment(wrap_text=True, vertical="top")

    # ---- Sheet 1: 概览 ----
    ws = wb.active
    ws.title = "报告概览"
    ws["A1"] = "专注小蛙 · 训练报告"
    ws["A1"].font = Font(bold=True, size=16, color="1F4A44")
    ws["A2"] = f"{report_time(report)} · 报告编号 {report.get('session_id') or '—'}"
    ws["A2"].font = Font(size=9, color="6A828A")
    ws.append([])
    ws.append(["项目", "结果"])
    for cell in ws[4]:
        cell.fill = head_fill
        cell.font = head_font
    for label, value in overview_rows(report):
        ws.append([label, value])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 62
    for row in ws.iter_rows(min_row=5, max_col=2):
        for cell in row:
            cell.alignment = wrap

    note_lines = _parent_lines(parent_note) or default_summary(report).splitlines()
    start = ws.max_row + 2
    ws.cell(row=start, column=1, value="给家长的话").font = Font(bold=True, size=12, color="1F4A44")
    for offset, line in enumerate([ln for ln in note_lines if ln.strip()], start=1):
        cell = ws.cell(row=start + offset, column=1, value=line)
        cell.alignment = wrap
        ws.merge_cells(start_row=start + offset, start_column=1,
                       end_row=start + offset, end_column=2)
        ws.row_dimensions[start + offset].height = max(16, 15 * (len(line) // 40 + 1))

    # ---- Sheet 2: 专注曲线 ----
    points = score_points(report)
    heart_map = {round(t, 2): bpm for t, bpm in heart_points(report)}
    ws2 = wb.create_sheet("专注曲线")
    ws2.append(["时间（秒）", "专注分（0–100）", "心率（BPM）"])
    for cell in ws2[1]:
        cell.fill = head_fill
        cell.font = head_font
    for t, score in points:
        ws2.append([round(t, 2), round(score, 1), heart_map.get(round(t, 2))])
    ws2.column_dimensions["A"].width = 14
    ws2.column_dimensions["B"].width = 18
    ws2.column_dimensions["C"].width = 14
    ws2.freeze_panes = "A2"

    if len(points) >= 2:
        chart = LineChart()
        chart.title = "专注曲线（0–100 分）"
        chart.y_axis.title = "专注分"
        chart.x_axis.title = "时间（秒）"
        chart.height = 8.5
        chart.width = 20
        chart.style = 2
        data = Reference(ws2, min_col=2, min_row=1, max_row=ws2.max_row)
        cats = Reference(ws2, min_col=1, min_row=2, max_row=ws2.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        ws2.add_chart(chart, "E2")

    # ---- Sheet 3: 起跳事件 ----
    events = _timeline_actions(report)
    ws3 = wb.create_sheet("起跳事件")
    ws3.append(["时间（秒）", "类型"])
    for cell in ws3[1]:
        cell.fill = head_fill
        cell.font = head_font
    for t, kind in events:
        ws3.append([round(t, 2), kind])
    ws3.column_dimensions["A"].width = 14
    ws3.column_dimensions["B"].width = 14

    # ---- Sheet 4: 每轮数据（研究分析用，不在儿童端展示）----
    rounds = (report.get("actions") or {}).get("rounds") or []
    if rounds:
        ws4 = wb.create_sheet("每轮数据")
        headers = [
            "轮次", "蓄力用时（秒）", "金色区域起点", "金色区域终点",
            "基准蓄力用时（秒）", "脑电基础得分", "实际得分", "点击倍率", "是否成功",
            "点击反应（秒）", "平均信号分", "达标占比",
            "衰减次数", "衰减时长（秒）", "信号异常时长（秒）", "提前点击",
            "冷却次数", "冷却时长（秒）",
        ]
        ws4.append(headers)
        for cell in ws4[1]:
            cell.fill = head_fill
            cell.font = head_font
        for item in rounds:
            if not isinstance(item, dict):
                continue
            ws4.append([
                item.get("round"),
                item.get("charge_sec"),
                item.get("zone_lo"),
                item.get("zone_hi"),
                item.get("t_ref"),
                item.get("potential"),
                item.get("awarded"),
                item.get("multiplier"),
                "是" if item.get("success") else "否",
                item.get("reaction_sec"),
                item.get("mean_score"),
                item.get("above_ratio"),
                item.get("decay_events"),
                item.get("decay_sec"),
                item.get("stale_sec"),
                item.get("early_taps"),
                item.get("cooldown_count"),
                item.get("cooldown_sec"),
            ])
        for col, width in zip("ABCDEFGHIJKLMNOPQR",
                              [8, 16, 14, 14, 18, 16, 10, 10, 10, 14, 14, 10, 10, 14, 16, 10, 10, 14]):
            ws4.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------
def build_docx(report: dict, parent_note: Optional[str] = None) -> bytes:
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt, RGBColor
    except ImportError as exc:  # noqa: BLE001
        raise ExportUnavailable("缺少 python-docx，无法导出 Word（pip install python-docx）") from exc

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "微软雅黑"
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    heading = doc.add_heading("专注小蛙 · 训练报告", level=0)
    for run in heading.runs:
        run.font.name = "微软雅黑"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    meta = doc.add_paragraph(f"{report_time(report)} · 报告编号 {report.get('session_id') or '—'}")
    meta.runs[0].font.size = Pt(9)
    meta.runs[0].font.color.rgb = RGBColor(0x6A, 0x82, 0x8A)

    doc.add_heading("报告概览", level=1)
    rows = overview_rows(report)
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    header = table.rows[0].cells
    header[0].text = "项目"
    header[1].text = "结果"
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(9.5)
                    run.font.name = "微软雅黑"
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    doc.add_heading("给家长的话", level=1)
    note_lines = _parent_lines(parent_note)
    if note_lines:
        for line in note_lines:
            paragraph = doc.add_paragraph()
            run = paragraph.add_run(line)
            run.font.name = "微软雅黑"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
            if line in ("本局表现", "针对性建议"):
                run.bold = True
                run.font.size = Pt(11.5)
            if line.startswith("· "):
                paragraph.paragraph_format.left_indent = Pt(10)
    else:
        for block in default_summary(report).split("\n\n"):
            for line in block.split("\n"):
                paragraph = doc.add_paragraph()
                run = paragraph.add_run(line.lstrip("· "))
                run.font.name = "微软雅黑"
                run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    points = score_points(report)
    if points:
        doc.add_heading("专注曲线数据", level=1)
        para = doc.add_paragraph(
            f"共 {len(points)} 个有效采样点，均值 "
            f"{fmt_num(report.get('score_mean') or process_stats(points)['mean'], suffix=' 分')}。"
            "逐点曲线与折线图请使用「Excel」导出。"
        )
        para.runs[0].font.size = Pt(9.5)
        para.runs[0].font.color.rgb = RGBColor(0x6A, 0x82, 0x8A)

    doc.add_paragraph()
    footer = doc.add_paragraph()
    run = footer.add_run(f"仅供参考：{DISCLAIMER}")
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor(0x6A, 0x82, 0x8A)
    ref = doc.add_paragraph()
    run = ref.add_run(REFERENCE)
    run.font.size = Pt(8.5)
    run.font.color.rgb = RGBColor(0x6A, 0x82, 0x8A)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CSV / JSON
# ---------------------------------------------------------------------------
def build_csv(report: dict) -> bytes:
    points = score_points(report)
    heart_map = {round(t, 2): bpm for t, bpm in heart_points(report)}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["时间（秒）", "专注分（0-100）", "心率（BPM）"])
    for t, score in points:
        writer.writerow([round(t, 2), round(score, 1), heart_map.get(round(t, 2), "")])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def build_json(report: dict) -> bytes:
    import json

    return json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")


BUILDERS = {
    "pdf": (build_pdf, "pdf", "application/pdf"),
    "xlsx": (build_xlsx, "xlsx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "docx": (build_docx, "docx",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "csv": (build_csv, "csv", "text/csv; charset=utf-8"),
    "json": (build_json, "json", "application/json; charset=utf-8"),
}


def export_report(report: dict, fmt: str, parent_note: Optional[str] = None) -> tuple[bytes, str, str]:
    """返回 (文件字节, 建议文件名, Content-Type)。"""
    fmt = (fmt or "").lower().lstrip(".")
    if fmt not in BUILDERS:
        raise ValueError(f"不支持的导出格式：{fmt}")
    builder, ext, media_type = BUILDERS[fmt]
    if fmt in ("csv", "json"):
        payload = builder(report)  # type: ignore[operator]
    else:
        payload = builder(report, parent_note)  # type: ignore[operator]
    return payload, _safe_filename(report, ext), media_type
