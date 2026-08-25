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
from weasyprint import HTML

# The FastAPI service keeps secrets outside the repository. Load it before
# importing device_claim_api, which reads DATABASE_URL at import time.
load_dotenv(os.getenv("COWOW_ENV_FILE", "/home/azureuser/3rd_fastapi/.env"))

from device_claim_api import get_connection
from operations_report_api import control_durations, ensure_schema, number, windows


DEVICE_ID = os.getenv("ESP32_PHYSICAL_DEVICE_ID", "ESP32-01")
REPORT_DAYS = max(1, min(31, int(os.getenv("REPORT_EMAIL_DAYS", "7"))))
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://hanwoo.koreacentral.cloudapp.azure.com").rstrip("/")
PDF_FONT_PATH = os.getenv(
    "COWOW_REPORT_FONT_PATH",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
)


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


def report_pdf_html(owner_name, report):
    def card(label, value, note=""):
        return f"<td class='metric-card'><div class='label'>{html.escape(label)}</div><strong>{html.escape(value)}</strong><small>{html.escape(note)}</small></td>"

    anomaly_rows = "".join(
        f"<tr><td>{html.escape(str(cattle_id))}</td><td>{html.escape(str(behavior))}</td><td>{html.escape(str(status))}</td><td>{count}건</td></tr>"
        for cattle_id, behavior, status, count, _ in report["anomalies"]
    ) or "<tr><td colspan='4' class='empty'>기간 내 확인이 필요한 이상행동 기록이 없습니다.</td></tr>"
    control_rows = "".join(
        f"<tr><td>{html.escape(str(item['actuator']))}</td><td>{item['commandCount']}건</td><td>{duration(item['estimatedOnSeconds'])}</td></tr>"
        for item in report["controls"]
    ) or "<tr><td colspan='3' class='empty'>완료된 제어 명령이 없습니다.</td></tr>"
    report_day = report["end"].astimezone().strftime("%Y년 %m월 %d일")
    period = f"{report['start'].astimezone().strftime('%Y.%m.%d')} ~ {report['end'].astimezone().strftime('%Y.%m.%d')}"
    return f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>
    @font-face {{ font-family: Cowow; src: url('file://{PDF_FONT_PATH}'); }}
    @page {{ size: A4; margin: 12mm 13mm; }}
    * {{ box-sizing: border-box; }} body {{ font-family: Cowow, sans-serif; color:#30251d; font-size:10px; line-height:1.5; }}
    header {{ border-bottom:1px solid #d9cbb9; padding-bottom:13px; }} .eyebrow {{ color:#287343; font-size:11px; font-weight:700; }}
    h1 {{ font-size:23px; margin:5px 0 4px; }} .sub {{ color:#806f60; margin:0; }} .period {{ float:right; color:#806f60; font-size:9px; margin-top:-16px; }}
    table {{ border-spacing:0; width:100%; }} .cards {{ margin-top:14px; border-spacing:8px 0; margin-left:-8px; width:calc(100% + 16px); }}
    .metric-card {{ width:25%; padding:12px; border:1px solid #e3d7c8; border-radius:10px; vertical-align:top; }} .metric-card .label {{ color:#806f60; }}
    .metric-card strong {{ display:block; font-size:16px; margin-top:4px; }} .metric-card small {{ display:block; color:#897b70; margin-top:3px; }}
    section {{ margin-top:13px; border:1px solid #d5e6d7; border-radius:12px; padding:14px; break-inside:avoid; }} section.sensor {{ border-color:#e7d7c3; }}
    h2 {{ margin:1px 0 8px; font-size:15px; }} .section-number {{ color:#287343; font-weight:700; font-size:10px; }} .summary {{ color:#5f554b; margin:0 0 10px; }}
    .mini td {{ width:33%; background:#f7faf7; border-radius:8px; padding:9px; vertical-align:top; }} .mini strong {{ display:block; font-size:13px; margin-top:2px; }}
    .data-table {{ border:1px solid #eadfd3; border-radius:8px; overflow:hidden; }} .data-table th {{ text-align:left; background:#f8f4ee; padding:7px; color:#705e4d; }} .data-table td {{ padding:7px; border-top:1px solid #eee5db; }} .empty {{ color:#887c70; text-align:center; }}
    footer {{ margin-top:14px; color:#8a7d71; font-size:8px; }}
    </style></head><body><header><div class='eyebrow'>COWOW 축사 운영 리포트</div><h1>{report_day} 환경 · 이상행동 보고서</h1><p class='sub'>ESP32가 연결된 기간 동안 누적한 센서 · 제어 · 이상행동 이력을 기반으로 작성되었습니다.</p><span class='period'>보고 기간 {period}</span></header>
    <table class='cards'><tr>{card('수집 데이터', f"{report['sample_count']}건", '최근 7일 센서 이력')}{card('온도 평균', metric(report['temperature']['average'], '°C'), f"최저 {metric(report['temperature']['min'], '°C')} · 최고 {metric(report['temperature']['max'], '°C')}")}{card('습도 평균', metric(report['humidity']['average'], '%'), f"최저 {metric(report['humidity']['min'], '%')} · 최고 {metric(report['humidity']['max'], '%')}")}{card('공기질 평균', metric(report['air_quality']['average'], '%'), f"최저 {metric(report['air_quality']['min'], '%')} · 최고 {metric(report['air_quality']['max'], '%')}")}</tr></table>
    <section><div class='section-number'>01 · 종합 판단</div><h2>오늘의 축사 운영 요약</h2><p class='summary'>센서 수치와 이상행동 이력을 함께 확인해 현장 점검과 장비 운전 상태를 판단하세요.</p><table class='mini'><tr><td>개체 관찰<strong>{'우선 점검' if report['anomalies'] else '정상 관찰'}</strong></td><td>환기 · 냉각<strong>{'운전 이력 확인' if report['controls'] else '현재 유지'}</strong></td><td>추가 설비 판단<strong>이력 추적</strong></td></tr></table></section>
    <section class='sensor'><div class='section-number'>02 · 환경 이력</div><h2>최근 7일 센서 추세와 설비 판단</h2><table class='data-table'><tr><th>항목</th><th>평균</th><th>최저</th><th>최고</th></tr><tr><td>온도</td><td>{metric(report['temperature']['average'], '°C')}</td><td>{metric(report['temperature']['min'], '°C')}</td><td>{metric(report['temperature']['max'], '°C')}</td></tr><tr><td>습도</td><td>{metric(report['humidity']['average'], '%')}</td><td>{metric(report['humidity']['min'], '%')}</td><td>{metric(report['humidity']['max'], '%')}</td></tr><tr><td>공기질</td><td>{metric(report['air_quality']['average'], '%')}</td><td>{metric(report['air_quality']['min'], '%')}</td><td>{metric(report['air_quality']['max'], '%')}</td></tr></table></section>
    <section><div class='section-number'>03 · 장비 제어</div><h2>환기 · 살수 장비 가동 이력</h2><table class='data-table'><tr><th>장비</th><th>명령 횟수</th><th>가동 추정 시간</th></tr>{control_rows}</table></section>
    <section><div class='section-number'>04 · 개체 이상행동</div><h2>확인 필요한 개체 및 증상</h2><table class='data-table'><tr><th>개체</th><th>증상</th><th>위험도</th><th>횟수</th></tr>{anomaly_rows}</table></section>
    <footer>COWOW · 본 보고서는 저장된 센서 이력과 완료된 제어 명령을 기준으로 생성되었습니다. 상세 내용은 {html.escape(FRONTEND_URL)}/dashboard 에서 확인할 수 있습니다.</footer></body></html>"""


def report_pdf(owner_name, report):
    """Render the dashboard-style report using a browser-grade HTML engine."""
    return HTML(string=report_pdf_html(owner_name, report), base_url="/").write_pdf()


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
