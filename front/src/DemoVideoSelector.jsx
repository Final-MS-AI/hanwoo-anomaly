import { useEffect, useRef, useState } from "react";

const DEMO_VIDEOS = [
  {
    id: "normal",
    title: "일반 축사 영상",
    description: "여러 개체의 일상 행동을 추적하는 시연 영상입니다.",
    videoUrl: "/cow_normal.mp4",
  },
  {
    id: "abnormal",
    title: "이상 개체 포함 영상",
    description: "여러 소 중 이상 징후가 있는 개체를 탐지합니다.",
    videoUrl: "/cow_normal.mp4",
  },
];

const STATUS_LABELS = {
  idle: "대기",
  uploading: "영상 전송 중",
  detecting: "개체 탐지 중",
  tracking: "개체 추적 중",
  analyzing: "행동 분석 중",
  completed: "분석 완료",
};

function DemoVideoSelector({ onInferenceComplete }) {
  const [isSelectorOpen, setIsSelectorOpen] = useState(false);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [jobStatus, setJobStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [detectedCattle, setDetectedCattle] = useState([]);
  const timerRef = useRef(null);

  const isRunning = [
    "uploading",
    "detecting",
    "tracking",
    "analyzing",
  ].includes(jobStatus);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  const handleSelectVideo = (video) => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
    }

    setSelectedVideo({
      ...video,
      sourceVideoUrl: video.videoUrl,
    });
    setJobStatus("idle");
    setProgress(0);
    setDetectedCattle([]);
    setIsSelectorOpen(false);
  };

  const handleStartInference = async () => {
    if (!selectedVideo || isRunning) {
      return;
    }

    try {
      console.log("영상 분석 시작");
      console.log(
        "API 주소:",
        import.meta.env.VITE_API_BASE_URL,
      );

      setProgress(0);
      setDetectedCattle([]);
      setJobStatus("uploading");

      const sourceResponse = await fetch(
        selectedVideo.videoUrl,
      );

      if (!sourceResponse.ok) {
        throw new Error(
          "선택한 원본 영상을 불러오지 못했습니다.",
        );
      }

      const videoBlob = await sourceResponse.blob();
      const formData = new FormData();

      formData.append(
        "video",
        videoBlob,
        `${selectedVideo.id}.mp4`,
      );

      const createResponse = await fetch(
        `https://hanwoo.koreacentral.cloudapp.azure.com/inference/jobs`,
        {
          method: "POST",
          body: formData,
        },
      );

      const createResult =
        await createResponse.json();

      if (!createResponse.ok) {
        throw new Error(
          createResult.detail ||
            "영상 업로드에 실패했습니다.",
        );
      }

      const jobId = createResult.job_id;

      console.log("추론 작업 생성:", jobId);

      timerRef.current = setInterval(async () => {
        try {
          const statusResponse = await fetch(
            `https://hanwoo.koreacentral.cloudapp.azure.com/inference/jobs/${jobId}`,
          );

          const statusResult =
            await statusResponse.json();

          console.log("추론 상태:", statusResult);

          if (!statusResponse.ok) {
            throw new Error(
              statusResult.detail ||
                "추론 상태 조회에 실패했습니다.",
            );
          }

          setProgress(statusResult.progress ?? 0);

          const statusMap = {
            queued: "uploading",
            processing: "detecting",
            detecting: "detecting",
            tracking: "tracking",
            analyzing: "analyzing",
            completed: "completed",
          };

          setJobStatus(
            statusMap[statusResult.status] ??
              "detecting",
          );

          if (statusResult.status === "completed") {
            clearInterval(timerRef.current);
            timerRef.current = null;

            const resultVideoUrl =
              statusResult.result_url;

            console.log("결과 영상 URL:", resultVideoUrl);

            setSelectedVideo((previous) => ({
              ...previous,
              videoUrl: resultVideoUrl,
              resultVideoUrl,
              inferenceSummary:
                statusResult.summary ?? null,
            }));

            setDetectedCattle([]);

            if (onInferenceComplete) {
              onInferenceComplete({
                videoId: selectedVideo.id,
                jobId,
                resultVideoUrl,
                summary: statusResult.summary ?? null,
                cattle: [],
                anomalies: [],
              });
            }
          }

          if (statusResult.status === "failed") {
            clearInterval(timerRef.current);
            timerRef.current = null;

            throw new Error(
              statusResult.error ||
                "영상 추론에 실패했습니다.",
            );
          }
        } catch (pollError) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }

          console.error(
            "추론 상태 조회 오류:",
            pollError,
          );

          setJobStatus("idle");
          setProgress(0);
          window.alert(pollError.message);
        }
      }, 2000);
    } catch (error) {
      console.error("추론 시작 오류:", error);

      setJobStatus("idle");
      setProgress(0);
      window.alert(error.message);
    }
  };
  const handleReset = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    setSelectedVideo(null);
    setJobStatus("idle");
    setProgress(0);
    setDetectedCattle([]);
    setIsSelectorOpen(false);
  };

  return (
    <section className="inference-section">
      <div className="inference-header">
        <div>
          <p className="section-label">카메라 대체 시연</p>
          <h2>다개체 행동 탐지</h2>
          <p className="inference-description">
            영상 속 여러 소를 탐지하고 추적한 뒤,
            개체별 행동 이상 징후를 분석합니다.
          </p>
        </div>

        <button
          className="video-select-button"
          type="button"
          disabled={isRunning}
          onClick={() => {
            setIsSelectorOpen((previous) => !previous);
          }}
        >
          {selectedVideo ? "영상 변경" : "영상 선택"}
        </button>
      </div>

      {isSelectorOpen && (
        <div className="video-option-list">
          {DEMO_VIDEOS.map((video) => (
            <button
              className="video-option-card"
              type="button"
              key={video.id}
              onClick={() => handleSelectVideo(video)}
            >
              <div className="video-option-thumbnail">
                <span className="video-play-icon">▶</span>
              </div>

              <div className="video-option-info">
                <strong>{video.title}</strong>
                <p>{video.description}</p>
              </div>
            </button>
          ))}
        </div>
      )}

      {!selectedVideo && !isSelectorOpen && (
        <div className="inference-empty">
          
          <strong>분석할 축사 영상을 선택해 주세요.</strong>
          <p>
            영상 속 여러 소를 탐지하고 개체별 이상 징후를 표시합니다.
          </p>
        </div>
      )}

      {selectedVideo && (
        <div className="inference-workspace">
          <div className="inference-video-panel">
            {selectedVideo.videoUrl ? (
              <video
                key={selectedVideo.videoUrl}
                className="inference-video"
                src={selectedVideo.videoUrl}
                controls
                preload="metadata"
                playsInline
                onLoadedMetadata={() => {
                  console.log(
                    "결과 영상 로드 완료:",
                    selectedVideo.videoUrl,
                  );
                }}
                onError={(event) => {
                  console.error(
                    "영상 로드 실패:",
                    selectedVideo.videoUrl,
                    event.currentTarget.error,
                  );
                }}
              />
            ) : (
              <div className="video-placeholder">
                <strong>{selectedVideo.title}</strong>
                <p>추론 결과 영상 연결 예정</p>

                {jobStatus === "completed" && (
                  <div className="mock-detection-layer">
                    <div className="mock-box cow-one">
                      <span>ID 1 · 정상</span>
                    </div>

                    <div
                      className={`mock-box cow-two ${
                        selectedVideo.id === "abnormal"
                          ? "warning"
                          : ""
                      }`}
                    >
                      <span>
                        ID 2 ·{" "}
                        {selectedVideo.id === "abnormal"
                          ? "장시간 누움"
                          : "정상"}
                      </span>
                    </div>

                    <div
                      className={`mock-box cow-three ${
                        selectedVideo.id === "abnormal"
                          ? "warning"
                          : ""
                      }`}
                    >
                      <span>
                        ID 3 ·{" "}
                        {selectedVideo.id === "abnormal"
                          ? "이동량 감소"
                          : "반추 중"}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {isRunning && (
              <div className="inference-overlay">
                <div className="scanner-line" />
                <span>{STATUS_LABELS[jobStatus]}</span>
              </div>
            )}
          </div>

          <div className="inference-control-panel">
            <div className="selected-video-summary">
              <h3>{selectedVideo.title}</h3>
              <p>{selectedVideo.description}</p>
            </div>

            <div className="job-status-box">
              <div className="job-status-row">
                <span>처리 단계</span>
                <strong>{STATUS_LABELS[jobStatus]}</strong>
              </div>

              <div className="progress-track">
                <div
                  className="progress-value"
                  style={{ width: `${progress}%` }}
                />
              </div>

              <div className="progress-text">
                <span>{progress}%</span>
                <span>
                  {jobStatus === "detecting" &&
                    "소 객체 탐지"}
                  {jobStatus === "tracking" &&
                    "Track ID 유지"}
                  {jobStatus === "analyzing" &&
                    "개체별 행동 분석"}
                  {jobStatus === "completed" &&
                    "분석 완료"}
                </span>
              </div>
            </div>

            {jobStatus === "completed" &&
              selectedVideo.inferenceSummary && (
                <div className="behavior-summary">
                  <div className="behavior-summary-header">
                    <span>행동 분석 결과</span>
                    <strong>
                      {
                        selectedVideo.inferenceSummary
                          .processed_frames
                      }
                      프레임 분석
                    </strong>
                  </div>

                  <div className="behavior-summary-grid">
                    <div className="behavior-summary-item">
                      <span>섭식</span>
                      <strong>
                        {selectedVideo.inferenceSummary
                          .behavior_counts?.feeding ?? 0}
                      </strong>
                    </div>

                    <div className="behavior-summary-item">
                      <span>누움</span>
                      <strong>
                        {selectedVideo.inferenceSummary
                          .behavior_counts?.lying ?? 0}
                      </strong>
                    </div>

                    <div className="behavior-summary-item">
                      <span>기립</span>
                      <strong>
                        {selectedVideo.inferenceSummary
                          .behavior_counts?.standing ?? 0}
                      </strong>
                    </div>

                    <div className="behavior-summary-item">
                      <span>보행</span>
                      <strong>
                        {selectedVideo.inferenceSummary
                          .behavior_counts?.walking ?? 0}
                      </strong>
                    </div>
                  </div>

                  <p className="behavior-summary-note">
                    각 수치는 분석 프레임에서 Track ID별로
                    판정된 행동 라벨의 누적 횟수입니다.
                  </p>
                </div>
              )}

            {detectedCattle.length > 0 && (
              <div className="detected-cattle-list">
                <div className="detected-cattle-header">
                  <span>개체별 분석 결과</span>
                  <strong>
                    {detectedCattle.length}마리 탐지
                  </strong>
                </div>

                {detectedCattle.map((item) => (
                  <article
                    className={`detected-cattle-item ${item.status}`}
                    key={item.trackId}
                  >
                    <div>
                      <strong>{item.cattleId}</strong>
                      <span>Track ID {item.trackId}</span>
                    </div>

                    <div className="detected-behavior">
                      <strong>{item.behavior}</strong>
                      <span>
                        {Math.round(item.confidence * 100)}%
                      </span>
                    </div>
                  </article>
                ))}
              </div>
            )}

            <div className="inference-actions">
              <button
                className="start-inference-button"
                type="button"
                disabled={isRunning}
                onClick={handleStartInference}
              >
                {isRunning
                  ? STATUS_LABELS[jobStatus]
                  : jobStatus === "completed"
                    ? "다시 분석하기"
                    : "영상 분석 시작"}
              </button>

              <button
                className="reset-inference-button"
                type="button"
                disabled={isRunning}
                onClick={handleReset}
              >
                선택 해제
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export default DemoVideoSelector;







