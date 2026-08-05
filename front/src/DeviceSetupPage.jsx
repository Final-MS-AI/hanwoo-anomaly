import { useState } from "react";
import { useNavigate } from "react-router-dom";

const API_BASE_URL =
  import.meta.env.VITE_DEVICE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "";
const DEVICE_STORAGE_KEY = "cowowRegisteredDevice";
const SHOULD_USE_DEVICE_API = import.meta.env.PROD || Boolean(API_BASE_URL);

function DeviceSetupPage({ user }) {
  const navigate = useNavigate();
  const isGuest = user?.loginType === "guest";
  const [claimCode, setClaimCode] = useState(isGuest ? "guest" : "");
  const [barnName, setBarnName] = useState("1번 축사");
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("error");

  const sendClaimCode = async () => {
    setIsSendingCode(true);
    setMessage("");

    try {
      const response = await fetch(
        `${API_BASE_URL}/devices/claim-code/send`,
        {
          method: "POST",
          credentials: "include",
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

    if (!claimCode.trim()) {
      setMessageType("error");
      setMessage("일회용 등록 코드를 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setMessage("");

    const payload = {
      claimCode: claimCode.trim(),
      barnName: barnName.trim(),
    };

    try {
      let registeredDevice = {
        ...payload,
        deviceId: "ESP32-DEMO-01",
        deviceName: "ESP32 ESP32-DEMO-01",
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
        <p>로그인 계정으로 받은 일회용 코드 하나만 입력하면 장비가 연결됩니다.</p>
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
          <div><strong>ESP32 전원과 핫스팟 확인</strong><p>장비가 서버에 온라인으로 연결된 상태여야 합니다.</p></div>
        </li>
        <li>
          <span>2</span>
          <div>
            <strong>{isGuest ? "게스트 데모 코드 확인" : "로그인 이메일로 코드 받기"}</strong>
            <p>{isGuest ? "게스트는 데모 장비만 임시 연결할 수 있습니다." : "인증된 이메일로 10분 동안 유효한 코드를 받습니다."}</p>
          </div>
        </li>
        <li>
          <span>3</span>
          <div><strong>등록 코드 입력</strong><p>장비 ID나 QR 없이 코드만으로 연결합니다.</p></div>
        </li>
      </ol>

      <form className="device-claim-form" onSubmit={registerDevice}>
        <div className="device-account-card">
          <div>
            <span>코드를 받을 계정</span>
            <strong>{isGuest ? "게스트 데모 계정" : user?.email ?? "이메일 정보 없음"}</strong>
          </div>
          {!isGuest && (
            <button
              type="button"
              className="device-send-code-button"
              disabled={isSendingCode || !user?.email}
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
          {isSubmitting ? "등록 확인 중..." : isGuest ? "데모 장비 연결" : "장비 연결하고 제어 시작"}
        </button>
      </form>

      <p className="device-setup-note">
        등록 코드는 한 번 사용하면 폐기되며 장비 비밀키는 브라우저나 이메일로 전달되지 않습니다.
      </p>
    </section>
  );
}

export default DeviceSetupPage;
