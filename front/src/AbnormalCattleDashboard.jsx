import { useEffect, useMemo, useState } from "react";
import "./AbnormalCattleDashboard.css";
import DashboardAlertFeedback from "./DashboardAlertFeedback";
import BarnOperationsReport from "./BarnOperationsReport";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

const EMPTY_SUMMARY = {
  total: 0,
  normal: 0,
  warning: 0,
  danger: 0,
};

function formatDetectedAt(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";

  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul",
  }).format(date);
}

function formatUpdatedAt(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";

  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul",
  }).format(date);
}

function AbnormalCattleDashboard({ user }) {
  const [filter, setFilter] = useState("all");
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [cattleSummary, setCattleSummary] = useState(EMPTY_SUMMARY);
  const [abnormalCattle, setAbnormalCattle] = useState([]);
  const [recentAlerts, setRecentAlerts] = useState([]);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [activeVideo, setActiveVideo] = useState(null);
  const [isReportOpen, setIsReportOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const loadDashboard = async ({ silent = false } = {}) => {
      if (!silent) setIsLoading(true);
      setLoadError("");

      try {
        const response = await fetch(`${API_BASE_URL}/api/dashboard`, {
          credentials: "include",
        });
        const result = await response.json().catch(() => null);

        if (!response.ok) {
          throw new Error(
            result?.detail || "대시보드 데이터를 불러오지 못했습니다.",
          );
        }
        if (!result || typeof result !== "object") {
          throw new Error("대시보드 API 응답 형식이 올바르지 않습니다.");
        }
        if (cancelled) return;

        const summary = result?.summary || EMPTY_SUMMARY;
        setCattleSummary({
          total: Number(summary.total ?? 0),
          normal: Number(summary.normal ?? 0),
          warning: Number(summary.warning ?? 0),
          danger: Number(summary.danger ?? 0),
        });

        setAbnormalCattle(
          (result?.abnormal_cattle || []).map((item, index) => ({
            id: item.cattle_id ?? `abnormal-${index}`,
            cattleId: item.display_id ?? `COW-${item.cattle_id}`,
            status: item.severity,
            behavior: item.message || item.anomaly_type || "이상 행동",
            lastDetectedAt: formatDetectedAt(item.detected_at),
            anomalyType: item.anomaly_type,
            score: item.score,
            nationalId: item.national_id,
            earTagNumber: item.ear_tag_number,
            detectedAt: item.detected_at,
            anomalyEventId: item.anomaly_event_id,
            trackId: item.track_id,
            imageUrl: item.image_url ?? item.imageUrl,
            videoUrl: item.video_url ?? item.videoUrl,
            durationSeconds: item.duration_seconds ?? item.durationSeconds,
          })),
        );

        setRecentAlerts(
          (result?.recent_alerts || []).map((item, index) => ({
            id: `${item.cattle_id}-${item.detected_at ?? index}`,
            cattleId: item.display_id ?? `COW-${item.cattle_id}`,
            status: item.severity,
            behavior: item.message || item.anomaly_type || "이상 행동",
            time: formatDetectedAt(item.detected_at),
          })),
        );
        setUpdatedAt(result?.updated_at ?? null);
      } catch (error) {
        if (!cancelled) {
          setLoadError(
            error instanceof Error
              ? error.message
              : "대시보드 데이터를 불러오지 못했습니다.",
          );
        }
      } finally {
        if (!cancelled && !silent) setIsLoading(false);
      }
    };

    loadDashboard();
    const refreshTimer = window.setInterval(
      () => loadDashboard({ silent: true }),
      10000,
    );
    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
    };
  }, []);

  const filteredCattle = useMemo(() => {
    if (filter === "all") return abnormalCattle;
    return abnormalCattle.filter((cattle) => cattle.status === filter);
  }, [filter, abnormalCattle]);

  return (
    <section className="abnormal-dashboard">
      <div className="abnormal-dashboard-header">
        <div>
          <span className="dashboard-label">실시간 개체 관리</span>
          <h2>이상 개체 대시보드</h2>
          <p>행동 변화가 감지된 개체를 확인합니다.</p>
          {loadError && <p role="alert">{loadError}</p>}
        </div>
        <div className="dashboard-header-actions">
          <button className="dashboard-report-button" type="button" onClick={() => setIsReportOpen(true)}>
            보고서 만들기
          </button>
          <span className="dashboard-update-time">
            {isLoading
              ? "데이터 불러오는 중"
              : `최종 갱신 ${formatUpdatedAt(updatedAt)}`}
          </span>
        </div>
      </div>

      <div className="dashboard-summary-grid">
        {[
          ["전체 개체", cattleSummary.total, ""],
          ["정상", cattleSummary.normal, "normal"],
          ["주의", cattleSummary.warning, "warning"],
          ["위험", cattleSummary.danger, "danger"],
        ].map(([label, value, className]) => (
          <article className={`dashboard-summary-card ${className}`} key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>마리</small>
          </article>
        ))}
      </div>

      <div className="dashboard-priority-card">
        <div className="dashboard-priority-status">
          <span className="cattle-status-dot danger" />
          <div>
            <strong>지금 확인할 위험 개체</strong>
            <span>
              위험 {cattleSummary.danger}마리 · 주의 {cattleSummary.warning}마리
            </span>
          </div>
        </div>
        <button
          className="dashboard-details-button"
          type="button"
          aria-expanded={isDetailsOpen}
          aria-controls="dashboard-details"
          onClick={() => setIsDetailsOpen((previous) => !previous)}
        >
          {isDetailsOpen ? "상세 현황 접기" : "상세 현황 보기"}
          <span aria-hidden="true">{isDetailsOpen ? "▲" : "›"}</span>
        </button>
      </div>

      <div
        id="dashboard-details"
        className={`dashboard-content-grid ${
          isDetailsOpen ? "is-open" : "is-collapsed"
        }`}
      >
        <div className="dashboard-panel">
          <div className="dashboard-panel-header">
            <div>
              <h3>이상 개체 목록</h3>
              <p>위험도에 따라 개체를 분류합니다.</p>
            </div>
            <div className="dashboard-filter-buttons">
              {[["all", "전체"], ["danger", "위험"], ["warning", "주의"]].map(
                ([value, label]) => (
                  <button
                    type="button"
                    className={filter === value ? "active" : ""}
                    onClick={() => setFilter(value)}
                    key={value}
                  >
                    {label}
                  </button>
                ),
              )}
            </div>
          </div>

          <div className="abnormal-cattle-list">
            {!filteredCattle.length && (
              <p className="dashboard-empty-state">
                현재 조건에 해당하는 이상 개체가 없습니다.
              </p>
            )}
            {filteredCattle.map((cattle) => (
              <article
                className={`abnormal-cattle-item ${cattle.status}`}
                key={cattle.id}
              >
                <div className="cattle-status-area">
                  <span className={`cattle-status-dot ${cattle.status}`} />
                  <strong>{cattle.cattleId}</strong>
                </div>
                <span className="cattle-behavior">
                  {cattle.behavior}
                  {Number(cattle.durationSeconds) > 0 && (
                    <small> · {Math.round(Number(cattle.durationSeconds))}초 연속</small>
                  )}
                </span>
                <time>{cattle.lastDetectedAt}</time>
                {(cattle.imageUrl || cattle.videoUrl) && (
                  <div className="dashboard-event-media">
                    {cattle.imageUrl && (
                      <a href={cattle.imageUrl} target="_blank" rel="noreferrer">
                        {cattle.cattleId} 대표 이미지
                      </a>
                    )}
                    {cattle.videoUrl && (
                      <button
                        className="dashboard-media-button"
                        type="button"
                        onClick={() =>
                          setActiveVideo({
                            url: cattle.videoUrl,
                            label: `${cattle.cattleId} 감지 영상`,
                          })
                        }
                      >
                        감지 영상 보기
                      </button>
                    )}
                  </div>
                )}
                <DashboardAlertFeedback cattle={cattle} />
              </article>
            ))}
          </div>
        </div>

        <aside className="dashboard-panel recent-alert-panel">
          <div className="dashboard-panel-header">
            <div>
              <h3>최근 이상 알림</h3>
              <p>최근 감지된 주요 행동입니다.</p>
            </div>
          </div>
          <div className="recent-alert-list">
            {!recentAlerts.length && (
              <p className="dashboard-empty-state">최근 이상 알림이 없습니다.</p>
            )}
            {recentAlerts.map((alert) => (
              <article
                className={`recent-alert-item ${alert.status}`}
                key={alert.id}
              >
                <span className={`cattle-status-dot ${alert.status}`} />
                <div>
                  <strong>{alert.cattleId}</strong>
                  <p>{alert.behavior}</p>
                </div>
                <time>{alert.time}</time>
              </article>
            ))}
          </div>
        </aside>
      </div>
      {activeVideo && (
        <div
          className="dashboard-video-modal"
          role="dialog"
          aria-modal="true"
          aria-label={activeVideo.label}
          onClick={() => setActiveVideo(null)}
        >
          <div
            className="dashboard-video-modal-card"
            onClick={(event) => event.stopPropagation()}
          >
            <div>
              <strong>{activeVideo.label}</strong>
              <button type="button" onClick={() => setActiveVideo(null)}>
                닫기
              </button>
            </div>
            <video src={activeVideo.url} controls autoPlay playsInline>
              이 브라우저에서는 영상을 재생할 수 없습니다.
            </video>
          </div>
        </div>
      )}
      <BarnOperationsReport
        open={isReportOpen}
        onClose={() => setIsReportOpen(false)}
        cattle={abnormalCattle}
        updatedAt={updatedAt}
        isGuest={user?.loginType === "guest"}
      />
    </section>
  );
}

export default AbnormalCattleDashboard;
