import { useEffect, useMemo, useState } from "react";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

function valueOrDash(value, unit = "") {
  return Number.isFinite(Number(value)) ? `${Number(value)}${unit}` : "수집 중";
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Seoul",
  }).format(date);
}

function formatAnalysisDateLabel(value) {
  if (!value) return "-";
  const date = new Date(`${value}T00:00:00+09:00`);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    timeZone: "Asia/Seoul",
  }).format(date);
}

function recommendationFor(sensors, cattle) {
  const temperature = Number(sensors?.temperature);
  const humidity = Number(sensors?.humidity);
  const airQuality = Number(sensors?.airQuality);
  const warningCount = cattle.filter((item) => item.status === "warning").length;

  const items = [];
  if (temperature >= 32) {
    items.push("고온 상태입니다. 환기 장치 가동 상태를 점검하고, 지속 시 냉각 장치 추가를 검토하세요.");
  } else if (temperature >= 28) {
    items.push("온도가 주의 범위입니다. 환기량을 높이고 다음 보고서에서 온도 하강 효과를 비교하세요.");
  }
  if (humidity >= 75) {
    items.push("습도가 높습니다. 살수·가습 동작을 중지하고 환기 또는 제습 대책을 우선 검토하세요.");
  }
  if (airQuality >= 55) {
    items.push("공기질 수치가 주의 범위입니다. 팬 용량·환기구 막힘·축사 밀집도를 점검하세요.");
  }
  if (warningCount > 0) {
    items.push(`주의 개체 ${warningCount}마리는 행동 변화 원인과 현장 상태를 함께 확인하고 개체별 관찰 기록을 남기세요.`);
  }
  if (!items.length) {
    items.push("현재 수집된 환경값은 정상 범위입니다. 개체별 행동 변화와 환경 이력을 계속 관찰하세요.");
  }
  return items;
}

function sensorStatus(value, warning, danger) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return { label: "수집 대기", level: "pending" };
  if (numeric >= danger) return { label: "주의", level: "warning" };
  if (numeric >= warning) return { label: "주의", level: "warning" };
  return { label: "정상", level: "normal" };
}

