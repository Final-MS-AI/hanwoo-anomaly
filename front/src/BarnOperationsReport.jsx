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

function recommendationFor(sensors, cattle) {
  const temperature = Number(sensors?.temperature);
  const humidity = Number(sensors?.humidity);
  const airQuality = Number(sensors?.airQuality);
  const dangerCount = cattle.filter((item) => item.status === "danger").length;

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
  if (dangerCount > 0) {
    items.push(`위험 개체 ${dangerCount}마리는 대표 이미지·감지 영상을 확인하고 개체별 관찰 기록을 남기세요.`);
  }
  if (!items.length) {
    items.push("현재 수집된 환경값은 정상 범위입니다. 이상행동 재발 여부와 환경 이력을 계속 관찰하세요.");
  }
  return items;
}

function sensorStatus(value, warning, danger) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return { label: "수집 대기", level: "pending" };
  if (numeric >= danger) return { label: "위험", level: "danger" };
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

function actuatorName(value) {
  return { ventilation_fan: "환기 팬", water_sprayer: "살수 장치", humidifier: "가습 장치" }[value] || value;
}

function printReport() {
  const report = document.querySelector(".operations-report");
  if (!report) return;

  // Print a document containing only the report. Printing the SPA modal itself
  // leaves its fixed backdrop/layout in Chrome's print tree and causes blank pages.
  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    window.print();
    return;
  }

  const stylesheets = [...document.querySelectorAll('link[rel="stylesheet"]')]
    .map((link) => `<link rel="stylesheet" href="${link.href}">`)
    .join("");

  printWindow.document.write(`<!doctype html>
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
    </style></head><body>${report.outerHTML}
    <script>window.addEventListener('load', () => setTimeout(() => { window.focus(); window.print(); }, 250));</script>
    </body></html>`);
  printWindow.document.close();
}

function BarnOperationsReport({ open, onClose, cattle = [], updatedAt }) {
  const [deviceState, setDeviceState] = useState(null);
  const [reportData, setReportData] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [reportLoadError, setReportLoadError] = useState("");

  useEffect(() => {
    if (!open) return undefined;
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
        let savedDevice = null;
        try {
          savedDevice = JSON.parse(localStorage.getItem("cowowRegisteredDevice"));
        } catch {
          savedDevice = null;
        }
        const device = devices?.devices?.[0] ?? savedDevice;
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
  }, [open]);

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
  const priorityCattle = groupedCattle.filter((item) => item.status === "danger" || item.status === "warning");
  const hasEnvironmentalRisk = [temperatureStatus, humidityStatus, airStatus].some((item) => item.level === "danger" || item.level === "warning");
  const reportDevice = reportData?.device;
  const deviceOnline = reportDevice?.online ?? deviceState?.online;
  const lastDeviceSeenAt = reportDevice?.lastSeenAt ?? deviceState?.lastSeenAt;

  return (
    <div className="operations-report-backdrop" role="dialog" aria-modal="true" aria-label="축사 운영 보고서" onClick={onClose}>
      <article className="operations-report" onClick={(event) => event.stopPropagation()}>
        <header className="operations-report-header">
          <div>
            <span> COWOW 축사 운영 리포트</span>
            <h2>{titleDate} 환경·이상행동 보고서</h2>
            <p>ESP32가 연결된 기간 동안 누적한 센서·제어·이상행동 이력을 기반으로 작성되었습니다.</p>
          </div>
          <div className="operations-report-actions">
            <button type="button" onClick={printReport}>인쇄 / PDF 저장</button>
            <button type="button" className="report-close" onClick={closeReport}>닫기</button>
          </div>
        </header>

        <section className="report-overview">
          <div><span>위험 개체</span><strong>{groupedCattle.filter((item) => item.status === "danger").length}마리</strong></div>
          <div><span>주의 개체</span><strong>{groupedCattle.filter((item) => item.status === "warning").length}마리</strong></div>
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
              ? `현재 ${priorityCattle.length}마리에서 확인이 필요한 이상행동이 감지되었습니다. 가장 최근 알림과 대표 이미지·감지 영상을 우선 확인하세요. `
              : "현재 활성 이상행동 경보는 없습니다. "}
            {hasEnvironmentalRisk
              ? "환경 수치 중 주의 이상 항목이 있어 환기·냉각 운전 상태를 함께 확인해야 합니다."
              : "현재 수집된 환경 센서값은 설정한 주의 기준 이내입니다."}
          </p>
          <div className="report-decision-grid">
            <div><span>개체 관찰</span><strong>{priorityCattle.length ? "우선 점검" : "정상 관찰"}</strong><small>{priorityCattle.length ? "이상행동 영상·현장 상태 대조" : "다음 분석 결과까지 모니터링"}</small></div>
            <div><span>환기·냉각</span><strong>{hasEnvironmentalRisk ? "운전 점검" : "현재 유지"}</strong><small>{hasEnvironmentalRisk ? "센서 추세와 팬 반응 확인" : "정상 범위 유지"}</small></div>
            <div><span>추가 설비 판단</span><strong>이력 수집 후</strong><small>지속시간·조치 효과를 기준으로 판단</small></div>
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
          <div className="report-section-heading"><div><span>03 · 개체 이상행동</span><h3>문제 개체 및 반복 관찰</h3></div><small>활성 알림 기준</small></div>
          {groupedCattle.length ? (
            <div className="report-cattle-list">
              {groupedCattle.map((item) => (
                <div key={item.cattleId} className={`report-cattle-item ${item.status}`}>
                  <strong>{item.cattleId}</strong>
                  <span>{item.behavior}</span>
                  <span>최근 감지 {item.lastDetectedAt || "-"}</span>
                  <span>{item.durationSeconds ? `${Math.round(item.durationSeconds)}초 연속` : `현재 목록 내 ${item.count}건`}</span>
                </div>
              ))}
            </div>
          ) : <p className="report-note">현재 확인이 필요한 이상행동 개체가 없습니다.</p>}
        </section>

        <section className="report-section report-recommendations">
          <div className="report-section-heading"><div><span>04 · 권고 조치</span><h3>운영 판단 및 다음 확인 항목</h3></div></div>
          <ul>{recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
          <div className="report-follow-up">
            <strong>다음 보고서에서 자동 검토할 항목</strong>
            <span>① 고온 발생 시각과 지속시간 ② 팬·살수 명령 및 실제 운전 시간 ③ 제어 후 온도·습도 변화 ④ 동일 개체·증상의 반복 횟수</span>
          </div>
        </section>
      </article>
    </div>
  );
}

export default BarnOperationsReport;
