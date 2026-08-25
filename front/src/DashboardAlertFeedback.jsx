import { useState } from "react";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

const CORRECTED_LABELS = [
  ["normal", "정상 행동"],
  ["standing", "서 있음"],
  ["walking", "걷는 중"],
  ["lying", "누워 있음"],
  ["feeding", "섭식 중"],
  ["ruminating", "반추 중"],
  ["unknown", "판단하기 어려움"],
];

function DashboardAlertFeedback({ cattle }) {
  const [isOpen, setIsOpen] = useState(false);
  const [feedbackType, setFeedbackType] = useState("false_anomaly");
  const [correctedLabel, setCorrectedLabel] = useState("normal");
  const [comment, setComment] = useState("");
  const [evidenceImage, setEvidenceImage] = useState(null);
  const [evidenceVideo, setEvidenceVideo] = useState(null);
  const [submitState, setSubmitState] = useState("idle");
  const [message, setMessage] = useState("");

  const submitFeedback = async (event) => {
    event.preventDefault();
    if (submitState === "submitting") return;

    setSubmitState("submitting");
    setMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/feedback`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: cattle.jobId || `dashboard-alert-${cattle.id}`,
          feedback_type: feedbackType,
          frame_time_seconds: cattle.frameTimeSeconds || 0,
          track_id: cattle.trackId || cattle.cattleId,
          predicted_label: cattle.behavior,
          corrected_label: correctedLabel,
          comment: comment || null,
          source_video_url: cattle.sourceVideoUrl || null,
          result_video_url: cattle.resultVideoUrl || null,
          inference_summary: {
            alert_id: cattle.id,
            cattle_id: cattle.cattleId,
            status: cattle.status,
            detected_at: cattle.lastDetectedAt,
          },
          anomaly_event_id: cattle.anomalyEventId || null,
        }),
      });

      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result?.detail || "피드백 저장에 실패했습니다.");
      }

      if (evidenceImage || evidenceVideo) {
        const evidence = new FormData();
        if (evidenceImage) evidence.append("image", evidenceImage);
        if (evidenceVideo) evidence.append("video", evidenceVideo);
        const evidenceResponse = await fetch(
          `${API_BASE_URL}/feedback/${result.id}/evidence`,
          { method: "POST", credentials: "include", body: evidence },
        );
        const evidenceResult = await evidenceResponse.json().catch(() => null);
        if (!evidenceResponse.ok) {
          throw new Error(
            evidenceResult?.detail || "피드백은 저장됐지만 증거 파일 업로드에 실패했습니다.",
          );
        }
      }

      setSubmitState("success");
      setMessage("피드백이 저장됐습니다. 검토 후 다음 화요일 업데이트에 반영됩니다.");
      setComment("");
      setEvidenceImage(null);
      setEvidenceVideo(null);
    } catch (error) {
      setSubmitState("error");
      setMessage(error.message);
    }
  };

  return (
    <div className="dashboard-alert-feedback">
      <button
        className="dashboard-feedback-trigger"
        type="button"
        aria-expanded={isOpen}
        onClick={() => {
          setIsOpen((previous) => !previous);
          setMessage("");
          setSubmitState("idle");
        }}
      >
        {isOpen ? "신고 닫기" : "AI 판단이 잘못됐어요"}
      </button>

      {isOpen && (
        <form className="dashboard-feedback-form" onSubmit={submitFeedback}>
          <div className="dashboard-feedback-context">
            <span>AI 판단</span>
            <strong>{cattle.behavior}</strong>
          </div>

          <label>
            잘못된 부분
            <select
              value={feedbackType}
              onChange={(event) => setFeedbackType(event.target.value)}
            >
              <option value="false_anomaly">정상인데 이상으로 탐지했어요</option>
              <option value="wrong_behavior">행동 종류가 틀렸어요</option>
              <option value="wrong_tracking">다른 소의 결과가 연결됐어요</option>
              <option value="false_detection">소가 아닌 대상을 탐지했어요</option>
            </select>
          </label>

          <label>
            실제 상태
            <select
              value={correctedLabel}
              onChange={(event) => setCorrectedLabel(event.target.value)}
            >
              {CORRECTED_LABELS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>

          <label className="dashboard-feedback-comment">
            추가 설명(선택)
            <textarea
              maxLength="1000"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="예: 실제로는 서 있었고 COW-013의 결과로 보입니다."
            />
          </label>

          <div className="dashboard-feedback-files">
            <label>
              당시 이미지(선택)
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(event) => setEvidenceImage(event.target.files?.[0] || null)}
              />
            </label>
            <label>
              당시 영상 구간(선택)
              <input
                type="file"
                accept="video/mp4,video/webm,video/quicktime"
                onChange={(event) => setEvidenceVideo(event.target.files?.[0] || null)}
              />
            </label>
          </div>

          {message && (
            <p className={`dashboard-feedback-message ${submitState}`} role="status">
              {message}
            </p>
          )}

          <button
            className="dashboard-feedback-submit"
            type="submit"
            disabled={submitState === "submitting"}
          >
            {submitState === "submitting" ? "전송 중..." : "검토 요청 보내기"}
          </button>
        </form>
      )}
    </div>
  );
}

export default DashboardAlertFeedback;
