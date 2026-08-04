import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

const CONTROL_API_URL = import.meta.env.VITE_CONTROL_API_URL ?? "";
const DEVICE_STORAGE_KEY = "cowowRegisteredDevice";

const initialSensors = {
  temperature: 27.8,
  humidity: 68,
  ammonia: 18.4,
  carbonDioxide: 820,
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
    key: "ammonia",
    label: "암모니아",
    unit: "ppm",
    icon: "NH₃",
    precision: 1,
    warning: 20,
    danger: 25,
  },
  {
    key: "carbonDioxide",
    label: "이산화탄소",
    unit: "ppm",
    icon: "CO₂",
    precision: 0,
    warning: 1500,
    danger: 2500,
  },
];

function getSensorLevel(value, sensor) {
  if (value >= sensor.danger) return "danger";
  if (value >= sensor.warning) return "warning";
  return "normal";
}

function BarnEnvironmentControl() {
  const navigate = useNavigate();
  const [device] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(DEVICE_STORAGE_KEY)) ?? null;
    } catch {
      return null;
    }
  });
  const [sensors, setSensors] = useState(initialSensors);
  const [mode, setMode] = useState("auto");
  const [fanLevel, setFanLevel] = useState(2);
  const [isSpraying, setIsSpraying] = useState(false);
  const [controlMessage, setControlMessage] = useState("자동 환기 운전 중");
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

  const warnings = sensorCards.filter((sensor) => sensor.level !== "normal");

  useEffect(() => {
    const sensorTimer = window.setInterval(() => {
      setSensors((previous) => ({
        temperature: Math.max(20, previous.temperature + (Math.random() - 0.52) * 0.3),
        humidity: Math.max(40, Math.min(95, previous.humidity + (Math.random() - 0.5) * 1.2)),
        ammonia: Math.max(5, previous.ammonia + (Math.random() - 0.48) * 0.5),
        carbonDioxide: Math.max(500, previous.carbonDioxide + (Math.random() - 0.5) * 24),
      }));
    }, 8000);

    return () => {
      window.clearInterval(sensorTimer);
      if (sprayTimerRef.current) window.clearTimeout(sprayTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (mode !== "auto") return;

    const recommendedLevel =
      sensors.ammonia >= 25 || sensors.temperature >= 32
        ? 3
        : sensors.ammonia >= 20 || sensors.temperature >= 28
          ? 2
          : 1;

    setFanLevel(recommendedLevel);
    setControlMessage(`센서 기준으로 환기팬 ${recommendedLevel}단계를 자동 유지합니다.`);
  }, [mode, sensors.ammonia, sensors.temperature]);

  const sendControlCommand = async (actuator, value) => {
    if (!CONTROL_API_URL) return;

    const response = await fetch(`${CONTROL_API_URL}/actuators`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        deviceId: device?.deviceId,
        actuator,
        value,
      }),
    });

    if (!response.ok) throw new Error("장비 제어 명령 전송에 실패했습니다.");
  };

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

  return (
    <section className="environment-control-page">
      <div className="environment-control-header">
        <div>
          <span className="environment-live"><i /> 실시간 환경</span>
          <h2>축사 환경 제어</h2>
          <p>센서 상태를 확인하고 환기·살수 장치를 제어합니다.</p>
        </div>
        <button
          className={`sensor-connection-badge ${device ? "connected" : ""}`}
          type="button"
          onClick={() => navigate("/devices/setup")}
        >
          {device ? "● 원격 연결" : CONTROL_API_URL ? "장비 등록" : "데모 데이터"}
        </button>
      </div>

      <div className={`remote-connection-card ${device ? "connected" : "unregistered"}`}>
        <div className="remote-connection-main">
          <span className="remote-connection-icon">{device ? "⌁" : "+"}</span>
          <div>
            <strong>{device ? device.deviceName ?? device.deviceId : "ESP32 게이트웨이를 등록해 주세요"}</strong>
            <p>
              {device
                ? `ESP32 → ${device.networkName || "핫스팟"} → MQTT 서버 → 현재 기기`
                : "최초 한 번 등록하면 모바일 데이터에서도 원격 제어할 수 있습니다."}
            </p>
          </div>
        </div>
        <div className="remote-connection-meta">
          {device ? (
            <>
              <span><i /> 온라인</span>
              <small>마지막 통신 방금 전</small>
            </>
          ) : (
            <button type="button" onClick={() => navigate("/devices/setup")}>장비 등록하기</button>
          )}
        </div>
      </div>

      <div className="sensor-grid">
        {sensorCards.map((sensor) => (
          <article className={`sensor-card ${sensor.level}`} key={sensor.key}>
            <div className="sensor-card-top">
              <span className="sensor-icon">{sensor.icon}</span>
              <span className={`sensor-state ${sensor.level}`}>
                {sensor.level === "normal" ? "정상" : sensor.level === "warning" ? "주의" : "위험"}
              </span>
            </div>
            <span className="sensor-name">{sensor.label}</span>
            <strong>
              {sensor.value.toFixed(sensor.precision)}
              <small>{sensor.unit}</small>
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
    </section>
  );
}

export default BarnEnvironmentControl;
