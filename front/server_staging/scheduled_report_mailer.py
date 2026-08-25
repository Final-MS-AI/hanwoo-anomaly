"""Send the COWOW weekly barn-operation report to each device owner.

Run once from the systemd timer. The delivery table makes retries safe and
prevents the same reporting period from being mailed twice.
"""
from __future__ import annotations

import argparse
import html
import os
import smtplib
import textwrap
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

from dotenv import load_dotenv

# The FastAPI service keeps secrets outside the repository. Load it before
# importing device_claim_api, which reads DATABASE_URL at import time.
load_dotenv(os.getenv("COWOW_ENV_FILE", "/home/azureuser/3rd_fastapi/.env"))

from device_claim_api import get_connection
from operations_report_api import control_durations, ensure_schema, number, windows


DEVICE_ID = os.getenv("ESP32_PHYSICAL_DEVICE_ID", "ESP32-01")
REPORT_DAYS = max(1, min(31, int(os.getenv("REPORT_EMAIL_DAYS", "7"))))
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://hanwoo.koreacentral.cloudapp.azure.com").rstrip("/")


def ensure_delivery_schema(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_report_deliveries (
                id BIGSERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                report_period_start DATE NOT NULL,
                report_period_end DATE NOT NULL,
                sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status TEXT NOT NULL DEFAULT 'sent',
                error_message TEXT,
                UNIQUE(device_id, recipient_email, report_period_start)
            )
            """
        )
    connection.commit()


def metric(value, unit):
    return f"{number(value):.1f}{unit}" if value is not None else "수집 데이터 없음"


def duration(seconds):
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}시간 {minutes}분" if hours else f"{minutes}분"


def build_report(connection, device_id, days):
    end_at = datetime.now(timezone.utc)
    start_at = end_at - timedelta(days=days)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT recorded_at, temperature, humidity, air_quality
            FROM device_telemetry_history
            WHERE device_id = %s AND recorded_at >= %s
            ORDER BY recorded_at ASC
            """,
            (device_id, start_at),
        )
        sensor_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT COUNT(*),
                   AVG(temperature), MIN(temperature), MAX(temperature),
                   AVG(humidity), MIN(humidity), MAX(humidity),
                   AVG(air_quality), MIN(air_quality), MAX(air_quality)
            FROM device_telemetry_history
            WHERE device_id = %s AND recorded_at >= %s
            """,
            (device_id, start_at),
        )
        summary = cursor.fetchone()
        cursor.execute(
            """
            SELECT actuator, command_value, created_at
            FROM device_commands
            WHERE device_id = %s AND status = 'completed' AND created_at >= %s
            ORDER BY created_at ASC
            """,
            (device_id, start_at),
        )
        command_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT COALESCE(NULLIF(cattle_id, ''), camera_id || ' 미확인 개체'),
                   behavior, status, COUNT(*), MAX(detected_at)
            FROM device_anomaly_events
            WHERE device_id = %s AND detected_at >= %s
            GROUP BY COALESCE(NULLIF(cattle_id, ''), camera_id || ' 미확인 개체'), behavior, status
            ORDER BY MAX(detected_at) DESC
            LIMIT 30
            """,
            (device_id, start_at),
        )
        anomaly_rows = cursor.fetchall()

    temperatures = [(row[0], row[1]) for row in sensor_rows]
    humidities = [(row[0], row[2]) for row in sensor_rows]
    qualities = [(row[0], row[3]) for row in sensor_rows]
    return {
        "start": start_at,
        "end": end_at,
        "sample_count": int(summary[0] or 0),
        "temperature": {"average": summary[1], "min": summary[2], "max": summary[3], "high": windows(temperatures, 28)},
        "humidity": {"average": summary[4], "min": summary[5], "max": summary[6], "high": windows(humidities, 75)},
        "air_quality": {"average": summary[7], "min": summary[8], "max": summary[9], "high": windows(qualities, 55)},
        "controls": control_durations(command_rows, end_at),
        "anomalies": anomaly_rows,
    }


