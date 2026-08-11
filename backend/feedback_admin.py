from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is not configured.")
    return value


def list_pending() -> None:
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, job_id, feedback_type, frame_time_seconds,
                       track_id, corrected_label, comment, evidence_path,
                       created_at
                FROM model_feedback
                WHERE review_status = 'pending'
                ORDER BY created_at
                """
            )
            for row in cursor.fetchall():
                print(json.dumps(dict(row), ensure_ascii=False, default=str))


def review(feedback_id: str, status: str, note: str | None) -> None:
    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE model_feedback
                SET review_status = %s,
                    reviewer_note = %s,
                    reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (status, note, feedback_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Feedback not found: {feedback_id}")
        connection.commit()


def export_approved(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    exported_ids: list[str] = []

    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, job_id, feedback_type, frame_time_seconds,
                       track_id, predicted_label, corrected_label, comment,
                       source_video_url, result_video_url, evidence_path,
                       inference_summary, created_at, reviewed_at
                FROM model_feedback
                WHERE review_status = 'approved'
                  AND training_exported_at IS NULL
                ORDER BY reviewed_at, created_at
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]

            with output_path.open("w", encoding="utf-8") as output_file:
                for row in rows:
                    exported_ids.append(str(row["id"]))
                    output_file.write(
                        json.dumps(row, ensure_ascii=False, default=str) + "\n"
                    )

            if exported_ids:
                cursor.execute(
                    """
                    UPDATE model_feedback
                    SET training_exported_at = NOW(),
                        review_status = 'exported',
                        updated_at = NOW()
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (exported_ids,),
                )
        connection.commit()

    print(f"Exported {len(exported_ids)} feedback rows to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review and export model feedback")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("feedback_id")
    review_parser.add_argument("status", choices=["approved", "rejected"])
    review_parser.add_argument("--note")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument(
        "--output",
        type=Path,
        default=BASE_DIR / "feedback_exports" / "approved_feedback.jsonl",
    )

    args = parser.parse_args()
    if args.command == "list":
        list_pending()
    elif args.command == "review":
        review(args.feedback_id, args.status, args.note)
    elif args.command == "export":
        export_approved(args.output)


if __name__ == "__main__":
    main()