function formatMetric(value, unit = "") {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}${unit}` : "-";
}

function formatDuration(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours ? `${hours}시간 ${minutes}분` : `${minutes}분`;
}

function attentionMetric(item, key) {
  return item?.metrics?.find((metric) => metric.key === key) || null;
}

function formatAttentionChange(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  if (numeric === 0) return "변화 없음";
  return `${numeric < 0 ? "감소" : "증가"} ${Math.abs(numeric).toFixed(1)}%`;
}

function attentionReason(item) {
  const feedBunk = attentionMetric(item, "feed_bunk");
  const lying = attentionMetric(item, "lying");
  const reasons = [];
  if (feedBunk?.is_warning_metric) reasons.push(`급이대 체류 ${formatAttentionChange(feedBunk.change_ratio_percent)}`);
  if (lying?.is_warning_metric) reasons.push(`누움 ${formatAttentionChange(lying.change_ratio_percent)}`);
  return reasons.length ? reasons.join(" · ") : item?.behavior || "주의 행동 변화";
}

function attentionComparison(item) {
  const metrics = [attentionMetric(item, "feed_bunk"), attentionMetric(item, "lying")].filter(
    (metric) => metric?.is_warning_metric,
  );
  if (!metrics.length) return "";
  return metrics
    .map(
      (metric) =>
        `${metric.label} 분석일 ${formatMetric(metric.current_ratio_percent, "%")} · 최근 평균 ${formatMetric(metric.baseline_ratio_percent, "%")}`,
    )
    .join(" / ");
}

function actuatorName(value) {
  return { ventilation_fan: "환기 팬", water_sprayer: "살수 장치", humidifier: "가습 장치" }[value] || value;
}

function equipmentDecision(telemetry, controls = []) {
  const samples = Number(telemetry?.sampleCount || 0);
  if (samples < 12) {
    return { title: "이력 수집 중", detail: `판단 기준 확보 중 · 현재 ${samples}건 수집` };
  }

  const temperature = telemetry?.temperature;
  const humidity = telemetry?.humidity;
  const fan = controls.find((item) => item.actuator === "ventilation_fan");
  const fanWasUsed = Number(fan?.estimatedOnSeconds || 0) > 0;

  if (Number(temperature?.max) >= 32 && fanWasUsed) {
    return { title: "냉각 장치 검토", detail: "팬 가동 후에도 32°C 이상 고온 발생" };
  }
  if (Number(temperature?.max) >= 28) {
    return { title: "환기 성능 점검", detail: "28°C 이상 고온 구간 발생" };
  }
  if (Number(humidity?.max) >= 75) {
    return { title: "제습·환기 점검", detail: "75% 이상 고습 구간 발생" };
  }
  return { title: "추가 설비 불필요", detail: `최근 7일 ${samples}건 기준 정상 범위 유지` };
}

function buildPrintDocument(report) {
  const stylesheets = [...document.querySelectorAll('link[rel="stylesheet"]')]
    .map((link) => `<link rel="stylesheet" href="${link.href}">`)
    .join("");

  return `<!doctype html>
    <html lang="ko"><head><meta charset="utf-8"><title>COWOW 축사 운영 보고서</title>
    ${stylesheets}
    <style>
      @page { size: A4 portrait; margin: 12mm; }
      html, body { margin: 0; padding: 0; background: #fff; }
      body { color: #281d14; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
      .operations-report { width: auto; max-width: none; margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; }
      .operations-report-actions { display: none !important; }
      .operations-report-header, .report-overview, .report-history-detail > div, .report-cattle-item { break-inside: avoid; page-break-inside: avoid; }
      .report-section-heading { break-after: avoid; page-break-after: avoid; }
      .report-section { margin-top: 16px; }
    </style></head><body>${report.outerHTML}</body></html>`;
}

function printReport() {
  const report = document.querySelector(".operations-report");
  if (!report) return;

  const printHtml = buildPrintDocument(report);

  // Expo/React Native WebView cannot open a browser print popup reliably.
  // Send the self-contained report document to the native app instead.
  if (typeof window.ReactNativeWebView?.postMessage === "function") {
    window.ReactNativeWebView.postMessage(JSON.stringify({
      type: "COWOW_PRINT_REPORT",
      title: "COWOW 축사 운영 보고서",
      html: printHtml,
    }));
    return;
  }

  // Print a document containing only the report. Printing the SPA modal itself
  // leaves its fixed backdrop/layout in Chrome's print tree and causes blank pages.
  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    window.print();
    return;
  }

  printWindow.document.write(printHtml.replace(
    "</body></html>",
    "<script>window.addEventListener('load', () => setTimeout(() => { window.focus(); window.print(); }, 250));</script></body></html>",
  ));
  printWindow.document.close();
}

const GUEST_REPORT_DATA = {
  deviceId: "GUEST-DEMO-01",
  device: { online: true, lastSeenAt: new Date().toISOString() },
  telemetry: {
    sampleCount: 96,
    temperature: { average: 26.4, min: 24.8, max: 29.1, highWindows: [] },
    humidity: { average: 67, min: 59, max: 73, highWindows: [] },
    airQuality: { average: 18, min: 11, max: 31, highWindows: [] },
  },
  controls: [
    { actuator: "ventilation_fan", commandCount: 8, estimatedOnSeconds: 14400 },
    { actuator: "water_sprayer", commandCount: 2, estimatedOnSeconds: 60 },
  ],
};

function BarnOperationsReport({ open, onClose, cattle = [], analysisDate = null, updatedAt, isGuest = false }) {
  const [deviceState, setDeviceState] = useState(null);
  const [reportData, setReportData] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [reportLoadError, setReportLoadError] = useState("");

  useEffect(() => {
    if (!open) return undefined;
    if (isGuest) {
      setDeviceState({
        online: true,
        lastSeenAt: new Date().toISOString(),
        publicDeviceNumber: "GUEST",
        sensors: { temperature: 26.4, humidity: 67, airQuality: 18 },
      });
      setReportData(GUEST_REPORT_DATA);
      setLoadError("");
      setReportLoadError("");
      return undefined;
    }
    const controller = new AbortController();

    async function loadDeviceState() {
      try {
        setLoadError("");
        const reportResponse = await fetch(`${API_BASE_URL}/api/reports/barn?days=7`, {
          credentials: "include",
          signal: controller.signal,
          cache: "no-store",
        });
        const report = await reportResponse.json().catch(() => ({}));
        if (reportResponse.ok) {
          setReportData(report);
          setReportLoadError("");
        } else {
          setReportLoadError(report.detail || "기간 센서 이력을 불러오지 못했습니다.");
        }
        const devicesResponse = await fetch(`${API_BASE_URL}/devices/mine`, {
          credentials: "include",
          signal: controller.signal,
        });
        const devices = await devicesResponse.json();
        const device = devices?.devices?.[0] ?? null;
        if (!devicesResponse.ok || !device?.deviceId) {
          throw new Error("연결된 환경 장비 정보가 없습니다.");
        }
        const stateResponse = await fetch(
          `${API_BASE_URL}/devices/${encodeURIComponent(device.deviceId)}/state`,
          { credentials: "include", signal: controller.signal },
        );
        const state = await stateResponse.json();
        if (!stateResponse.ok) throw new Error(state?.detail || "센서 상태를 불러오지 못했습니다.");
        setDeviceState({ ...state, publicDeviceNumber: device.publicDeviceNumber });
      } catch (error) {
        if (error.name !== "AbortError") setLoadError(error.message || "환경 데이터를 불러오지 못했습니다.");
      }
    }

    loadDeviceState();
    const refreshTimer = window.setInterval(loadDeviceState, 15000);
    return () => {
      window.clearInterval(refreshTimer);
      controller.abort();
    };
  }, [open, isGuest]);

  const closeReport = (event) => {
    event?.preventDefault();
    event?.stopPropagation();
    setReportData(null);
    setReportLoadError("");
    onClose();
  };

  const sensors = deviceState?.sensors || {};
  const telemetry = reportData?.telemetry;
  const hasHistory = Boolean(telemetry?.sampleCount);
  const periodSensors = {
    temperature: telemetry?.temperature,
    humidity: telemetry?.humidity,
    airQuality: telemetry?.airQuality,
  };
  const groupedCattle = useMemo(() => {
    const map = new Map();
    cattle.forEach((item) => {
      const key = item.cattleId;
      const previous = map.get(key) || { ...item, count: 0 };
      previous.count += 1;
      if (new Date(item.detectedAt || 0) > new Date(previous.detectedAt || 0)) {
        previous.behavior = item.behavior;
        previous.lastDetectedAt = item.lastDetectedAt;
      }
      map.set(key, previous);
    });
    return [...map.values()];
  }, [cattle]);

  if (!open) return null;
  const recommendationSensors = hasHistory
    ? {
        temperature: periodSensors.temperature?.max,
        humidity: periodSensors.humidity?.max,
        airQuality: periodSensors.airQuality?.max,
      }
    : sensors;
  const recommendations = recommendationFor(recommendationSensors, groupedCattle);
  const titleDate = new Intl.DateTimeFormat("ko-KR", { dateStyle: "long", timeZone: "Asia/Seoul" }).format(new Date());
  const temperatureStatus = sensorStatus(hasHistory ? periodSensors.temperature?.max : sensors.temperature, 28, 32);
  const humidityStatus = sensorStatus(hasHistory ? periodSensors.humidity?.max : sensors.humidity, 75, 85);
  const airStatus = sensorStatus(hasHistory ? periodSensors.airQuality?.max : sensors.airQuality, 55, 75);
  const priorityCattle = groupedCattle.filter((item) => item.status === "warning");
  const insufficientCattle = groupedCattle.filter((item) => item.status === "insufficient");
  const missingAnalysisCattle = insufficientCattle.filter((item) => item.source === "missing");
  const baselineCollectingCattle = insufficientCattle.filter(
    (item) => item.source !== "missing" && item.isBaselineCollecting,
  );
  const insufficientDataCattle = insufficientCattle.filter(
    (item) => item.source !== "missing" && !item.isBaselineCollecting,
  );
  const hasEnvironmentalRisk = [temperatureStatus, humidityStatus, airStatus].some((item) => item.level === "warning");
  const reportDevice = reportData?.device;
  const deviceOnline = reportDevice?.online ?? deviceState?.online;
  const lastDeviceSeenAt = reportDevice?.lastSeenAt ?? deviceState?.lastSeenAt;
  const facilityDecision = equipmentDecision(telemetry, reportData?.controls);

  return (
    <div className="operations-report-backdrop" role="dialog" aria-modal="true" aria-label="축사 운영 보고서" onClick={onClose}>
      <article className="operations-report" onClick={(event) => event.stopPropagation()}>
        <header className="operations-report-header">
          <div>
            <div className="report-title-kicker">
              <span>COWOW 축사 운영 리포트</span>
              {isGuest && <span className="dashboard-demo-badge">예시 데이터</span>}
            </div>
            <h2>{titleDate} 환경·행동 변화 보고서</h2>
            <p>최근 7일 환경·장비 이력과 최신 완료 일별 행동 변화 분석을 함께 정리했습니다.</p>
          </div>
          <div className="operations-report-actions">
            <button type="button" onClick={printReport}>인쇄 / PDF 저장</button>
            <button type="button" className="report-close" onClick={closeReport}>닫기</button>
          </div>
        </header>

        <section className="report-overview">
          <div><span>주의 개체</span><strong>{priorityCattle.length}마리</strong></div>
          <div><span>분석 데이터 부족</span><strong>{insufficientCattle.length}마리</strong></div>
          <div><span>장비 상태</span><strong className={deviceOnline ? "report-ok" : "report-caution"}>{deviceOnline ? "온라인" : "통신 확인 중"}</strong><small>{lastDeviceSeenAt ? `최근 통신 ${formatDate(lastDeviceSeenAt)}` : "최근 통신 정보 없음"}</small></div>
          <div><span>기준 시각</span><strong>{formatDate(updatedAt)}</strong></div>
        </section>

        <section className="report-section report-executive-summary">
          <div className="report-section-heading">
            <div><span>01 · 종합 판단</span><h3>오늘의 축사 운영 요약</h3></div>
            <b className={priorityCattle.length || hasEnvironmentalRisk ? "report-risk-chip" : "report-safe-chip"}>
              {priorityCattle.length || hasEnvironmentalRisk ? "확인·조치 필요" : "현재 안정"}
            </b>
          </div>
          <p>
            {priorityCattle.length
              ? `최신 행동 변화 분석에서 ${priorityCattle.length}마리가 주의로 분류되었습니다. 상세 분석의 분석일 값과 최근 평균을 현장 상태와 함께 확인하세요. `
              : "최신 행동 변화 분석에서 주의로 분류된 개체는 없습니다. "}
            {hasEnvironmentalRisk
              ? "환경 수치 중 주의 이상 항목이 있어 환기·냉각 운전 상태를 함께 확인해야 합니다."
              : "현재 수집된 환경 센서값은 설정한 주의 기준 이내입니다."}
          </p>
          <div className="report-decision-grid">
            <div><span>개체 관찰</span><strong>{priorityCattle.length ? "우선 점검" : "정상 관찰"}</strong><small>{priorityCattle.length ? "행동 변화 원인·현장 상태 대조" : "다음 일별 분석까지 모니터링"}</small></div>
            <div><span>환기·냉각</span><strong>{hasEnvironmentalRisk ? "운전 점검" : "현재 유지"}</strong><small>{hasEnvironmentalRisk ? "센서 추세와 팬 반응 확인" : "정상 범위 유지"}</small></div>
            <div><span>추가 설비 판단</span><strong>{facilityDecision.title}</strong><small>{facilityDecision.detail}</small></div>
          </div>
        </section>

        <section className="report-section">
          <div className="report-section-heading"><div><span>02 · 환경 이력</span><h3>최근 7일 센서 추세와 설비 판단</h3></div><small>장비 {deviceState?.publicDeviceNumber || reportData?.deviceId || "미연결"}</small></div>
          {loadError ? <p className="report-note">{loadError}</p> : (
            <div className="report-sensor-grid">
              <div><span>온도 <b className={`sensor-status ${temperatureStatus.level}`}>{temperatureStatus.label}</b></span><strong>{hasHistory ? `평균 ${formatMetric(periodSensors.temperature?.average, "°C")}` : valueOrDash(sensors.temperature, "°C")}</strong><small>{hasHistory ? `최저 ${formatMetric(periodSensors.temperature?.min, "°C")} · 최고 ${formatMetric(periodSensors.temperature?.max, "°C")}` : "이력 수집 시작 대기"}</small></div>
              <div><span>습도 <b className={`sensor-status ${humidityStatus.level}`}>{humidityStatus.label}</b></span><strong>{hasHistory ? `평균 ${formatMetric(periodSensors.humidity?.average, "%")}` : valueOrDash(sensors.humidity, "%")}</strong><small>{hasHistory ? `최저 ${formatMetric(periodSensors.humidity?.min, "%")} · 최고 ${formatMetric(periodSensors.humidity?.max, "%")}` : "이력 수집 시작 대기"}</small></div>
              <div><span>공기질 <b className={`sensor-status ${airStatus.level}`}>{airStatus.label}</b></span><strong>{hasHistory ? `평균 ${formatMetric(periodSensors.airQuality?.average, "%")}` : valueOrDash(sensors.airQuality, "%")}</strong><small>{hasHistory ? `최저 ${formatMetric(periodSensors.airQuality?.min, "%")} · 최고 ${formatMetric(periodSensors.airQuality?.max, "%")}` : "이력 수집 시작 대기"}</small></div>
            </div>
          )}
          <div className="report-history-notice">
            <strong>{hasHistory ? `기간 분석 완료 · ${telemetry.sampleCount}건 수집` : "기간 분석 데이터 수집 중"}</strong>
            <p>{hasHistory ? "표시값은 실시간 한 건이 아니라 저장된 센서 이력의 평균·최저·최고값입니다. 제어 가동시간은 완료된 ON/OFF 명령을 기준으로 계산합니다." : "이력 저장을 시작했습니다. ESP32가 다음 텔레메트리를 보내면 평균·최저·최고 및 지속시간이 보고서에 표시됩니다."}</p>
          </div>
          {reportLoadError && <p className="report-note">{reportLoadError}</p>}
          {hasHistory && (
            <div className="report-history-detail">
              <div><strong>고온 구간</strong>{periodSensors.temperature?.highWindows?.length ? periodSensors.temperature.highWindows.map((item) => <span key={item.startedAt}>{formatDate(item.startedAt)} · 최고 {formatMetric(item.maxValue, "°C")} · {formatDuration(item.durationSeconds)}</span>) : <span>28°C 이상 구간 없음</span>}</div>
              <div><strong>고습 구간</strong>{periodSensors.humidity?.highWindows?.length ? periodSensors.humidity.highWindows.map((item) => <span key={item.startedAt}>{formatDate(item.startedAt)} · 최고 {formatMetric(item.maxValue, "%")} · {formatDuration(item.durationSeconds)}</span>) : <span>75% 이상 구간 없음</span>}</div>
              <div><strong>장비 제어 이력</strong>{reportData?.controls?.length ? reportData.controls.map((item) => <span key={item.actuator}>{actuatorName(item.actuator)} · 명령 {item.commandCount}건 · 가동 추정 {formatDuration(item.estimatedOnSeconds)}</span>) : <span>완료된 제어 명령 없음</span>}</div>
            </div>
          )}
        </section>

        <section className="report-section">
          <div className="report-section-heading"><div><span>03 · 행동 변화 분석</span><h3>주의 개체의 분석일 값과 최근 평균 비교</h3></div><small>{analysisDate ? `행동 분석일 ${formatAnalysisDateLabel(analysisDate)}` : "최신 완료 일별 분석"}</small></div>
          {priorityCattle.length ? (
            <div className="report-cattle-list">
              {priorityCattle.map((item) => (
                <div key={item.cattleId} className="report-cattle-item warning report-attention-item">
                  <strong>{item.cattleId}</strong>
                  <span>{attentionReason(item)}</span>
                  <span>{attentionComparison(item)}</span>
                  <span>{item.streakDays > 1 ? `주의 · ${item.streakDays}일 연속` : "주의"}</span>
                </div>
              ))}
            </div>
          ) : <p className="report-note">최신 행동 변화 분석에서 주의 개체가 없습니다.</p>}
          {missingAnalysisCattle.length > 0 && (
            <p className="report-note">분석 결과 없음 {missingAnalysisCattle.length}마리: 해당 분석일의 분석 결과가 없습니다.</p>
          )}
          {baselineCollectingCattle.length > 0 && (
            <>
              <p className="report-note">기준 데이터 수집 중 {baselineCollectingCattle.length}마리</p>
              {baselineCollectingCattle.map((item) => (
                <p className="report-note" key={`baseline-collecting-${item.cattleId}`}>
                  {item.cattleId}: 기준 데이터 수집 중 {item.baselineValidDays}일 / {item.baselineRequiredDays}일 · 직전 {item.baselineRequiredDays}개 유효 관찰일 확보 후 정상/주의 판정을 시작합니다.
                </p>
              ))}
            </>
          )}
          {insufficientDataCattle.length > 0 && (
            <>
              <p className="report-note">분석 데이터 부족 {insufficientDataCattle.length}마리</p>
              {insufficientDataCattle.map((item) => (
                <p className="report-note" key={`insufficient-${item.cattleId}`}>
                  {item.cattleId}: {item.detail || "분석에 필요한 유효 관찰시간이 충분하지 않습니다."}
                </p>
              ))}
            </>
          )}
          <div className="report-attention-policy">
            <strong>주의 판단 기준</strong>
            <p>대상일을 제외한 직전 10개 유효 관찰일 평균과 비교하며, 급이대 체류비율이 18% 이상 감소하거나 누움비율이 30% 이상 감소하면 주의로 표시합니다.</p>
            <small>행동 변화를 확인하기 위한 기준이며, 질병 진단 기준은 아닙니다.</small>
          </div>
        </section>

        <section className="report-section report-recommendations">
          <div className="report-section-heading"><div><span>04 · 권고 조치</span><h3>운영 판단 및 다음 확인 항목</h3></div></div>
          <ul>{recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
          <div className="report-follow-up">
            <strong>다음 보고서에서 자동 검토할 항목</strong>
            <span>① 고온 발생 시각과 지속시간 ② 팬·살수 명령 및 실제 운전 시간 ③ 제어 후 온도·습도 변화 ④ 동일 개체의 행동 변화 반복 여부</span>
          </div>
        </section>
      </article>
    </div>
  );
}

export default BarnOperationsReport;
