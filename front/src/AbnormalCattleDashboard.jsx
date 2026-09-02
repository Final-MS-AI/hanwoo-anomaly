import { useCallback, useEffect, useMemo, useState } from "react";
import "./AbnormalCattleDashboard.css";
import DashboardAlertFeedback from "./DashboardAlertFeedback";
import BarnOperationsReport from "./BarnOperationsReport";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

const PAGE_SIZE = 5;
const FILTERS = [
  ["all", "전체"],
  ["warning", "주의"],
  ["normal", "이상 징후 없음"],
  ["insufficient", "분석 데이터 부족"],
];
const STATUS_ORDER = { warning: 0, insufficient: 1, normal: 2 };
const DEFAULT_ATTENTION_POLICY = {
  baselineRequiredValidDays: 10,
  feedBunkWarningDecreasePercent: 18,
  lyingWarningDecreasePercent: 30,
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

function formatAnalysisDate(value) {
  if (!value) return "-";
  const date = new Date(`${value}T00:00:00+09:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    timeZone: "Asia/Seoul",
  }).format(date);
}

function formatMinutes(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  if (numeric >= 60) {
    const hours = Math.floor(numeric / 60);
    const minutes = Math.round(numeric % 60);
    return `${hours}시간 ${minutes}분`;
  }
  return `${Math.round(numeric)}분`;
}

function formatPercent(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${numeric.toFixed(1)}%` : "-";
}

function formatChange(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  if (numeric === 0) return "변화 없음";
  return `${numeric > 0 ? "▲" : "▼"}${Math.abs(numeric).toFixed(1)}%`;
}

function normalizeStatus(value) {
  const status = String(value || "").toLowerCase();
  if (["warning", "caution", "주의"].includes(status)) return "warning";
  if (
    [
      "insufficient",
      "insufficient_data",
      "insufficient_baseline",
      "data_insufficient",
      "분석 데이터 부족",
    ].includes(status)
  ) {
    return "insufficient";
  }
  return "normal";
}

function behaviorLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  if (!key) return "행동 정보 없음";
  if (key.includes("standing")) return "서 있음";
  if (key.includes("head_down")) return "서 있음";
  if (key.includes("lying")) return "누워 있음";
  if (key.includes("walking")) return "걷는 중";
  if (
    key.includes("feeding") ||
    key.includes("eating") ||
    key.includes("섭식")
  ) {
    return "섭식 중";
  }
  return value;
}

function metricByKey(cattle, key) {
  return cattle?.metrics?.find((metric) => metric.key === key) || null;
}

function analysisReasonText(cattle) {
  if (!cattle) return "";
  if (cattle.isBaselineCollecting) {
    return "개체별 행동 비교를 위한 기준 데이터를 수집하고 있습니다.";
  }
  if (cattle.status === "insufficient") {
    if (cattle.source === "missing") return "해당 분석일의 분석 결과가 없습니다.";
    return "분석에 필요한 데이터가 충분하지 않습니다.";
  }
  const feedBunk = metricByKey(cattle, "feed_bunk");
  const lying = metricByKey(cattle, "lying");
  const feedWarning = Boolean(feedBunk?.is_warning_metric);
  const lyingWarning = Boolean(lying?.is_warning_metric);
  if (feedWarning && lyingWarning) return "최근 평균보다 급이대 체류와 누움 시간이 모두 감소했습니다.";
  if (feedWarning) return "최근 평균보다 급이대 체류가 감소했습니다.";
  if (lyingWarning) return "최근 평균보다 누워 있는 시간이 감소했습니다.";
  return "현재 주의 기준에 해당하는 행동 감소가 확인되지 않았습니다.";
}

function insufficientDetailText(cattle) {
  if (!cattle) return "분석에 필요한 데이터가 충분하지 않습니다.";
  if (cattle.source === "missing") return "해당 분석일의 분석 결과가 없습니다.";
  if (cattle.detail) return cattle.detail;
  if (cattle.baselineValidDays < cattle.baselineRequiredDays) {
    return `비교 기준 계산에 필요한 유효 관찰일이 부족합니다. (${cattle.baselineValidDays}일 / ${cattle.baselineRequiredDays}일)`;
  }
  return "분석에 필요한 유효 관찰시간이 충분하지 않습니다.";
}

function cowNumber(value) {
  const match = String(value || "").match(/(\d+)$/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function normalizeAnalysisItem(item, index) {
  const displayId =
    item.display_id ||
    item.cattleId ||
    item.cattle_id ||
    `COW-${String(index + 1).padStart(3, "0")}`;
  const rawStatus = String(item.status || item.severity || "").trim().toLowerCase();
  const source = item.source || "missing";

  return {
    id: item.id || item.analysis_id || `${displayId}-${item.analysis_date || index}`,
    cattleId: displayId,
    nationalId: item.national_id || item.nationalId || null,
    status: normalizeStatus(rawStatus),
    rawStatus,
    isBaselineCollecting: rawStatus === "insufficient_baseline" && source !== "missing",
    streakDays: Number(item.streak_days ?? item.streakDays ?? 0),
    primaryMetric:
      item.primary_metric || item.primaryMetric || "최근 분석에서 유의한 행동 변화 없음",
    detail: item.detail || item.insufficient_reason || null,
    changeRatio:
      item.change_ratio === null || item.change_ratio === undefined
        ? null
        : Number(item.change_ratio),
    analysisDate: item.analysis_date || item.analysisDate || null,
    baselineValidDays: Number(item.baseline_valid_days ?? item.baselineValidDays ?? 0),
    baselineRequiredDays: Number(
      item.baseline_required_days ?? item.baselineRequiredDays ?? 10,
    ),
    validObservationMinutes: Number(
      item.valid_observation_minutes ?? item.validObservationMinutes ?? 0,
    ),
    metrics: Array.isArray(item.metrics) ? item.metrics : [],
    warningReasons: Array.isArray(item.warning_reasons) ? item.warning_reasons : [],
    source,
  };
}

function normalizeRecentBehavior(item, index) {
  const displayId =
    item.display_id ||
    item.cattleId ||
    (item.national_id?.startsWith?.("99")
      ? `COW-${item.national_id.slice(-3)}`
      : item.national_id) ||
    `COW-${item.cattle_id || index}`;

  return {
    id: item.id || item.anomaly_event_id || `recent-${index}`,
    cattleId: displayId,
    nationalId: item.national_id || null,
    behavior: item.behavior || item.anomaly_type || item.message || "",
    behaviorLabel: behaviorLabel(
      item.behavior || item.anomaly_type || item.behavior_label || item.message,
    ),
    status: item.status || item.severity || "warning",
    detectedAt: item.detected_at || null,
    lastDetectedAt: formatDetectedAt(item.detected_at),
    anomalyEventId: item.anomaly_event_id || item.id || null,
    trackId: item.track_id || null,
    imageUrl: item.image_url ?? item.imageUrl ?? null,
    videoUrl: item.video_url ?? item.videoUrl ?? null,
  };
}

function Pagination({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null;
  return (
    <nav className="dashboard-pagination" aria-label="목록 페이지 이동">
      <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        이전
      </button>
      <span>{page} / {totalPages}</span>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onChange(page + 1)}
      >
        다음
      </button>
    </nav>
  );
}

function StatusBadge({ cattle }) {
  if (cattle.status === "warning") {
    return (
      <span className="analysis-status-badge warning">
        {cattle.streakDays > 1 ? `주의 · ${cattle.streakDays}일 연속` : "주의"}
      </span>
    );
  }
  if (cattle.isBaselineCollecting) {
    return <span className="analysis-status-badge collecting">기준 데이터 수집 중</span>;
  }
  if (cattle.status === "insufficient") {
    return <span className="analysis-status-badge insufficient">분석 데이터 부족</span>;
  }
  return <span className="analysis-status-badge normal">이상 징후 없음</span>;
}

function RecentBehaviorCard({ cattle, onOpenImage, onOpenVideo, isGuest = false }) {
  return (
    <article className="recent-behavior-card">
      <div className="recent-behavior-top">
        <strong>{cattle.cattleId}</strong>
        {!isGuest && <time>{cattle.lastDetectedAt}</time>}
      </div>
      <p><span>{isGuest ? "예시 행동 :" : "최근 감지 행동 :"}</span> {cattle.behaviorLabel}</p>
      {!isGuest && (
        <>
          <div className="recent-behavior-actions">
            {cattle.imageUrl ? (
              <button
                type="button"
                className="dashboard-outline-button"
                onClick={() =>
                  onOpenImage({ url: cattle.imageUrl, label: `${cattle.cattleId} 대표 이미지` })
                }
              >
                대표 이미지
              </button>
            ) : (
              <button type="button" className="dashboard-outline-button" disabled>
                대표 이미지
              </button>
            )}
            <button
              className="dashboard-outline-button"
              type="button"
              disabled={!cattle.videoUrl}
              onClick={() =>
                cattle.videoUrl &&
                onOpenVideo({ url: cattle.videoUrl, label: `${cattle.cattleId} 감지 영상` })
              }
            >
              감지 영상
            </button>
            <DashboardAlertFeedback cattle={cattle} />
          </div>
        </>
      )}
    </article>
  );
}

function AbnormalCattleDashboard({ user }) {
  const [filter, setFilter] = useState("all");
  const [isDetailsOpen, setIsDetailsOpen] = useState(true);
  const [analysisSearch, setAnalysisSearch] = useState("");
  const [recentSearch, setRecentSearch] = useState("");
  const [analysisPage, setAnalysisPage] = useState(1);
  const [recentPage, setRecentPage] = useState(1);
  const [analysisCattle, setAnalysisCattle] = useState([]);
  const [analysisDate, setAnalysisDate] = useState(null);
  const [analysisPolicy, setAnalysisPolicy] = useState(DEFAULT_ATTENTION_POLICY);
  const [mobilePanel, setMobilePanel] = useState("analysis");
  const [recentBehavior, setRecentBehavior] = useState([]);
  const [selectedCattle, setSelectedCattle] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [activeImage, setActiveImage] = useState(null);
  const [activeVideo, setActiveVideo] = useState(null);
  const [activeAnalysis, setActiveAnalysis] = useState(null);
  const [isReportOpen, setIsReportOpen] = useState(false);

  const loadDashboard = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setIsLoading(true);
    setLoadError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/dashboard`, {
        credentials: "include",
        cache: "no-store",
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(result?.detail || "대시보드 데이터를 불러오지 못했습니다.");
      }
      if (!result || typeof result !== "object") {
        throw new Error("대시보드 API 응답 형식이 올바르지 않습니다.");
      }

      const apiAnalysis = Array.isArray(result.analysis_cattle)
        ? result.analysis_cattle
        : [];
      setAnalysisCattle(apiAnalysis.map(normalizeAnalysisItem));
      setAnalysisDate(result.analysis_date || apiAnalysis[0]?.analysis_date || null);
      setAnalysisPolicy({
        baselineRequiredValidDays: Number(
          result.analysis_policy?.baseline_required_valid_days ??
            DEFAULT_ATTENTION_POLICY.baselineRequiredValidDays,
        ),
        feedBunkWarningDecreasePercent: Number(
          result.analysis_policy?.feed_bunk_warning_decrease_percent ??
            DEFAULT_ATTENTION_POLICY.feedBunkWarningDecreasePercent,
        ),
        lyingWarningDecreasePercent: Number(
          result.analysis_policy?.lying_warning_decrease_percent ??
            DEFAULT_ATTENTION_POLICY.lyingWarningDecreasePercent,
        ),
      });

      const recentSource = Array.isArray(result.recent_behavior)
        ? result.recent_behavior
        : (result.abnormal_cattle || []).filter(
            (item) => item.device_id || item.camera_id,
          );
      setRecentBehavior(recentSource.map(normalizeRecentBehavior));
      setUpdatedAt(result.updated_at || new Date().toISOString());
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "대시보드 데이터를 불러오지 못했습니다.",
      );
      setAnalysisCattle([]);
      setAnalysisDate(null);
      setAnalysisPolicy(DEFAULT_ATTENTION_POLICY);
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
    const refreshTimer = window.setInterval(
      () => loadDashboard({ silent: true }),
      10000,
    );
    return () => window.clearInterval(refreshTimer);
  }, [loadDashboard]);

  useEffect(() => setAnalysisPage(1), [filter, analysisSearch]);
  useEffect(() => setRecentPage(1), [recentSearch]);

  const cattleSummary = useMemo(() => {
    const summary = { total: analysisCattle.length, normal: 0, warning: 0, insufficient: 0 };
    analysisCattle.forEach((item) => {
      if (item.status === "warning") summary.warning += 1;
      else if (item.status === "insufficient") summary.insufficient += 1;
      else summary.normal += 1;
    });
    return summary;
  }, [analysisCattle]);

  const analysisCounts = useMemo(
    () => ({
      all: cattleSummary.total,
      warning: cattleSummary.warning,
      normal: cattleSummary.normal,
      insufficient: cattleSummary.insufficient,
    }),
    [cattleSummary],
  );

  const filteredAnalysis = useMemo(() => {
    const search = analysisSearch.trim().toLowerCase();
    return analysisCattle
      .filter((item) => filter === "all" || item.status === filter)
      .filter(
        (item) =>
          !search ||
          item.cattleId.toLowerCase().includes(search) ||
          String(item.nationalId || "").toLowerCase().includes(search),
      )
      .sort(
        (a, b) =>
          (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) ||
          b.streakDays - a.streakDays ||
          cowNumber(a.cattleId) - cowNumber(b.cattleId),
      );
  }, [analysisCattle, analysisSearch, filter]);

  const analysisTotalPages = Math.max(1, Math.ceil(filteredAnalysis.length / PAGE_SIZE));
  const pagedAnalysis = filteredAnalysis.slice(
    (analysisPage - 1) * PAGE_SIZE,
    analysisPage * PAGE_SIZE,
  );
  useEffect(() => {
    if (analysisPage > analysisTotalPages) setAnalysisPage(analysisTotalPages);
  }, [analysisPage, analysisTotalPages]);

  const filteredRecent = useMemo(() => {
    const search = recentSearch.trim().toLowerCase();
    return recentBehavior
      .filter(
        (item) =>
          !search ||
          item.cattleId.toLowerCase().includes(search) ||
          String(item.nationalId || "").toLowerCase().includes(search),
      )
      .sort(
        (a, b) =>
          cowNumber(a.cattleId) - cowNumber(b.cattleId) ||
          String(b.detectedAt || "").localeCompare(String(a.detectedAt || "")),
      );
  }, [recentBehavior, recentSearch]);

  const recentTotalPages = Math.max(1, Math.ceil(filteredRecent.length / PAGE_SIZE));
  const pagedRecent = filteredRecent.slice(
    (recentPage - 1) * PAGE_SIZE,
    recentPage * PAGE_SIZE,
  );
  useEffect(() => {
    if (recentPage > recentTotalPages) setRecentPage(recentTotalPages);
  }, [recentPage, recentTotalPages]);

  const selectedRecent = useMemo(() => {
    if (!selectedCattle) return null;
    return recentBehavior.find(
      (item) =>
        (selectedCattle.nationalId && item.nationalId === selectedCattle.nationalId) ||
        item.cattleId === selectedCattle.cattleId,
    ) || null;
  }, [recentBehavior, selectedCattle]);

  const hasRecentBehavior = (cattle) =>
    recentBehavior.some(
      (item) =>
        (cattle.nationalId && item.nationalId === cattle.nationalId) ||
        item.cattleId === cattle.cattleId,
    );

  const showCurrentState = (cattle) => {
    if (!hasRecentBehavior(cattle)) return;
    setSelectedCattle(cattle);
    setIsDetailsOpen(true);
    setMobilePanel("recent");
  };

  const isGuest = user?.loginType === "guest";

  const reportCattle = useMemo(
    () =>
      analysisCattle.map((item) => ({
        id: item.id,
        cattleId: item.cattleId,
        status: item.status,
        behavior: item.primaryMetric,
        detectedAt: item.analysisDate ? `${item.analysisDate}T12:00:00+09:00` : null,
        lastDetectedAt: item.analysisDate ? formatAnalysisDate(item.analysisDate) : "-",
        analysisDate: item.analysisDate,
        streakDays: item.streakDays,
        metrics: item.metrics,
        baselineValidDays: item.baselineValidDays,
        baselineRequiredDays: item.baselineRequiredDays,
        validObservationMinutes: item.validObservationMinutes,
        source: item.source,
        rawStatus: item.rawStatus,
        isBaselineCollecting: item.isBaselineCollecting,
        detail: item.detail,
      })),
    [analysisCattle],
  );

  return (
    <section className="abnormal-dashboard">
      <div className="abnormal-dashboard-header">
        <div>
          <span className="dashboard-label">실시간 개체 관리</span>
          <h2>이상 개체 대시보드</h2>
          <p>최근 완료 분석 결과와 오늘의 개체 행동을 한눈에 확인합니다.</p>
          {loadError && <p className="dashboard-load-error" role="alert">{loadError}</p>}
        </div>

        <div className="dashboard-header-actions">
          <button
            className="dashboard-report-button"
            type="button"
            onClick={() => setIsReportOpen(true)}
          >
            보고서 만들기
          </button>
          <div className="dashboard-refresh-group">
            <button
              className="dashboard-refresh-button"
              type="button"
              onClick={() => loadDashboard()}
              disabled={isLoading}
              aria-label="대시보드 데이터 새로고침"
            >
              {isLoading ? "↻ 갱신 중..." : `↻ 최종 갱신 ${formatUpdatedAt(updatedAt)}`}
            </button>
          </div>
        </div>
      </div>

      <div className="dashboard-summary-grid">
        <article className="dashboard-summary-card">
          <span>등록 개체</span>
          <div><strong>{cattleSummary.total}</strong><small>마리</small></div>
        </article>
        <article className="dashboard-summary-card normal">
          <span>이상 징후 없음</span>
          <div><strong>{cattleSummary.normal}</strong><small>마리</small></div>
        </article>
        <article className="dashboard-summary-card warning">
          <span>주의 개체</span>
          <div><strong>{cattleSummary.warning}</strong><small>마리</small></div>
        </article>
        <article className="dashboard-summary-card insufficient">
          <span>분석 데이터 부족</span>
          <div><strong>{cattleSummary.insufficient}</strong><small>마리</small></div>
        </article>
      </div>

      <div className="dashboard-priority-card">
        <div className="dashboard-priority-status">
          <span className={`dashboard-priority-dot ${cattleSummary.warning ? "has-warning" : ""}`} aria-hidden="true" />
          <div>
            <strong>지금 확인할 주의 개체</strong>
            <span>
              주의 개체 {cattleSummary.warning}마리 · 분석 데이터 부족 {cattleSummary.insufficient}마리
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
          <span aria-hidden="true">{isDetailsOpen ? "▲" : "▼"}</span>
        </button>
      </div>

      {isDetailsOpen && (
        <div className="dashboard-mobile-tabs" role="tablist" aria-label="대시보드 상세 영역 선택">
          <button
            type="button"
            role="tab"
            aria-selected={mobilePanel === "analysis"}
            className={mobilePanel === "analysis" ? "active" : ""}
            onClick={() => setMobilePanel("analysis")}
          >
            분석 결과
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobilePanel === "recent"}
            className={mobilePanel === "recent" ? "active" : ""}
            onClick={() => setMobilePanel("recent")}
          >
            오늘 상태
          </button>
        </div>
      )}

      <div
        id="dashboard-details"
        className={`dashboard-content-grid ${isDetailsOpen ? "is-open" : "is-collapsed"}`}
      >
        <section className={`dashboard-panel analysis-panel ${mobilePanel === "analysis" ? "mobile-active" : "mobile-hidden"}`}>
          <div className="dashboard-panel-heading">
            <div>
              <div className="dashboard-panel-title-row">
                <h3>분석 결과 개체 목록</h3>
                {isGuest && <span className="dashboard-demo-badge">예시 데이터</span>}
              </div>
              <p>
                {isGuest
                  ? "게스트 체험을 위해 구성된 예시 분석 데이터입니다."
                  : analysisDate
                    ? `${formatAnalysisDate(analysisDate)} 행동 분석 결과입니다.`
                    : "등록 개체의 일별 행동 분석 상태를 확인합니다."}
              </p>
            </div>
          </div>


          <label className="dashboard-search">
            <span className="sr-only">분석 결과 개체 검색</span>
            <input
              type="search"
              value={analysisSearch}
              onChange={(event) => setAnalysisSearch(event.target.value)}
              placeholder="개체 번호 검색"
            />
          </label>

          <div className="dashboard-filter-buttons">
            {FILTERS.map(([value, label]) => (
              <button
                type="button"
                className={filter === value ? "active" : ""}
                onClick={() => setFilter(value)}
                key={value}
              >
                {label}({analysisCounts[value]})
              </button>
            ))}
          </div>

          <div className="analysis-cattle-list">
            {!pagedAnalysis.length && (
              <div className="dashboard-empty-state">
                {filter === "warning"
                  ? "현재 주의로 분류된 개체가 없습니다."
                  : "현재 조건에 해당하는 개체가 없습니다."}
              </div>
            )}

            {pagedAnalysis.map((cattle) => {
              const canShowCurrentState = hasRecentBehavior(cattle);
              return (
              <article
                className={`analysis-cattle-card ${cattle.status} ${cattle.isBaselineCollecting ? "collecting" : ""} ${canShowCurrentState ? "selectable" : ""}`}
                key={cattle.id}
                role={canShowCurrentState ? "button" : undefined}
                tabIndex={canShowCurrentState ? 0 : undefined}
                onClick={() => canShowCurrentState && showCurrentState(cattle)}
                onKeyDown={(event) => {
                  if (
                    canShowCurrentState &&
                    (event.key === "Enter" || event.key === " ")
                  ) {
                    event.preventDefault();
                    showCurrentState(cattle);
                  }
                }}
              >
                <div className="analysis-cattle-top">
                  <strong>{cattle.cattleId}</strong>
                  <StatusBadge cattle={cattle} />
                  {canShowCurrentState && (
                    <span className="analysis-link-hint">현재 상태 보기 →</span>
                  )}
                </div>

                <div className="analysis-cattle-body">
                  <div>
                    <p className="analysis-primary-metric">
                      {cattle.isBaselineCollecting
                        ? "개체별 행동 비교를 위한 기준 데이터를 수집하고 있습니다."
                        : cattle.status === "insufficient"
                          ? "분석에 필요한 데이터가 충분하지 않습니다."
                          : cattle.primaryMetric}
                    </p>
                    {cattle.isBaselineCollecting ? (
                      <p className="analysis-insufficient-detail">
                        유효 관찰일 {cattle.baselineValidDays}일 / {cattle.baselineRequiredDays}일
                      </p>
                    ) : cattle.status !== "insufficient" && Number.isFinite(cattle.changeRatio) ? (
                      <p className="analysis-change">
                        최근 평균 대비 <strong>{formatChange(cattle.changeRatio)}</strong>
                      </p>
                    ) : null}
                  </div>
                  <button
                    className="dashboard-outline-button"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      setActiveAnalysis(cattle);
                    }}
                  >
                    상세 분석
                  </button>
                </div>
              </article>
              );
            })}
          </div>

          <Pagination page={analysisPage} totalPages={analysisTotalPages} onChange={setAnalysisPage} />
        </section>

        <aside className={`dashboard-panel recent-behavior-panel ${mobilePanel === "recent" ? "mobile-active" : "mobile-hidden"}`}>
          <div className="dashboard-panel-heading recent-heading">
            <div>
              <div className="dashboard-panel-title-row">
                <h3>오늘 실시간 개체 상태</h3>
                {isGuest && <span className="dashboard-demo-badge">예시 데이터</span>}
              </div>
              <p>
                {isGuest
                  ? "게스트 체험을 위한 예시 행동 데이터입니다."
                  : "오늘 영상에서 확인된 개체 행동입니다."}
              </p>
            </div>

          </div>

          {selectedCattle ? (
            <div className="selected-realtime-view">
              <button
                className="dashboard-back-list-button"
                type="button"
                onClick={() => setSelectedCattle(null)}
              >
                ← 전체 개체 보기
              </button>
              <div className="selected-realtime-title">
                <span>선택한 개체</span>
                <strong>{selectedCattle.cattleId}</strong>
                <StatusBadge cattle={selectedCattle} />
              </div>
              {selectedRecent ? (
                <RecentBehaviorCard cattle={selectedRecent} onOpenImage={setActiveImage} onOpenVideo={setActiveVideo} isGuest={isGuest} />
              ) : (
                <div className="selected-realtime-empty">
                  <strong>표시 가능한 실시간 행동 이벤트가 없습니다.</strong>
                  <p>
                    오늘 저장된 실시간 행동 이벤트에서 {selectedCattle.cattleId}를 찾지 못했습니다.
                    이 메시지는 해당 개체가 카메라에 없다는 의미는 아닙니다.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <>
              <label className="dashboard-search">
                <span className="sr-only">최근 행동 개체 검색</span>
                <input
                  type="search"
                  value={recentSearch}
                  onChange={(event) => setRecentSearch(event.target.value)}
                  placeholder="개체 번호 검색"
                />
              </label>
              <div className="recent-behavior-list">
                {!pagedRecent.length && (
                  <div className="dashboard-empty-state">오늘 확인된 개체 행동이 없습니다.</div>
                )}
                {pagedRecent.map((cattle) => (
                  <RecentBehaviorCard
                    cattle={cattle}
                    onOpenImage={setActiveImage}
                    onOpenVideo={setActiveVideo}
                    isGuest={isGuest}
                    key={cattle.id}
                  />
                ))}
              </div>
              <Pagination page={recentPage} totalPages={recentTotalPages} onChange={setRecentPage} />
            </>
          )}
        </aside>
      </div>

      {activeAnalysis && (
        <div
          className="dashboard-analysis-modal"
          role="dialog"
          aria-modal="true"
          aria-label={`${activeAnalysis.cattleId} 상세 분석`}
          onClick={() => setActiveAnalysis(null)}
        >
          <div className="dashboard-analysis-modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="dashboard-analysis-modal-header">
              <div className="dashboard-analysis-modal-title-row">
                <div>
                  <span>분석일 {formatAnalysisDate(activeAnalysis.analysisDate)}</span>
                  <strong>{activeAnalysis.cattleId}</strong>
                </div>
                <StatusBadge cattle={activeAnalysis} />
              </div>
              <button type="button" onClick={() => setActiveAnalysis(null)}>닫기</button>
            </div>

            <div className="dashboard-analysis-modal-summary">
              <strong>{analysisReasonText(activeAnalysis)}</strong>
              {activeAnalysis.status === "warning" && Number.isFinite(activeAnalysis.changeRatio) && (
                <p>가장 큰 변화 {formatChange(activeAnalysis.changeRatio)}</p>
              )}
            </div>

            {activeAnalysis.isBaselineCollecting ? (
              <>
                <div className="dashboard-analysis-collecting-box">
                  <strong>기준 데이터 수집 중 · {activeAnalysis.baselineValidDays}일 / {activeAnalysis.baselineRequiredDays}일</strong>
                  <p>개체별 행동 비교를 위한 기준 데이터를 수집하고 있습니다.</p>
                </div>

                <div className="dashboard-analysis-context-grid">
                  <div><span>분석일 유효 관찰시간</span><strong>{formatMinutes(activeAnalysis.validObservationMinutes)}</strong></div>
                  <div><span>기준 데이터 수집</span><strong>{activeAnalysis.baselineValidDays}일 / {activeAnalysis.baselineRequiredDays}일</strong></div>
                </div>

                <div className="dashboard-analysis-section-heading">
                  <strong>분석일 행동 지표</strong>
                  <span>기준 데이터가 충분히 쌓이기 전에도 분석일의 행동값은 계속 계산·저장합니다.</span>
                </div>
                <div className="dashboard-analysis-metrics collecting-metrics">
                  {[metricByKey(activeAnalysis, "feed_bunk"), metricByKey(activeAnalysis, "lying")]
                    .filter(Boolean)
                    .map((metric) => (
                      <div key={metric.key}>
                        <strong className="dashboard-analysis-metric-title">{metric.label}</strong>
                        <div className="dashboard-analysis-metric-values collecting-values">
                          <div>
                            <span>분석일</span>
                            <b>{formatPercent(metric.current_ratio_percent)}</b>
                            <small>{formatMinutes(metric.duration_min)}</small>
                          </div>
                        </div>
                      </div>
                    ))}
                </div>

                <div className="dashboard-analysis-section-heading reference-heading">
                  <strong>참고 행동</strong>
                  <span>분석일의 관찰값입니다.</span>
                </div>
                <div className="dashboard-analysis-reference-grid">
                  {[metricByKey(activeAnalysis, "standing"), metricByKey(activeAnalysis, "walking")]
                    .filter(Boolean)
                    .map((metric) => (
                      <div key={metric.key}>
                        <strong>{metric.key === "standing" ? "서 있음" : "걷는 중"}</strong>
                        <span>{formatPercent(metric.current_ratio_percent)}</span>
                        <small>{formatMinutes(metric.duration_min)}</small>
                      </div>
                    ))}
                </div>

                <div className="dashboard-analysis-collecting-note">
                  직전 {activeAnalysis.baselineRequiredDays}개 유효 관찰일이 확보되면 정상/주의 판정을 시작합니다.
                </div>

                <div className="dashboard-analysis-policy-copy">
                  <strong>기준 확보 후 적용되는 주의 판단 기준</strong>
                  <ul>
                    <li>급이대 체류비율이 대상일을 제외한 직전 {analysisPolicy.baselineRequiredValidDays}개 유효 관찰일 평균보다 {analysisPolicy.feedBunkWarningDecreasePercent}% 이상 감소</li>
                    <li>누움비율이 대상일을 제외한 직전 {analysisPolicy.baselineRequiredValidDays}개 유효 관찰일 평균보다 {analysisPolicy.lyingWarningDecreasePercent}% 이상 감소</li>
                    <li>두 조건 중 하나 이상에 해당하면 주의로 표시합니다.</li>
                  </ul>
                  <small>행동 변화를 확인하기 위한 기준이며, 질병 진단 기준은 아닙니다.</small>
                </div>
              </>
            ) : activeAnalysis.status === "insufficient" ? (
              <>
                <div className="dashboard-analysis-detail-box">
                  <strong>분석 데이터 부족</strong>
                  <p>{insufficientDetailText(activeAnalysis)}</p>
                </div>
                {activeAnalysis.source !== "missing" && (
                  <div className="dashboard-analysis-context-grid">
                    <div><span>분석일 유효 관찰시간</span><strong>{formatMinutes(activeAnalysis.validObservationMinutes)}</strong></div>
                    <div><span>기준 데이터 수집</span><strong>{activeAnalysis.baselineValidDays}일 / {activeAnalysis.baselineRequiredDays}일</strong></div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="dashboard-analysis-context-grid">
                  <div><span>분석일 유효 관찰시간</span><strong>{formatMinutes(activeAnalysis.validObservationMinutes)}</strong></div>
                  <div><span>비교 기준</span><strong>직전 {activeAnalysis.baselineRequiredDays}개 유효 관찰일 평균</strong></div>
                </div>

                <div className="dashboard-analysis-section-heading">
                  <strong>주의 판정 핵심 지표</strong>
                  <span>분석일 값과 직전 10개 유효 관찰일 평균을 비교합니다.</span>
                </div>
                <div className="dashboard-analysis-metrics core-metrics">
                  {[metricByKey(activeAnalysis, "feed_bunk"), metricByKey(activeAnalysis, "lying")]
                    .filter(Boolean)
                    .map((metric) => (
                      <div className={metric.is_warning_metric ? "warning-metric" : ""} key={metric.key}>
                        <strong className="dashboard-analysis-metric-title">{metric.label}</strong>
                        <div className="dashboard-analysis-metric-values">
                          <div>
                            <span>분석일</span>
                            <b>{formatPercent(metric.current_ratio_percent)}</b>
                            <small>{formatMinutes(metric.duration_min)}</small>
                          </div>
                          <div>
                            <span>최근 평균</span>
                            <b>{formatPercent(metric.baseline_ratio_percent)}</b>
                          </div>
                          <div>
                            <span>변화</span>
                            <b className={metric.is_warning_metric ? "warning-change" : ""}>{formatChange(metric.change_ratio_percent)}</b>
                          </div>
                        </div>
                      </div>
                    ))}
                </div>

                <div className="dashboard-analysis-section-heading reference-heading">
                  <strong>참고 행동</strong>
                  <span>주의 판정에는 사용하지 않는 분석일의 관찰값입니다.</span>
                </div>
                <div className="dashboard-analysis-reference-grid">
                  {[metricByKey(activeAnalysis, "standing"), metricByKey(activeAnalysis, "walking")]
                    .filter(Boolean)
                    .map((metric) => (
                      <div key={metric.key}>
                        <strong>{metric.key === "standing" ? "서 있음" : "걷는 중"}</strong>
                        <span>{formatPercent(metric.current_ratio_percent)}</span>
                        <small>{formatMinutes(metric.duration_min)}</small>
                      </div>
                    ))}
                </div>

                <div className="dashboard-analysis-policy-copy">
                  <strong>주의 판단 기준</strong>
                  <ul>
                    <li>급이대 체류비율이 대상일을 제외한 직전 {analysisPolicy.baselineRequiredValidDays}개 유효 관찰일 평균보다 {analysisPolicy.feedBunkWarningDecreasePercent}% 이상 감소</li>
                    <li>누움비율이 대상일을 제외한 직전 {analysisPolicy.baselineRequiredValidDays}개 유효 관찰일 평균보다 {analysisPolicy.lyingWarningDecreasePercent}% 이상 감소</li>
                    <li>두 조건 중 하나 이상에 해당하면 주의로 표시합니다.</li>
                  </ul>
                  <small>행동 변화를 확인하기 위한 기준이며, 질병 진단 기준은 아닙니다.</small>
                </div>
              </>
            )}

          </div>
        </div>
      )}

      {activeImage && (
        <div
          className="dashboard-image-modal"
          role="dialog"
          aria-modal="true"
          aria-label={activeImage.label}
          onClick={() => setActiveImage(null)}
        >
          <div className="dashboard-image-modal-card" onClick={(event) => event.stopPropagation()}>
            <div>
              <strong>{activeImage.label}</strong>
              <button type="button" onClick={() => setActiveImage(null)}>닫기</button>
            </div>
            <img src={activeImage.url} alt={activeImage.label} />
          </div>
        </div>
      )}

      {activeVideo && (
        <div
          className="dashboard-video-modal"
          role="dialog"
          aria-modal="true"
          aria-label={activeVideo.label}
          onClick={() => setActiveVideo(null)}
        >
          <div className="dashboard-video-modal-card" onClick={(event) => event.stopPropagation()}>
            <div>
              <strong>{activeVideo.label}</strong>
              <button type="button" onClick={() => setActiveVideo(null)}>닫기</button>
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
        cattle={reportCattle}
        analysisDate={analysisDate}
        updatedAt={updatedAt}
        isGuest={isGuest}
      />
    </section>
  );
}

export default AbnormalCattleDashboard;
