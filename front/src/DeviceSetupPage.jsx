import { useState } from "react";
import { useNavigate } from "react-router-dom";

const API_BASE_URL =
  import.meta.env.VITE_DEVICE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "";
const DEVICE_STORAGE_KEY = "cowowRegisteredDevice";
const SHOULD_USE_DEVICE_API = import.meta.env.PROD || Boolean(API_BASE_URL);
const PUBLIC_DEVICE_NUMBER = "COWOW-0001";

function DeviceSetupPage({ user }) {
  const navigate = useNavigate();
  const isGuest = user?.loginType === "guest";
  const [deviceNumber, setDeviceNumber] = useState(isGuest ? "guest" : "");
  const [claimCode, setClaimCode] = useState(isGuest ? "guest" : "");
  const [barnName, setBarnName] = useState("1번 축사");
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("error");

  const normalizedDeviceNumber = isGuest
    ? "guest"
    : deviceNumber.trim().toUpperCase();

  const validateDeviceNumber = () => {
    if (
      (isGuest && normalizedDeviceNumber === "guest") ||
      normalizedDeviceNumber === PUBLIC_DEVICE_NUMBER
    ) {
      return true;
    }

    setMessageType("error");
    setMessage("잘못된 장비 번호입니다.");
    return false;
  };

  const sendClaimCode = async () => {
    if (!validateDeviceNumber()) return;

    setIsSendingCode(true);
    setMessage("");

    try {
      const response = await fetch(
        `${API_BASE_URL}/devices/claim-code/send`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ deviceId: normalizedDeviceNumber }),
        },
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ?? data.message ?? "등록 코드 발송에 실패했습니다.",
        );
      }

      setMessageType("success");
      setMessage(
        data.message ??
          `${user?.email ?? "로그인 이메일"}로 등록 코드를 보냈습니다.`,
      );
    } catch (error) {
      setMessageType("error");
      setMessage(error.message);
    } finally {
      setIsSendingCode(false);
    }
  };

  const registerDevice = async (event) => {
    event.preventDefault();

    if (!validateDeviceNumber()) return;

    if (!claimCode.trim()) {
      setMessageType("error");
      setMessage("일회용 등록 코드를 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setMessage("");

    const payload = {
      deviceId: normalizedDeviceNumber,
      claimCode: claimCode.trim(),
      barnName: barnName.trim(),
    };

    try {
      let registeredDevice = {
        ...payload,
        deviceName: isGuest
          ? "게스트 데모 장비"
          : `ESP32 ${normalizedDeviceNumber}`,
      };

      if (SHOULD_USE_DEVICE_API) {
        const response = await fetch(`${API_BASE_URL}/devices/claim`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await response.json();

        if (!response.ok) {
          throw new Error(
            data.detail ?? data.message ?? "장비 등록에 실패했습니다.",
          );
        }

        registeredDevice = { ...registeredDevice, ...data.device };
      }

      localStorage.setItem(
        DEVICE_STORAGE_KEY,
        JSON.stringify({
          ...registeredDevice,
          registeredAt: new Date().toISOString(),
        }),
      );

      navigate("/control", { replace: true });
    } catch (error) {
      setMessageType("error");
      setMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="device-setup-page">
      <div className="device-setup-header">
        <span>최초 1회 설정</span>
        <h2>축사 장비 연결</h2>
        <p>장비 번호를 확인하고 이메일로 받은 일회용 코드를 입력해 연결합니다.</p>
      </div>

      <div className="device-network-flow" aria-label="원격 연결 흐름">
        <div><strong>ESP32</strong><span>축사 장비</span></div>
        <b>→</b>
        <div><strong>핫스팟</strong><span>2.4GHz</span></div>
        <b>→</b>
        <div><strong>서버</strong><span>HTTPS API</span></div>
        <b>→</b>
        <div><strong>웹·앱</strong><span>원격 제어</span></div>
      </div>

      <ol className="device-setup-steps">
        <li>
          <span>1</span>
          <div><strong>장비 번호 확인</strong><p>장비 본체 또는 포장지에 적힌 COWOW 번호를 확인합니다.</p></div>
        </li>
        <li>
          <span>2</span>
          <div>
            <strong>{isGuest ? "게스트 데모 정보 확인" : "로그인 이메일로 코드 받기"}</strong>
            <p>{isGuest ? "게스트는 데모 장비만 임시 연결할 수 있습니다." : "선택한 장비의 일회용 등록 코드를 이메일로 받습니다."}</p>
          </div>
        </li>
        <li>
          <span>3</span>
          <div><strong>장비 연결</strong><p>등록 코드와 설치 축사를 확인한 후 제어를 시작합니다.</p></div>
        </li>
      </ol>

      <form className="device-claim-form" onSubmit={registerDevice}>
        <label>
          <span>장비 번호</span>
          <input
            value={deviceNumber}
            readOnly={isGuest}
            placeholder="예: COWOW-0001"
            autoCapitalize="characters"
            autoComplete="off"
            onChange={(event) => {
              setDeviceNumber(event.target.value.toUpperCase());
            }}
          />
        </label>

        <div className="device-account-card">
          <div>
            <span>코드를 받을 계정</span>
            <strong>{isGuest ? "게스트 데모 계정" : user?.email ?? "이메일 정보 없음"}</strong>
          </div>
          {!isGuest && (
            <button
              type="button"
              className="device-send-code-button"
              disabled={isSendingCode || !user?.email || !deviceNumber.trim()}
              onClick={sendClaimCode}
            >
              {isSendingCode ? "발송 중..." : "등록 코드 받기"}
            </button>
          )}
        </div>

        <label>
          <span>일회용 등록 코드</span>
          <input
            value={claimCode}
            readOnly={isGuest}
            placeholder="예: A7K9-P2M4"
            autoCapitalize="characters"
            autoComplete="one-time-code"
            onChange={(event) => setClaimCode(event.target.value)}
          />
        </label>

        <label>
          <span>설치 축사</span>
          <input
            value={barnName}
            placeholder="예: 1번 축사"
            onChange={(event) => setBarnName(event.target.value)}
          />
        </label>

        {message && (
          <p className={`device-setup-message ${messageType}`}>{message}</p>
        )}

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting
            ? "등록 확인 중..."
            : isGuest
              ? "게스트 장비 연결"
              : "장비 연결하고 제어 시작"}
        </button>
      </form>

      <p className="device-setup-note">
        장비 번호는 장비를 구분하고, 일회용 코드는 해당 장비의 등록 권한을 확인하는 데 사용됩니다.
      </p>
    </section>
  );
}

export default DeviceSetupPage;
