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

function BarnOperationsReport({ open, onClose, cattle = [], updatedAt }) {
  const [deviceState, setDeviceState] = useState(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();

    async function loadDeviceState() {
      try {
        setLoadError("");
        const devicesResponse = await fetch(`${API_BASE_URL}/devices/mine`, {
          credentials: "include",
          signal: controller.signal,
        });
        const devices = await devicesResponse.json();
        const device = devices?.devices?.[0];
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
    return () => controller.abort();
  }, [open]);

  const sensors = deviceState?.sensors || {};
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
  const recommendations = recommendationFor(sensors, groupedCattle);
  const titleDate = new Intl.DateTimeFormat("ko-KR", { dateStyle: "long", timeZone: "Asia/Seoul" }).format(new Date());

  return (
    <div className="operations-report-backdrop" role="dialog" aria-modal="true" aria-label="축사 운영 보고서" onClick={onClose}>
      <article className="operations-report" onClick={(event) => event.stopPropagation()}>
        <header className="operations-report-header">
          <div>
            <span> COWOW 축사 운영 리포트</span>
            <h2>{titleDate} 환경·이상행동 보고서</h2>
            <p>대시보드와 ESP32에서 수집한 최신 상태를 기반으로 작성되었습니다.</p>
          </div>
          <div className="operations-report-actions">
            <button type="button" onClick={() => window.print()}>인쇄 / PDF 저장</button>
            <button type="button" className="report-close" onClick={onClose}>닫기</button>
          </div>
        </header>

        <section className="report-overview">
          <div><span>위험 개체</span><strong>{groupedCattle.filter((item) => item.status === "danger").length}마리</strong></div>
          <div><span>주의 개체</span><strong>{groupedCattle.filter((item) => item.status === "warning").length}마리</strong></div>
          <div><span>장비 상태</span><strong className={deviceState?.online ? "report-ok" : "report-caution"}>{deviceState?.online ? "온라인" : "확인 필요"}</strong></div>
          <div><span>기준 시각</span><strong>{formatDate(updatedAt)}</strong></div>
        </section>

        <section className="report-section">
          <h3>환경 센서 현황</h3>
          {loadError ? <p className="report-note">{loadError}</p> : (
            <div className="report-sensor-grid">
              <div><span>온도</span><strong>{valueOrDash(sensors.temperature, "°C")}</strong><small>주의 28°C · 위험 32°C</small></div>
              <div><span>습도</span><strong>{valueOrDash(sensors.humidity, "%")}</strong><small>주의 75% · 위험 85%</small></div>
              <div><span>공기질</span><strong>{valueOrDash(sensors.airQuality, "%")}</strong><small>주의 55% · 위험 75%</small></div>
            </div>
          )}
          <p className="report-note">센서별 최고·최저 시각, 팬·살수 가동 시간과 환경 개선 효과는 이력 수집이 시작되는 시점부터 기간 보고서에 자동 누적됩니다.</p>
        </section>

        <section className="report-section">
          <h3>문제 개체 및 반복 관찰</h3>
          {groupedCattle.length ? (
            <div className="report-cattle-list">
              {groupedCattle.map((item) => (
                <div key={item.cattleId} className={`report-cattle-item ${item.status}`}>
                  <strong>{item.cattleId}</strong>
                  <span>{item.behavior}</span>
                  <span>최근 감지 {item.lastDetectedAt || "-"}</span>
                  <span>현재 목록 내 {item.count}건</span>
                </div>
              ))}
            </div>
          ) : <p className="report-note">현재 확인이 필요한 이상행동 개체가 없습니다.</p>}
        </section>

        <section className="report-section report-recommendations">
          <h3>운영 판단 및 권고</h3>
          <ul>{recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      </article>
    </div>
  );
}

export default BarnOperationsReport;