def report_html(owner_name, report):
    anomaly_lines = "".join(
        f"<li><b>{html.escape(str(cattle_id))}</b> · {html.escape(str(behavior))} · {html.escape(str(status))} · {count}건</li>"
        for cattle_id, behavior, status, count, _ in report["anomalies"]
    ) or "<li>기간 내 확인이 필요한 이상행동 기록이 없습니다.</li>"
    control_lines = "".join(
        f"<li>{html.escape(str(item['actuator']))}: 명령 {item['commandCount']}건 · 가동 추정 {duration(item['estimatedOnSeconds'])}</li>"
        for item in report["controls"]
    ) or "<li>완료된 제어 명령이 없습니다.</li>"
    return f"""<!doctype html><html lang=\"ko\"><body style=\"font-family:Arial,'Apple SD Gothic Neo',sans-serif;color:#281d14;line-height:1.6\">
    <h1 style=\"color:#287343\">COWOW 주간 축사 운영 보고서</h1>
    <p>안녕하세요, {html.escape(owner_name or '관리자')}님. 최근 {REPORT_DAYS}일간의 장비·센서·이상행동 요약입니다.</p>
    <p><b>수집 건수:</b> {report['sample_count']}건</p>
    <table style=\"border-collapse:collapse\"><tr><th style=\"padding:8px;border:1px solid #ddd\">항목</th><th style=\"padding:8px;border:1px solid #ddd\">평균</th><th style=\"padding:8px;border:1px solid #ddd\">최저</th><th style=\"padding:8px;border:1px solid #ddd\">최고</th></tr>
    <tr><td style=\"padding:8px;border:1px solid #ddd\">온도</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['temperature']['average'], '°C')}</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['temperature']['min'], '°C')}</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['temperature']['max'], '°C')}</td></tr>
    <tr><td style=\"padding:8px;border:1px solid #ddd\">습도</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['humidity']['average'], '%')}</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['humidity']['min'], '%')}</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['humidity']['max'], '%')}</td></tr>
    <tr><td style=\"padding:8px;border:1px solid #ddd\">공기질</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['air_quality']['average'], '%')}</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['air_quality']['min'], '%')}</td><td style=\"padding:8px;border:1px solid #ddd\">{metric(report['air_quality']['max'], '%')}</td></tr></table>
    <h2>장비 제어 이력</h2><ul>{control_lines}</ul>
    <h2>이상행동 기록</h2><ul>{anomaly_lines}</ul>
    <p><a href=\"{html.escape(FRONTEND_URL)}/dashboard\">COWOW 대시보드에서 상세 보고서 보기</a></p>
    </body></html>"""


def _pdf_text(value):
    """Encode Korean text for a built-in Korean CID font PDF string."""
    return str(value).encode("utf-16-be").hex().upper()


def _pdf_lines(owner_name, report):
    lines = [
        "COWOW 축사 운영 보고서",
        f"수신자: {owner_name or '구성원'}",
        f"보고 기간: {report['start'].astimezone().strftime('%Y-%m-%d')} ~ {report['end'].astimezone().strftime('%Y-%m-%d')}",
        f"센서 수집 건수: {report['sample_count']}건",
        "",
        "[환경 센서 요약]",
        f"온도  평균 {metric(report['temperature']['average'], '°C')} / 최저 {metric(report['temperature']['min'], '°C')} / 최고 {metric(report['temperature']['max'], '°C')}",
        f"습도  평균 {metric(report['humidity']['average'], '%')} / 최저 {metric(report['humidity']['min'], '%')} / 최고 {metric(report['humidity']['max'], '%')}",
        f"공기질 평균 {metric(report['air_quality']['average'], '%')} / 최저 {metric(report['air_quality']['min'], '%')} / 최고 {metric(report['air_quality']['max'], '%')}",
        "",
        "[장비 제어 이력]",
    ]
    controls = report["controls"] or []
    lines.extend(
        f"- {item['actuator']}: 명령 {item['commandCount']}건, 가동 추정 {duration(item['estimatedOnSeconds'])}"
        for item in controls
    )
    if not controls:
        lines.append("- 완료된 제어 명령이 없습니다.")
    lines.extend(["", "[이상행동 기록]"])
    anomalies = report["anomalies"] or []
    lines.extend(
        f"- {cattle_id} · {behavior} · {status} · {count}건"
        for cattle_id, behavior, status, count, _ in anomalies
    )
    if not anomalies:
        lines.append("- 기간 내 확인이 필요한 이상행동 기록이 없습니다.")
    lines.extend(["", f"상세 확인: {FRONTEND_URL}/dashboard"])
    return [part for line in lines for part in (textwrap.wrap(line, width=62) or [""])]


