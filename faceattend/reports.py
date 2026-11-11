import csv
import io
from collections import Counter
from datetime import date, datetime

from flask import Response, send_file
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import or_

from models import Attendance, Student, db

# (key, header, width)
COLUMNS = [
    ("date", "Date", 12), ("roll_no", "Roll No", 12), ("name", "Name", 26), ("class_name", "Class", 12),
    ("section", "Section", 10), ("check_in", "Check-in", 12), ("status", "Status", 12), ("method", "Method", 14),
]


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def is_single_day(args):
    start, end = parse_date(args.get("date_from")), parse_date(args.get("date_to"))
    return bool(start and start == end)


def _text_match(q):
    like = f"%{q}%"
    return or_(Student.full_name.ilike(like), Student.roll_no.ilike(like))


def build_rows(args):
    """Filtered attendance rows. For a single selected date, students with no record appear as absent."""
    q = (args.get("q") or "").strip()[:64]
    class_name = (args.get("class_name") or "").strip()
    status = (args.get("status") or "").strip().lower()
    start, end = parse_date(args.get("date_from")), parse_date(args.get("date_to"))
    if start and end and end < start:
        start, end = end, start

    query = db.session.query(Attendance, Student).join(Student, Attendance.student_id == Student.id)
    if start:
        query = query.filter(Attendance.date >= start)
    if end:
        query = query.filter(Attendance.date <= end)
    if class_name:
        query = query.filter(Student.class_name == class_name)
    if q:
        query = query.filter(_text_match(q))
    if status in ("present", "late"):
        query = query.filter(Attendance.status == status)

    rows = []
    for att, stu in query.order_by(Attendance.date.desc(), Attendance.check_in.desc()).all():
        rows.append({
            "student_id": stu.id, "date": att.date.isoformat(), "roll_no": stu.roll_no, "name": stu.full_name,
            "class_name": stu.class_name, "section": stu.section or "",
            "check_in": att.check_in.strftime("%H:%M:%S"), "status": att.status, "method": att.method,
        })

    if start and start == end and status in ("", "absent"):
        marked = {r["student_id"] for r in rows if r["date"] == start.isoformat()}
        students = Student.query
        if class_name:
            students = students.filter(Student.class_name == class_name)
        if q:
            students = students.filter(_text_match(q))
        for stu in students.order_by(Student.class_name, Student.roll_no).all():
            if stu.id not in marked:
                rows.append({
                    "student_id": stu.id, "date": start.isoformat(), "roll_no": stu.roll_no, "name": stu.full_name,
                    "class_name": stu.class_name, "section": stu.section or "", "check_in": "—",
                    "status": "absent", "method": "—",
                })

    if status == "absent":
        rows = [r for r in rows if r["status"] == "absent"]
    return rows


def _safe(value):
    """Stop spreadsheet formula injection by neutralising leading = + - @ characters."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def export(rows, fmt):
    stem = f"attendance-{datetime.now():%Y%m%d-%H%M}"
    labels = [label for _, label, _ in COLUMNS]
    keys = [key for key, _, _ in COLUMNS]
    body = [[_safe(r[k]) for k in keys] for r in rows]
    if fmt == "xlsx":
        return _excel(labels, body, rows, stem)
    return _csv(labels, body, stem)


def _csv(labels, body, stem):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(labels)
    writer.writerows(body)
    return Response(
        buf.getvalue().encode("utf-8-sig"),  # BOM so Excel opens UTF-8 correctly
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
    )


def _excel(labels, body, rows, stem):
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    ws.append(labels)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0B1730")
        cell.alignment = Alignment(horizontal="center")
    for line in body:
        ws.append(line)
    for idx, (_, _, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    summary = wb.create_sheet("Summary")
    summary.append(["Status", "Count"])
    counts = Counter(r["status"] for r in rows)
    for status in ("present", "late", "absent"):
        summary.append([status.title(), counts.get(status, 0)])
    summary.append(["Total rows", len(rows)])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{stem}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
