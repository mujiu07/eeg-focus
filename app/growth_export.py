"""v1.9.0 家长成长报告的 PDF / Excel / JSON / CSV 导出。

不包含原始高频 EEG；所有输出均由同一份 growth.build_report() 数据生成，
避免不同格式之间口径漂移。
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, Iterable, List, Optional

from . import export as report_export
from . import growth


class GrowthExportError(RuntimeError):
    pass


def _safe(value: Any) -> str:
    from xml.sax.saxutils import escape
    return escape(str(value if value is not None else ""))


def _display(value: Any, unit: str = "") -> str:
    if value is None:
        return "数据不足"
    if isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return text + unit if unit else text


def _duration(seconds: Any) -> str:
    if seconds is None:
        return "数据不足"
    return report_export.fmt_duration(seconds).replace("—", "数据不足")


def _percent(value: Any) -> str:
    return "数据不足" if value is None else f"{float(value) * 100:.1f}%"


def _pn(value: Any, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "数据不足"
    return f"{float(value):.{digits}f}{suffix}"


def _metrics_rows(report: Dict[str, Any]) -> List[tuple]:
    behavior = report.get("behavior") or {}
    usage = report.get("usage") or {}
    return [
        ("使用情况", "累计使用天数", usage.get("usage_days"), "天", "正式游戏/真实评估/有效校准的本地日期去重"),
        ("使用情况", "正式游戏次数", usage.get("formal_game_count"), "次", "不含模拟、回放和标准评估"),
        ("使用情况", "实际游戏时长", _duration(usage.get("play_seconds")), "", "正式游戏 played_sec"),
        ("使用情况", "有效信号采集时长", _duration(usage.get("effective_signal_seconds")), "", "按时长 × 有效帧比例折算；无 EEG 局不计"),
        ("游戏行为", "成功跳跃次数", behavior.get("successful_jumps"), "次", "完整轮次 success 之和"),
        ("游戏行为", "进入黄色区域次数", behavior.get("zone_entries"), "次", "完整轮次 + 已进入未完成轮次"),
        ("游戏行为", "点击成功率", _percent(behavior.get("click_success_rate")), "", "成功 ÷（成功 + 未成功完成）"),
        ("游戏行为", "点击反应时间中位数", _pn(behavior.get("reaction_median"), 2, " 秒"), "", "仅成功且具有有效 reaction_sec 的轮次"),
        ("游戏行为", "提前点击次数", behavior.get("early_taps"), "次", "正式游戏 actions.early_taps"),
        ("游戏行为", "净蓄力用时中位数", _pn(behavior.get("net_charge_median"), 3, " 秒"), "", "仅完整轮次 eval_sec；未完成轮次单列"),
        ("游戏行为", "有效信号比例", _percent(behavior.get("valid_signal_ratio")), "", "有效帧 ÷ 总帧（正式硬件游戏汇总）"),
        ("游戏行为", "当前难度", _pn((report.get("difficulty") or {}).get("current_factor"), 2), "", "黄色区域起点；不是专注力分数"),
        ("标准评估", "真实标准评估次数", (report.get("assessments") or {}).get("completed_count"), "次", "含已完成记录，模拟另列"),
    ]


def _assessment_rows(report: Dict[str, Any]) -> List[List[Any]]:
    rows = []
    for item in (report.get("assessments") or {}).get("items") or []:
        rows.append([
            item.get("date") or "数据不足",
            item.get("source_label") or "",
            item.get("protocol_version") or "",
            _pn(item.get("reference_score"), 1),
            _pn(item.get("pre_map_score"), 3),
            _percent(item.get("valid_signal_ratio")),
            _percent(item.get("click_success_rate")),
            _pn(item.get("reaction_median"), 2, "s"),
            "可比较" if item.get("comparable") else "不参与趋势：" + "；".join(item.get("comparison_reasons") or []),
        ])
    return rows


def build_json(report: Dict[str, Any]) -> bytes:
    return json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")


def build_csv(report: Dict[str, Any]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["section", "date", "session_id", "metric", "value", "unit", "quality", "note"])
    for section, label, value, unit, note in _metrics_rows(report):
        writer.writerow([section, "", "", label, "" if value is None else value, unit,
                         "missing" if value is None else "ok", note])
    for day in report.get("daily") or []:
        writer.writerow(["daily", day.get("date"), "", "played_sec", day.get("played_sec"), "秒",
                         "ok" if day.get("has_data") else "no_record",
                         f"sessions={day.get('sessions')}"])
        if day.get("has_data"):
            writer.writerow(["daily", day.get("date"), "", "click_success_rate",
                             day.get("click_success_rate"), "比例",
                             "missing" if day.get("click_success_rate") is None else "ok", ""])
    for row in report.get("sessions") or []:
        writer.writerow(["session", row.get("date"), row.get("session_id"), "kind",
                         row.get("kind"), "", "ok", row.get("kind_label") or ""])
        writer.writerow(["session", row.get("date"), row.get("session_id"), "played_sec",
                         row.get("played_sec"), "秒",
                         "missing" if row.get("played_sec") is None else "ok", ""])
        writer.writerow(["session", row.get("date"), row.get("session_id"), "score",
                         row.get("score"), "分",
                         "missing" if row.get("score") is None else "ok", ""])
        metrics = row.get("metrics") or {}
        for key in ("successful_jumps", "click_success_rate", "reaction_median",
                    "net_charge_median", "valid_signal_ratio"):
            writer.writerow(["session", row.get("date"), row.get("session_id"), key,
                             metrics.get(key), "", "missing" if metrics.get(key) is None else "ok", ""])
    for item in (report.get("assessments") or {}).get("items") or []:
        writer.writerow(["assessment", item.get("date"), item.get("session_id"),
                         "reference_score", item.get("reference_score"), "分",
                         "missing" if item.get("reference_score") is None else "ok",
                         item.get("source_label") or ""])
        writer.writerow(["assessment", item.get("date"), item.get("session_id"),
                         "comparable", item.get("comparable"), "", "ok",
                         "；".join(item.get("comparison_reasons") or [])])
    for group in ((report.get("assessments") or {}).get("trend") or {}).get("segments") or []:
        for series in group.get("series") or []:
            for point in series.get("points") or []:
                writer.writerow(["assessment_trend", point.get("date"), point.get("assessment_id"),
                                 series.get("metric"), point.get("value"), "",
                                 "missing" if point.get("value") is None else "ok",
                                 group.get("segment_reason") or ""])
    for point in (report.get("difficulty") or {}).get("points") or []:
        writer.writerow(["difficulty", point.get("date"), "", "factor_change",
                         f"{point.get('before')}→{point.get('after')}", "", "ok",
                         point.get("reason") or ""])
    writer.writerow(["meta", "", "", "generated_at", report.get("generated_at"), "", "ok", ""])
    writer.writerow(["meta", "", "", "encrypted", "false", "", "ok",
                     "SQLite 与导出文件尚未静态加密"])
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def build_excel(report: Dict[str, Any]) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, Reference
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise GrowthExportError("缺少 openpyxl，无法生成 Excel") from exc

    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="D9EAD3")
    header_font = Font(bold=True, color="1D3B2A")
    title_font = Font(bold=True, size=14, color="1D3B2A")
    wrap = Alignment(wrap_text=True, vertical="top")

    def style_sheet(ws, headers: List[str], rows: List[List[Any]], widths: Optional[List[int]] = None):
        ws.append(headers)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center")
        for row in rows:
            ws.append(["" if v is None else v for v in row])
        for col_idx, header in enumerate(headers, 1):
            width = widths[col_idx - 1] if widths and col_idx <= len(widths) else 16
            ws.column_dimensions[get_column_letter(col_idx)].width = width
        ws.freeze_panes = "A2"
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = wrap

    ws = wb.create_sheet("概览")
    ws["A1"] = "专注小蛙 · 家长成长报告"
    ws["A1"].font = title_font
    ws["A2"] = f"孩子：{report.get('user', {}).get('nickname', '小蛙朋友')}"
    ws["A3"] = f"日期范围：{(report.get('range') or {}).get('label')}"
    ws["A4"] = f"生成时间：{report.get('generated_at')}"
    ws["A5"] = "说明：本报告是本地游戏与任务记录的确定性统计，不是临床注意力评价。"
    ws["A5"].alignment = wrap
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 60
    ws["A7"] = "指标"
    ws["B7"] = "数值"
    ws["C7"] = "统计口径"
    for cell in ws[7]:
        cell.fill = header_fill
        cell.font = header_font
    for i, (_, label, value, unit, note) in enumerate(_metrics_rows(report), 8):
        ws.cell(i, 1, label)
        ws.cell(i, 2, _display(value, unit))
        ws.cell(i, 3, note).alignment = wrap
    ws.freeze_panes = "A8"

    style_sheet(wb.create_sheet("每日使用"),
                ["日期", "正式游戏次数", "游戏时长(分钟)", "成功跳跃", "点击成功率", "有效信号比例", "低质量局数", "是否有记录"],
                [[d.get("date"), d.get("sessions"), None if d.get("played_sec") is None else round(d["played_sec"] / 60, 2),
                  d.get("successful_jumps"), d.get("click_success_rate"), d.get("valid_signal_ratio"),
                  d.get("low_quality_sessions"), "是" if d.get("has_data") else "否"]
                 for d in report.get("daily") or []],
                [13, 12, 14, 12, 14, 15, 12, 12])
    if len(wb["每日使用"]._charts) == 0:
        ws_daily = wb["每日使用"]
        chart = BarChart()
        chart.title = "每日游戏时长（分钟）"
        chart.y_axis.title = "分钟"
        chart.x_axis.title = "日期"
        if ws_daily.max_row > 1:
            data = Reference(ws_daily, min_col=3, min_row=1, max_row=ws_daily.max_row)
            cats = Reference(ws_daily, min_col=1, min_row=2, max_row=ws_daily.max_row)
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(cats)
            chart.height = 6
            chart.width = 15
            ws_daily.add_chart(chart, "J2")

    style_sheet(wb.create_sheet("正式游戏"),
                ["日期", "Session", "来源", "时长(分钟)", "游戏积分", "成功跳跃", "点击成功率", "反应中位数(s)", "净蓄力中位数(s)", "有效信号比例", "低质量"],
                [[r.get("date"), r.get("session_id"), r.get("source_label"),
                  None if r.get("played_sec") is None else round(r["played_sec"] / 60, 2),
                  r.get("score"), (r.get("metrics") or {}).get("successful_jumps"),
                  (r.get("metrics") or {}).get("click_success_rate"),
                  (r.get("metrics") or {}).get("reaction_median"),
                  (r.get("metrics") or {}).get("net_charge_median"),
                  (r.get("metrics") or {}).get("valid_signal_ratio"),
                  "是" if r.get("low_quality") else "否"] for r in report.get("sessions") or []],
                [13, 20, 20, 12, 10, 10, 12, 14, 16, 14, 8])

    style_sheet(wb.create_sheet("标准评估"),
                ["日期", "来源", "协议", "S_reference", "映射前输出", "有效信号", "点击成功率", "反应中位数(s)", "是否可比 / 原因"],
                _assessment_rows(report),
                [13, 20, 14, 13, 14, 12, 13, 15, 42])

    trend_rows = []
    for group in ((report.get("assessments") or {}).get("trend") or {}).get("segments") or []:
        for series in group.get("series") or []:
            for point in series.get("points") or []:
                trend_rows.append([group.get("label"), group.get("segment_reason"),
                                   series.get("metric"), point.get("date"),
                                   point.get("assessment_id"), point.get("value")])
    style_sheet(wb.create_sheet("评估趋势"),
                ["条件段", "分段原因", "指标", "日期", "评估", "数值"],
                trend_rows, [40, 20, 24, 13, 20, 12])

    style_sheet(wb.create_sheet("难度变化"),
                ["日期", "变化前", "变化后", "方向", "决策", "原因"],
                [[p.get("date"), p.get("before"), p.get("after"), p.get("direction"),
                  p.get("decision"), p.get("reason")] for p in (report.get("difficulty") or {}).get("points") or []],
                [13, 10, 10, 10, 18, 42])

    style_sheet(wb.create_sheet("指标说明"),
                ["指标", "口径", "单位"],
                [[v.get("label"), v.get("denominator"), v.get("unit")]
                 for v in (report.get("definitions") or {}).values()],
                [28, 80, 10])

    style_sheet(wb.create_sheet("数据局限"),
                ["项目", "说明"],
                [["低信号阈值", f"有效信号比例低于 {int(growth.MIN_VALID_SIGNAL_RATIO * 100)}% 不参与评估趋势"],
                 ["缺失值", "空白/数据不足表示没有有效数据，不填 0"],
                 ["模拟与回放", "不进入真实 EEG 成长趋势"],
                 ["隐私", "未包含原始高频 EEG；SQLite 与导出文件尚未静态加密"]]
                + [["说明", x] for x in report.get("limitations") or []],
                [18, 100])

    buf = io.BytesIO()
    try:
        wb.save(buf)
    except Exception as exc:  # noqa: BLE001
        raise GrowthExportError(f"Excel 生成失败：{exc}") from exc
    return buf.getvalue()


def _bar_chart(daily: List[Dict[str, Any]], width: float = 500, height: float = 150):
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    drawing = Drawing(width, height)
    left, bottom = 38, 24
    usable_w = width - left - 12
    usable_h = height - bottom - 12
    values = [d.get("played_sec") or 0 for d in daily]
    maximum = max(values + [1])
    n = max(1, len(daily))
    slot = usable_w / n
    for i, day in enumerate(daily):
        value = day.get("played_sec") or 0
        h = (value / maximum) * usable_h
        x = left + i * slot + 2
        drawing.add(Rect(x, bottom, max(1, slot - 4), h, fillColor="#8BC6A4", strokeColor=None))
        if i % max(1, n // 7) == 0:
            drawing.add(String(x, 8, str(day.get("date") or "")[5:], fontSize=6, fillColor="#45614F"))
    drawing.add(Line(left, bottom, left + usable_w, bottom, strokeColor="#B7C9BC"))
    drawing.add(String(4, height - 10, "每日游戏时长", fontSize=8, fillColor="#1D3B2A"))
    return drawing


def _trend_chart(report: Dict[str, Any], width: float = 500, height: float = 160):
    from reportlab.graphics.shapes import Drawing, Line, String
    drawing = Drawing(width, height)
    groups = ((report.get("assessments") or {}).get("trend") or {}).get("segments") or []
    series = []
    for group in groups:
        for item in group.get("series") or []:
            if item.get("metric") == "reference_score" and item.get("points"):
                series.append((group, item["points"]))
                break
    if not series:
        drawing.add(String(20, height / 2, "暂无可比较的标准评估趋势（数据不足）", fontSize=9, fillColor="#45614F"))
        return drawing
    left, bottom, usable_w, usable_h = 38, 24, width - 50, height - 38
    all_values = [p["value"] for _, points in series for p in points if p.get("value") is not None]
    if not all_values:
        drawing.add(String(20, height / 2, "暂无可比较的标准评估趋势（数据不足）", fontSize=9, fillColor="#45614F"))
        return drawing
    lo, hi = min(all_values), max(all_values)
    if hi == lo:
        hi = lo + 1
    base_y = bottom
    drawing.add(Line(left, base_y, left + usable_w, base_y, strokeColor="#B7C9BC"))
    colors = ["#4C9A6E", "#D29A45", "#6C86C9", "#B16AA0", "#5AA6B4"]
    for group_index, (_, points) in enumerate(series):
        color = colors[group_index % len(colors)]
        coords = []
        for p in points:
            if p.get("value") is None:
                continue
            x = left + usable_w * (len(coords) / max(1, len(points) - 1))
            y = bottom + usable_h * ((p["value"] - lo) / (hi - lo))
            coords.append((x, y))
        for i in range(1, len(coords)):
            drawing.add(Line(coords[i - 1][0], coords[i - 1][1],
                             coords[i][0], coords[i][1], strokeColor=color, strokeWidth=2))
        for x, y in coords:
            drawing.add(Line(x - 2, y, x + 2, y, strokeColor=color, strokeWidth=2))
            drawing.add(Line(x, y - 2, x, y + 2, strokeColor=color, strokeWidth=2))
    drawing.add(String(4, height - 10, "标准评估 S_reference（不同条件分段，不连线）",
                       fontSize=8, fillColor="#1D3B2A"))
    return drawing


def build_pdf(report: Dict[str, Any]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                        SimpleDocTemplate, Spacer, Table, TableStyle)
    except ImportError as exc:
        raise GrowthExportError("缺少 reportlab，无法生成 PDF") from exc

    font = report_export._register_cjk_font()
    title = ParagraphStyle("GrowthTitle", fontName=font, fontSize=19, leading=25,
                           textColor=colors.HexColor("#1D3B2A"), spaceAfter=4)
    h1 = ParagraphStyle("GrowthH1", fontName=font, fontSize=13, leading=18,
                        textColor=colors.HexColor("#2E6B4B"), spaceBefore=10, spaceAfter=5)
    body = ParagraphStyle("GrowthBody", fontName=font, fontSize=8.5, leading=13,
                          textColor=colors.HexColor("#294536"), alignment=TA_LEFT)
    small = ParagraphStyle("GrowthSmall", fontName=font, fontSize=7, leading=10,
                           textColor=colors.HexColor("#5B7162"))
    head = ParagraphStyle("GrowthHead", fontName=font, fontSize=7.5, leading=10,
                          textColor=colors.HexColor("#1D3B2A"))

    def P(text: Any, style=body):
        return Paragraph(_safe(text), style)

    def table(headers: List[str], rows: List[List[Any]], widths: Optional[List[float]] = None):
        data = [[P(h, head) for h in headers]]
        for row in rows:
            data.append([P(v) if isinstance(v, str) and len(str(v)) > 18 else str(v)
                         for v in row])
        t = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAD3")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1D3B2A")),
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("LEADING", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D8CE")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5FAF6")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#6C8173"))
        canvas.drawString(18 * mm, 10 * mm, "专注小蛙 · 家长成长报告")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title="专注小蛙 · 家长成长报告", author="专注小蛙")
    story = [
        P("专注小蛙 · 成长报告", title),
        P(f"孩子：{report.get('user', {}).get('nickname', '小蛙朋友')}　"
          f"范围：{(report.get('range') or {}).get('label')}　"
          f"生成：{report.get('generated_at')}", small),
        Spacer(1, 4),
        P("本报告是本地游戏与任务记录的确定性统计，不是临床注意力评价，也不构成诊断或治疗建议。", body),
        P("一、使用情况", h1),
    ]
    usage = report.get("usage") or {}
    story.append(table(
        ["累计使用天数", "正式游戏次数", "实际游戏时长", "有效信号采集时长", "最近一次使用"],
        [[str(usage.get("usage_days") if usage.get("usage_days") is not None else "数据不足"),
          str(usage.get("formal_game_count") if usage.get("formal_game_count") is not None else "数据不足"),
          _duration(usage.get("play_seconds")),
          _duration(usage.get("effective_signal_seconds")),
          str(usage.get("last_use") or "数据不足")]],
        [30 * mm, 30 * mm, 38 * mm, 42 * mm, 38 * mm]))
    story += [Spacer(1, 5), P("二、游戏行为表现", h1)]
    story.append(table(
        ["指标", "数值", "统计口径"],
        [[label, _display(value, unit), note] for _, label, value, unit, note in _metrics_rows(report)],
        [35 * mm, 27 * mm, 112 * mm]))
    story += [Spacer(1, 5), P("三、每日使用与游戏时长", h1)]
    story.append(P("柱状图只表示正式游戏时长；空白日期表示没有记录，不插入估算值。", small))
    story.append(_bar_chart(report.get("daily") or []))
    story.append(table(
        ["日期", "正式游戏", "分钟", "成功跳跃", "点击成功率", "有效信号"],
        [[d.get("date"), d.get("sessions"), _pn(None if d.get("played_sec") is None else d["played_sec"] / 60, 1),
          d.get("successful_jumps") if d.get("successful_jumps") is not None else "数据不足",
          _percent(d.get("click_success_rate")), _percent(d.get("valid_signal_ratio"))]
         for d in report.get("daily") or []],
        [28 * mm, 20 * mm, 18 * mm, 25 * mm, 33 * mm, 35 * mm]))

    story += [PageBreak(), P("四、标准评估与长期趋势", h1),
              P((report.get("assessments") or {}).get("trend", {}).get("policy", ""), body),
              P("不同条件段之间不连线；不足两次有效评估时只展示记录，不计算趋势。", small)]
    story.append(_trend_chart(report))
    story.append(table(
        ["日期", "来源", "S_reference", "映射前", "有效信号", "点击成功", "可比性"],
        [[a.get("date") or "数据不足", a.get("source_label") or "",
          _pn(a.get("reference_score"), 1), _pn(a.get("pre_map_score"), 3),
          _percent(a.get("valid_signal_ratio")), _percent(a.get("click_success_rate")),
          "可比较" if a.get("comparable") else "不参与趋势"]
         for a in (report.get("assessments") or {}).get("items") or []],
        [25 * mm, 28 * mm, 25 * mm, 20 * mm, 24 * mm, 25 * mm, 27 * mm]))
    for group in (report.get("assessments") or {}).get("trend", {}).get("segments") or []:
        story += [Spacer(1, 4), P(f"条件段：{group.get('label')}　"
                                  f"{group.get('segment_reason')}　{group.get('trend_note')}", small)]
        rows = []
        for series in group.get("series") or []:
            rows.append([series.get("label"), _pn(series.get("first"), 3),
                         _pn(series.get("last"), 3),
                         "不计算" if not series.get("trend_available") else _pn(series.get("change"), 3)])
        if rows:
            story.append(table(["指标", "首次", "末次", "变化（仅同段）"], rows,
                               [70 * mm, 34 * mm, 34 * mm, 42 * mm]))

    story += [PageBreak(), P("五、游戏难度变化", h1)]
    points = (report.get("difficulty") or {}).get("points") or []
    story.append(table(["日期", "变化前", "变化后", "方向 / 决策", "原因"],
                       [[p.get("date"), _pn(p.get("before"), 2), _pn(p.get("after"), 2),
                         f"{p.get('direction') or ''} / {p.get('decision') or ''}", p.get("reason") or ""]
                        for p in points] or [["数据不足", "", "", "", "所选范围内没有难度调整记录"]]))
    story += [Spacer(1, 6), P("六、数据质量与局限", h1)]
    quality = report.get("quality") or {}
    story.append(table(["项目", "数量"], [
        ["正式游戏", quality.get("sessions_total")],
        ["低信号质量局数", quality.get("sessions_low_quality")],
        ["缺少逐轮数据局数", quality.get("sessions_missing_rounds")],
        ["不参与趋势的评估", quality.get("assessment_uncomparable")],
        ["模拟/回放评估", quality.get("assessment_simulation")],
    ]))
    story.append(P("缺失值不会被填成 0；低质量记录保留在历史列表，但不参与脑电趋势。", small))
    for line in report.get("limitations") or []:
        story.append(P("• " + line, small))

    story += [Spacer(1, 6), P("七、指标解释", h1)]
    story.append(table(["指标", "统计口径", "单位"],
                       [[v.get("label"), v.get("denominator"), v.get("unit")]
                        for v in (report.get("definitions") or {}).values()],
                       [40 * mm, 102 * mm, 18 * mm]))
    story += [Spacer(1, 6), P("八、报告说明", h1)]
    for line in report.get("narrative") or []:
        story.append(P("• " + line, body))
    try:
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    except Exception as exc:  # noqa: BLE001
        raise GrowthExportError(f"PDF 生成失败：{exc}") from exc
    data = buf.getvalue()
    if not data.startswith(b"%PDF"):
        raise GrowthExportError("PDF 生成结果不是有效文件")
    return data


def build_export(report: Dict[str, Any], fmt: str) -> bytes:
    fmt = fmt.lower()
    if fmt == "json":
        return build_json(report)
    if fmt == "csv":
        return build_csv(report)
    if fmt == "xlsx":
        return build_excel(report)
    if fmt == "pdf":
        return build_pdf(report)
    raise GrowthExportError("导出格式只支持 pdf、xlsx、json、csv")
