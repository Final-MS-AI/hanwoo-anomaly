import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import DeviceSharingPanel from "./DeviceSharingPanel.jsx";

const CONTROL_API_URL =
  import.meta.env.VITE_CONTROL_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "https://hanwoo.koreacentral.cloudapp.azure.com";
const DEVICE_STORAGE_KEY = "cowowRegisteredDevice";
const COWOW_0001_LIVE_VIEW_URL =
  import.meta.env.VITE_LIVE_VIEW_URL ??
  "https://hanwoo2.koreacentral.cloudapp.azure.com/top/raw";
const COWOW_0001_IDENTITY_VIEW_URL =
  import.meta.env.VITE_IDENTITY_LIVE_VIEW_URL ??
  "https://hanwoo2.koreacentral.cloudapp.azure.com/identity-raw";

function getLiveViewUrl(device) {
  if (!device) return "";
  if (device.liveViewUrl) return device.liveViewUrl;

  const systemNumber = String(
    device.publicDeviceNumber ?? device.systemId ?? "",
  ).toUpperCase();

  if (systemNumber === "COWOW-0001" || systemNumber === "GUEST") {
    return COWOW_0001_LIVE_VIEW_URL;
  }

  return "";
}

const initialSensors = {
  temperature: null,
  humidity: null,
  airQuality: null,
};

const sensorDefinitions = [
  {
    key: "temperature",
    label: "온도",
    unit: "°C",
    icon: "℃",
    precision: 1,
    warning: 28,
    danger: 32,
  },
  {
    key: "humidity",
    label: "습도",
    unit: "%",
    icon: "◌",
    precision: 0,
    warning: 75,
    danger: 85,
  },
  {
    key: "airQuality",
    label: "공기질",
    unit: "%",
    icon: "AQ",
    precision: 0,
    warning: 55,
    danger: 75,
  },
];

function getSensorLevel(value, sensor) {
  if (!Number.isFinite(value)) return "unavailable";
  if (value >= sensor.danger) return "danger";
  if (value >= sensor.warning) return "warning";
  return "normal";
}