def report_pdf(owner_name, report):
    """Generate a compact, dependency-free A4 PDF attachment with Korean text."""
    lines = _pdf_lines(owner_name, report)
    per_page = 38
    pages = [lines[index:index + per_page] for index in range(0, len(lines), per_page)] or [[""]]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        None,
        b"<< /Type /Font /Subtype /Type0 /BaseFont /HYSMyeongJo-Medium /Encoding /UniKS-UTF16-H /DescendantFonts [4 0 R] >>",
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /HYSMyeongJo-Medium /CIDSystemInfo << /Registry (Adobe) /Ordering (Korea1) /Supplement 2 >> >>",
    ]
    page_ids = []
    for page_lines in pages:
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        commands = ["BT", "/F1 17 Tf", "50 800 Td"]
        for index, line in enumerate(page_lines):
            if index:
                commands.append("0 -20 Td")
            commands.append(f"<{_pdf_text(line)}> Tj")
        commands.append("ET")
        content = "\n".join(commands).encode("ascii")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode("ascii"))
        objects.append(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream")
    objects[1] = ("<< /Type /Pages /Count %d /Kids [%s] >>" % (len(page_ids), " ".join(f"{page_id} 0 R" for page_id in page_ids))).encode("ascii")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:]))
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(output)


def send_report(recipient, owner_name, report):
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    if not username or not password:
        raise RuntimeError("SMTP_USERNAME 또는 SMTP_PASSWORD가 설정되지 않았습니다.")
    message = EmailMessage()
    message["Subject"] = f"[COWOW] 최근 {REPORT_DAYS}일 축사 운영 보고서"
    message["From"] = f"{os.getenv('SMTP_FROM_NAME', 'COWOW')} <{username}>"
    message["To"] = recipient
    message.set_content(f"COWOW 최근 {REPORT_DAYS}일 축사 운영 보고서입니다. 웹에서 상세 내용을 확인하세요: {FRONTEND_URL}/dashboard")
    message.add_alternative(report_html(owner_name, report), subtype="html")
    message.add_attachment(
        report_pdf(owner_name, report),
        maintype="application",
        subtype="pdf",
        filename=f"COWOW_축사운영보고서_{report['end'].strftime('%Y%m%d')}.pdf",
    )
    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(username, password)
        smtp.send_message(message)


def recipients(connection, device_id):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH connected_users AS (
                SELECT user_id FROM device_owners WHERE device_id = %s
                UNION
                SELECT user_id FROM device_members WHERE device_id = %s
            )
            SELECT COALESCE(NULLIF(r.email, ''), u.email), COALESCE(NULLIF(u.name, ''), '구성원')
            FROM connected_users cu
            JOIN users u ON u.id = cu.user_id
            LEFT JOIN user_report_recipients r ON r.user_id = u.id AND r.verified_at IS NOT NULL
            WHERE COALESCE(NULLIF(r.email, ''), NULLIF(u.email, '')) IS NOT NULL
            """,
            (device_id, device_id),
        )
        return cursor.fetchall()


def was_sent(connection, recipient, period_start):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM scheduled_report_deliveries WHERE device_id=%s AND recipient_email=%s AND report_period_start=%s",
            (DEVICE_ID, recipient, period_start),
        )
        return cursor.fetchone() is not None


def record_delivery(connection, recipient, period_start, period_end):
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO scheduled_report_deliveries(device_id, recipient_email, report_period_start, report_period_end)
               VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (DEVICE_ID, recipient, period_start, period_end),
        )
    connection.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="발송 이력과 관계없이 현재 보고 기간을 다시 발송합니다.",
    )
    args = parser.parse_args()
    with get_connection() as connection:
        ensure_schema(connection)
        ensure_delivery_schema(connection)
        report = build_report(connection, DEVICE_ID, REPORT_DAYS)
        period_start = report["start"].date()
        period_end = report["end"].date()
        owners = recipients(connection, DEVICE_ID)
        if not owners:
            print(f"No owner with an email for {DEVICE_ID}; report not sent.")
            return
        for recipient, owner_name in owners:
            if not args.force and was_sent(connection, recipient, period_start):
                print(f"Already sent to {recipient} for {period_start}.")
                continue
            if args.dry_run:
                print(f"DRY RUN: would send {REPORT_DAYS}-day report to {recipient}; samples={report['sample_count']}")
                continue
            send_report(recipient, owner_name, report)
            record_delivery(connection, recipient, period_start, period_end)
            print(f"Report sent to {recipient}.")


if __name__ == "__main__":
    main()
