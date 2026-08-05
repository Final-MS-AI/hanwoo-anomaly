import { useState } from "react";
import { useNavigate } from "react-router-dom";

const API_BASE_URL =
  import.meta.env.VITE_DEVICE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "";
const DEVICE_STORAGE_KEY = "cowowRegisteredDevice";

function DeviceSetupPage() {
  const navigate = useNavigate();
  const [deviceId, setDeviceId] = useState("");
  const [claimCode, setClaimCode] = useState("");
  const [barnName, setBarnName] = useState("1번 축사");
  const [networkName, setNetworkName] = useState("시연용 핫스팟");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  const registerDevice = async (event) => {
    event.preventDefault();

    if (!deviceId.trim() || !claimCode.trim()) {
      setMessage("장비 ID와 일회용 등록 코드를 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setMessage("");

    const payload = {
      deviceId: deviceId.trim(),
      claimCode: claimCode.trim(),
      barnName: barnName.trim(),
      networkName: networkName.trim(),
    };

    try {
      let registeredDevice = payload;

      if (import.meta.env.VITE_DEVICE_API_URL) {
        const response = await fetch(`${API_BASE_URL}/devices/claim`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail ?? data.message ?? "장비 등록에 실패했습니다.");
        }

        registeredDevice = { ...payload, ...data.device };
      }

      localStorage.setItem(
        DEVICE_STORAGE_KEY,
        JSON.stringify({
          ...registeredDevice,
          deviceName: registeredDevice.deviceName ?? `ESP32 ${payload.deviceId}`,
          registeredAt: new Date().toISOString(),
        }),
      );

      navigate("/control", { replace: true });
    } catch (error) {
      setMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="device-setup-page">
      <div className="device-setup-header">
        <span>최초 1회 설정</span>
        <h2>ESP32 게이트웨이 등록</h2>
        <p>ESP32는 핫스팟으로 서버에 연결되고, 사용자는 모바일 데이터로 원격 제어합니다.</p>
      </div>

      <div className="device-network-flow" aria-label="원격 연결 흐름">
        <div><strong>ESP32</strong><span>축사 장비</span></div>
        <b>→</b>
        <div><strong>핫스팟</strong><span>2.4GHz</span></div>
        <b>→</b>
        <div><strong>서버</strong><span>MQTT·API</span></div>
        <b>→</b>
        <div><strong>웹·앱</strong><span>모바일 데이터</span></div>
      </div>

      <ol className="device-setup-steps">
        <li>
          <span>1</span>
          <div><strong>휴대폰 핫스팟 켜기</strong><p>2.4GHz 또는 호환성 모드로 켜 주세요.</p></div>
        </li>
        <li>
          <span>2</span>
          <div><strong>ESP32 전원 켜기</strong><p>최초 설정 펌웨어가 핫스팟 정보를 받은 상태여야 합니다.</p></div>
        </li>
        <li>
          <span>3</span>
          <div><strong>장비를 축사 계정에 등록</strong><p>장비 QR에 적힌 ID와 일회용 코드를 입력합니다.</p></div>
        </li>
      </ol>

      <form className="device-claim-form" onSubmit={registerDevice}>
        <label>
          <span>장비 ID</span>
          <input
            value={deviceId}
            placeholder="예: COWOW-GW-000001"
            autoCapitalize="characters"
            onChange={(event) => setDeviceId(event.target.value)}
          />
        </label>
        <label>
          <span>일회용 등록 코드</span>
          <input
            value={claimCode}
            placeholder="예: REG-48M2-9QKF"
            autoCapitalize="characters"
            onChange={(event) => setClaimCode(event.target.value)}
          />
        </label>
        <div className="device-form-row">
          <label>
            <span>설치 축사</span>
            <input value={barnName} onChange={(event) => setBarnName(event.target.value)} />
          </label>
          <label>
            <span>ESP32 네트워크</span>
            <input value={networkName} onChange={(event) => setNetworkName(event.target.value)} />
          </label>
        </div>

        {message && <p className="device-setup-message">{message}</p>}

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "등록 확인 중..." : "장비 등록하고 제어 시작"}
        </button>
      </form>

      <p className="device-setup-note">
        현재 별도 장비 API가 설정되지 않은 경우 입력한 정보는 이 기기의 데모 등록 정보로 저장됩니다.
      </p>
    </section>
  );
}

export default DeviceSetupPage;