function BarnEnvironmentControl({ user }) {
  const navigate = useNavigate();
  const isGuest = user?.loginType === "guest";
  const [device, setDevice] = useState(() => {
    try {
      // Browser storage is shared across Google/Kakao/Naver logins. Only the
      // guest demo may use a local cache; social accounts use /devices/mine.
      const cachedDevice = JSON.parse(localStorage.getItem(DEVICE_STORAGE_KEY));
      return cachedDevice?.accountScope === "guest" ? cachedDevice : null;
    } catch {
      return null;
    }
  });
  const [sensors, setSensors] = useState(initialSensors);
  const [isDeviceOnline, setIsDeviceOnline] = useState(false);
  const [lastSeenAt, setLastSeenAt] = useState(null);
  const [mode, setMode] = useState("auto");
  const [fanLevel, setFanLevel] = useState(2);
  const [isSpraying, setIsSpraying] = useState(false);
  const [isControlsOpen, setIsControlsOpen] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [disconnectError, setDisconnectError] = useState("");
  const [controlMessage, setControlMessage] = useState("자동 환기 운전 중");
  const [activeSystemTab, setActiveSystemTab] = useState("environment");
  const sprayTimerRef = useRef(null);

  const sensorCards = useMemo(
    () =>
      sensorDefinitions.map((sensor) => ({
        ...sensor,
        value: sensors[sensor.key],
        level: getSensorLevel(sensors[sensor.key], sensor),
      })),
    [sensors],
  );

  const warnings = sensorCards.filter(
    (sensor) =>
      sensor.level === "warning" || sensor.level === "danger",
  );
  const liveViewUrl = getLiveViewUrl(device);
  const lastSeenLabel = lastSeenAt
    ? new Date(lastSeenAt).toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "확인 중";

  useEffect(() => {
    if (isGuest) {
      setDevice({ deviceId: "GUEST-DEMO-01", publicDeviceNumber: "GUEST", accountScope: "guest" });
      setSensors({ temperature: 26.4, humidity: 67, airQuality: 18 });
      setIsDeviceOnline(true);
      setLastSeenAt(new Date().toISOString());
      setControlMessage("게스트 데모 환경 시스템이 연결되었습니다.");
      return undefined;
    }
    if (!CONTROL_API_URL) return undefined;

    const controller = new AbortController();

    fetch(`${CONTROL_API_URL}/devices/mine`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail ?? "등록 장비 조회에 실패했습니다.");
        }
        return data.devices?.[0] ?? null;
      })
      .then((registeredDevice) => {
        if (!registeredDevice && device?.accountScope === "guest") {
          return;
        }
        // The backend result is account-scoped. Discard a prior login's cache.
        localStorage.removeItem(DEVICE_STORAGE_KEY);
        setDevice(registeredDevice);
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          localStorage.removeItem(DEVICE_STORAGE_KEY);
          setDevice(null);
          console.error("Registered device error:", error);
        }
      });

    return () => controller.abort();
  }, [isGuest]);

  useEffect(() => {
    if (isGuest) return undefined;
    if (!device?.deviceId || !CONTROL_API_URL) {
      return undefined;
    }

    let isCancelled = false;

    const loadDeviceState = async () => {
      try {
        const response = await fetch(
          `${CONTROL_API_URL}/devices/${encodeURIComponent(device.deviceId)}/state`,
          { credentials: "include" },
        );
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail ?? "센서값 조회에 실패했습니다.");
        }

        if (isCancelled) return;

        setIsDeviceOnline(Boolean(data.online));
        setLastSeenAt(data.lastSeenAt ?? null);
        setSensors((previous) => ({
          temperature:
            data.sensors?.temperature ?? previous.temperature,
          humidity:
            data.sensors?.humidity ?? previous.humidity,
          airQuality:
            data.sensors?.airQuality ??
            data.sensors?.ammonia ??
            previous.airQuality,
        }));
      } catch (error) {
        if (!isCancelled) {
          setIsDeviceOnline(false);
          console.error("Device state error:", error);
        }
      }
    };

    loadDeviceState();
    const sensorTimer = window.setInterval(loadDeviceState, 5000);

    return () => {
      isCancelled = true;
      window.clearInterval(sensorTimer);
      if (sprayTimerRef.current) window.clearTimeout(sprayTimerRef.current);
    };
  }, [device?.deviceId, isGuest]);

  const sendControlCommand = useCallback(async (actuator, value) => {
    if (isGuest) {
      setControlMessage(`${actuator === "ventilation_fan" ? "환기팬" : "살수 장치"} 데모 명령을 적용했습니다.`);
      return;
    }
    if (!CONTROL_API_URL) return;

    const response = await fetch(`${CONTROL_API_URL}/actuators`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        deviceId: device?.deviceId,
        actuator,
        value,
      }),
    });

    if (!response.ok) throw new Error("장비 제어 명령 전송에 실패했습니다.");
  }, [device?.deviceId, isGuest]);

  useEffect(() => {
    if (mode !== "auto" || !device?.deviceId) return undefined;

    const recommendedLevel =
      sensors.airQuality >= 75 || sensors.temperature >= 32
        ? 3
        : sensors.airQuality >= 55 || sensors.temperature >= 28
          ? 2
          : 1;

    let isCancelled = false;
    setFanLevel(recommendedLevel);
    setControlMessage(`환기팬 ${recommendedLevel}단계 명령을 전송하는 중입니다.`);

    sendControlCommand("ventilation_fan", recommendedLevel)
      .then(() => {
        if (!isCancelled) {
          setControlMessage(
            `센서 기준으로 환기팬 ${recommendedLevel}단계를 자동 유지합니다.`,
          );
        }
      })
      .catch((error) => {
        if (!isCancelled) setControlMessage(error.message);
      });

    return () => {
      isCancelled = true;
    };
  }, [
    device?.deviceId,
    mode,
    sendControlCommand,
    sensors.airQuality,
    sensors.temperature,
  ]);

  const changeFanLevel = async (level) => {
    if (mode === "auto") return;

    try {
      await sendControlCommand("ventilation_fan", level);
      setFanLevel(level);
      setControlMessage(level === 0 ? "환기팬을 정지했습니다." : `환기팬을 ${level}단계로 운전합니다.`);
    } catch (error) {
      setControlMessage(error.message);
    }
  };

  const toggleSprayer = async () => {
    const nextState = !isSpraying;

    try {
      await sendControlCommand("water_sprayer", nextState);
      setIsSpraying(nextState);

      if (sprayTimerRef.current) window.clearTimeout(sprayTimerRef.current);

      if (nextState) {
        setControlMessage("살수 장치를 작동했습니다. 30초 후 자동 정지합니다.");
        sprayTimerRef.current = window.setTimeout(async () => {
          setIsSpraying(false);
          setControlMessage("30초 살수가 완료되었습니다.");
          try {
            await sendControlCommand("water_sprayer", false);
          } catch {
            setControlMessage("살수 자동 정지 명령을 확인해 주세요.");
          }
        }, 30000);
      } else {
        setControlMessage("살수 장치를 정지했습니다.");
      }
    } catch (error) {
      setControlMessage(error.message);
    }
  };

  const disconnectDevice = async () => {
    if (!device || isDisconnecting) return;

    setIsDisconnecting(true);
    setDisconnectError("");

    try {
      const response = await fetch(`${CONTROL_API_URL}/devices/connection`, {
        method: "DELETE",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deviceId: device.deviceId }),
      });

      if (!response.ok && response.status !== 404) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail ?? "장비 연결 해제에 실패했습니다.");
      }

      localStorage.removeItem(DEVICE_STORAGE_KEY);
      setDevice(null);
      setSensors(initialSensors);
      setIsDeviceOnline(false);
      setLastSeenAt(null);
    } catch (error) {
      setDisconnectError(error.message);
      setControlMessage(error.message);
    } finally {
      setIsDisconnecting(false);
    }
  };

  return (
    <section className="environment-control-page">
      <div className="environment-control-header">
        <div>
          <span className="environment-live"><i /> 실시간 환경</span>
          <h2>축사 환경 시스템</h2>
          <p>환경 센서, 제어 장치와 CCTV 분석 스트림을 한 곳에서 확인합니다.</p>
        </div>
        {device && (
          <div className="connection-action-area">
            <button
              className="sensor-connection-badge disconnect-action"
              type="button"
              disabled={isDisconnecting}
              onClick={disconnectDevice}
            >
              {isDisconnecting ? "해제 중..." : "연결 해제"}
            </button>
            {disconnectError && (
              <small className="connection-action-error" role="alert">
                {disconnectError}
              </small>
            )}
          </div>
        )}
      </div>

      <div className={`remote-connection-card ${device ? "connected" : "unregistered"}`}>
        <div className="remote-connection-main">
          <span className="remote-connection-icon">{device ? "⌁" : "+"}</span>
          <div>
            <strong>{device ? "COWOW 축사 환경 시스템" : "축사 환경 시스템을 등록해 주세요"}</strong>
            <p>
              {device
                ? `환경 센서 · 로컬 분석 서버 · CCTV 스트림 → COWOW 클라우드`
                : "최초 한 번 등록하면 센서 제어와 영상 분석 결과를 함께 사용할 수 있습니다."}
            </p>
          </div>
        </div>
        <div className="remote-connection-meta">
          {device ? (
            <>
              <span><i /> {isDeviceOnline ? "온라인" : "오프라인"}</span>
              <small>마지막 통신 {lastSeenLabel}</small>
            </>
          ) : (
            <button type="button" onClick={() => navigate("/devices/setup")}>환경 시스템 연결</button>
          )}
        </div>
      </div>

      <div className="environment-system-tabs" role="tablist" aria-label="축사 환경 시스템 보기">
        <button
          className={activeSystemTab === "environment" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeSystemTab === "environment"}
          onClick={() => setActiveSystemTab("environment")}
        >
          환경 센서·제어
        </button>
        <button
          className={activeSystemTab === "live" ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={activeSystemTab === "live"}
          onClick={() => setActiveSystemTab("live")}
        >
          실시간 CCTV
        </button>
      </div>

      {activeSystemTab === "environment" ? (
        <>
      <DeviceSharingPanel device={device} />

      <div className="sensor-grid">
        {sensorCards.map((sensor) => (
          <article className={`sensor-card ${sensor.level}`} key={sensor.key}>
            <div className="sensor-card-top">
              <span className="sensor-icon">{sensor.icon}</span>
              <span className={`sensor-state ${sensor.level}`}>
                {sensor.level === "unavailable"
                  ? "미연결"
                  : sensor.level === "normal"
                    ? "정상"
                    : sensor.level === "warning"
                      ? "주의"
                      : "위험"}
              </span>
            </div>
            <span className="sensor-name">{sensor.label}</span>
            <strong>
              {Number.isFinite(sensor.value)
                ? sensor.value.toFixed(sensor.precision)
                : "--"}
              {Number.isFinite(sensor.value) && (
                <small>{sensor.unit}</small>
              )}
            </strong>
          </article>
        ))}
      </div>

      <div className={`environment-notice ${warnings.length ? "warning" : "normal"}`}>
        <span>{warnings.length ? "!" : "✓"}</span>
        <div>
          <strong>
            {warnings.length
              ? `${warnings.map((sensor) => sensor.label).join(", ")} 수치를 확인하세요.`
              : "모든 환경 센서가 정상 범위입니다."}
          </strong>
          <p>
            {warnings.length
              ? "자동 제어가 환기량을 조절하고 있습니다."
              : "현재 설정을 유지해도 좋습니다."}
          </p>
        </div>
      </div>

      <button
        className="environment-controls-toggle"
        type="button"
        aria-expanded={isControlsOpen}
        aria-controls="environment-device-controls"
        onClick={() => setIsControlsOpen((previous) => !previous)}
      >
        <span>
          <strong>팬·살수 장비 제어</strong>
          <small>
            {mode === "auto" ? "자동" : "수동"} · 팬 {fanLevel === 0 ? "정지" : `${fanLevel}단`} · {isSpraying ? "살수 중" : "살수 대기"}
          </small>
        </span>
        <b>{isControlsOpen ? "접기 ▲" : "제어 열기 ›"}</b>
      </button>

      <div
        id="environment-device-controls"
        className={`environment-device-controls ${isControlsOpen ? "is-open" : "is-collapsed"}`}
      >
        <div className="control-mode-row">
          <div>
            <strong>제어 모드</strong>
            <span>{mode === "auto" ? "센서값에 따라 자동 운전" : "관리자가 직접 운전"}</span>
          </div>
          <div className="control-mode-buttons" role="group" aria-label="제어 모드">
            <button className={mode === "auto" ? "active" : ""} type="button" onClick={() => setMode("auto")}>자동</button>
            <button className={mode === "manual" ? "active" : ""} type="button" onClick={() => setMode("manual")}>수동</button>
          </div>
        </div>

        <div className="actuator-grid">
          <article className="actuator-card">
            <div className="actuator-header">
              <div>
                <span className="actuator-label">환기 장치</span>
                <h3>환기팬</h3>
              </div>
              <span className={`device-status ${fanLevel > 0 ? "on" : "off"}`}>
                {fanLevel > 0 ? `운전 ${fanLevel}단계` : "정지"}
              </span>
            </div>
            <div className="fan-level-buttons" role="group" aria-label="환기팬 단계">
              {[0, 1, 2, 3].map((level) => (
                <button
                  className={fanLevel === level ? "active" : ""}
                  type="button"
                  key={level}
                  disabled={mode === "auto"}
                  onClick={() => changeFanLevel(level)}
                >
                  {level === 0 ? "정지" : `${level}단`}
                </button>
              ))}
            </div>
            {mode === "auto" && <p className="auto-control-hint">수동 조작은 수동 모드에서 사용할 수 있습니다.</p>}
          </article>

          <article className="actuator-card">
            <div className="actuator-header">
              <div>
                <span className="actuator-label">냉각 장치</span>
                <h3>물 뿌리기</h3>
              </div>
              <span className={`device-status ${isSpraying ? "on" : "off"}`}>
                {isSpraying ? "살수 중" : "대기"}
              </span>
            </div>
            <button
              className={`sprayer-button ${isSpraying ? "stop" : ""}`}
              type="button"
              disabled={mode === "auto"}
              onClick={toggleSprayer}
            >
              {isSpraying ? "살수 정지" : "30초 살수 시작"}
            </button>
            {mode === "auto" && <p className="auto-control-hint">고온 조건에서 자동으로 살수합니다.</p>}
          </article>
        </div>

        <div className="control-feedback" role="status">
          <span>최근 제어</span>
          <strong>{controlMessage}</strong>
        </div>
      </div>
        </>
      ) : (
        <div className="live-cctv-grid">
        <section className="live-cctv-panel" aria-label="실시간 CCTV 화면">
          <div className="live-cctv-header">
            <div>
              <span>CAMERA-01</span>
              <h3>1번 축사 실시간 화면</h3>
            </div>
            <strong><i /> {liveViewUrl ? "스트림 연결" : "시스템 미연결"}</strong>
          </div>

          {liveViewUrl ? (
            <img
              className="live-cctv-frame"
              src={liveViewUrl}
              alt="1번 축사 실시간 CCTV"
            />
          ) : (
            <div className="live-cctv-placeholder">
              <span>▶</span>
              <strong>{device ? "RTSP 웹 스트림을 준비하고 있습니다." : "축사 환경 시스템을 먼저 연결해 주세요."}</strong>
              <p>영상 서버의 상단 CCTV 실시간 신호를 불러오면 이 화면에서 바로 표시됩니다.</p>
            </div>
          )}

          <p className="live-cctv-note">
            hanwoo2 서버의 상단 CCTV 원본 실시간 신호를 동일하게 표시합니다.
          </p>
        </section>
        <section className="live-cctv-panel" aria-label="비문 귀표 분석 CCTV 화면">
          <div className="live-cctv-header">
            <div>
              <span>CAMERA-02</span>
              <h3>비문·귀표 RTSP 실시간 화면</h3>
            </div>
            <strong><i /> {liveViewUrl ? "스트림 연결" : "시스템 미연결"}</strong>
          </div>

          {liveViewUrl ? (
            <img
              className="live-cctv-frame"
              src={COWOW_0001_IDENTITY_VIEW_URL}
              alt="비문 귀표 분석용 실시간 RTSP CCTV"
            />
          ) : (
            <div className="live-cctv-placeholder">
              <span>▶</span>
              <strong>비문·귀표 분석 스트림을 준비하고 있습니다.</strong>
              <p>축사 환경 시스템을 연결하면 두 번째 CCTV 화면이 표시됩니다.</p>
            </div>
          )}

          <p className="live-cctv-note">
            hanwoo2 /top 비문·귀표 탭의 RTSP 실시간 신호를 동일하게 표시합니다.
          </p>
        </section>
        </div>
      )}
    </section>
  );
}

export default BarnEnvironmentControl;
