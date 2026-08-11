from feedback_api import FeedbackCreate


def test_feedback_payload_normalizes_optional_text():
    payload = FeedbackCreate(
        job_id="job-1",
        feedback_type="wrong_tracking",
        frame_time_seconds=12.5,
        track_id="  7  ",
        corrected_label="  walking  ",
        comment="   ",
    )

    assert payload.track_id == "7"
    assert payload.corrected_label == "walking"
    assert payload.comment is None


def test_feedback_payload_accepts_supported_categories():
    categories = [
        "missed_cow",
        "false_detection",
        "wrong_tracking",
        "wrong_behavior",
        "false_anomaly",
        "missed_anomaly",
    ]

    for category in categories:
        payload = FeedbackCreate(job_id="job-1", feedback_type=category)
        assert payload.feedback_type == category

