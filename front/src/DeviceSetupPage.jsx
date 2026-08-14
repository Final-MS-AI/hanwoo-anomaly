import { useState } from "react";
import { useNavigate } from "react-router-dom";

const API_BASE_URL =
  import.meta.env.VITE_DEVICE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";
const DEVICE_STORAGE_KEY = "cowowRegisteredDevice";
const SHOULD_USE_DEVICE_API = import.meta.env.PROD || Boolean(API_BASE_URL);
const PUBLIC_DEVICE_NUMBER = "COWOW-0001";

async function readApiResponse(response) {
  const text = await response.text();

  if (!text) return {};

  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

function DeviceSetupPage({ user }) {
  const navigate = useNavigate();
  const isGuest = user?.loginType === "guest";
  const [setupMode, setSetupMode] = useState("register");
  const [deviceNumber, setDeviceNumber] = useState(isGuest ? "guest" : "");
  const [claimCode, setClaimCode] = useState(isGuest ? "guest" : "");
  const [shareCode, setShareCode] = useState("");
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
    if (!deviceNumber.trim()) {
      setMessageType("error");
      setMessage("장비 번호를 입력해 주세요.");
      return;
    }

    if (!user?.email) {
      setMessageType("error");
      setMessage("로그인 계정의 이메일 정보를 확인할 수 없습니다. 다시 로그인해 주세요.");
      return;
    }

    if (!validateDeviceNumber()) return;

    setIsSendingCode(true);
    setMessage("");
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 15000);

    try {
      const response = await fetch(
        `${API_BASE_URL}/devices/claim-code/send`,
        {
          method: "POST",
          credentials: "include",
          signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ deviceId: normalizedDeviceNumber }),
        },
      );
      const data = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(
          data.detail ??
            data.message ??
            `등록 코드 발송에 실패했습니다. (HTTP ${response.status})`,
        );
      }

      setMessageType("success");
      setMessage(
        data.message ??
          `${user?.email ?? "로그인 이메일"}로 등록 코드를 보냈습니다.`,
      );
    } catch (error) {
      setMessageType("error");
      setMessage(
        error.name === "AbortError"
          ? "서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
          : error.message,
      );
    } finally {
      window.clearTimeout(timeoutId);
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
        const data = await readApiResponse(response);

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

  const joinSharedDevice = async (event) => {
    event.preventDefault();

    if (!shareCode.trim()) {
      setMessageType("error");
      setMessage("이메일로 받은 공유 인증 코드를 입력해 주세요.");
      return;
    }

    setIsSubmitting(true);
    setMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/devices/share/join`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shareCode: shareCode.trim() }),
      });
      const data = await readApiResponse(response);

      if (!response.ok) {
        throw new Error(data.detail ?? "가족 공유 장비 연결에 실패했습니다.");
      }

      localStorage.setItem(
        DEVICE_STORAGE_KEY,
        JSON.stringify({
          ...data.device,
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
        <h2>축사 환경 시스템 연결</h2>
        <p>대표 시스템 번호 하나로 센서, 로컬 분석 서버와 CCTV 스트림을 연결합니다.</p>
      </div>

      <div className="device-network-flow" aria-label="원격 연결 흐름">
        <div><strong>환경 시스템</strong><span>센서·제어</span></div>
        <b>→</b>
        <div><strong>핫스팟</strong><span>2.4GHz</span></div>
        <b>→</b>
        <div><strong>분석 서버</strong><span>RTSP·HTTPS</span></div>
        <b>→</b>
        <div><strong>웹·앱</strong><span>원격 제어</span></div>
      </div>

      <ol className="device-setup-steps">
        <li>
          <span>1</span>
          <div><strong>시스템 번호 확인</strong><p>설치 안내서에 적힌 COWOW 환경 시스템 번호를 확인합니다.</p></div>
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
          <div><strong>환경 시스템 연결</strong><p>센서 제어와 CCTV 분석 스트림을 한 번에 연결합니다.</p></div>
        </li>
      </ol>

      {!isGuest && (
        <div className="device-setup-mode" role="tablist" aria-label="장비 연결 방식">
          <button
            className={setupMode === "register" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={setupMode === "register"}
            onClick={() => {
              setSetupMode("register");
              setMessage("");
            }}
          >
            내 환경 시스템 등록
          </button>
          <button
            className={setupMode === "share" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={setupMode === "share"}
            onClick={() => {
              setSetupMode("share");
              setMessage("");
            }}
          >
            가족 공유 참여
          </button>
        </div>
      )}

      {setupMode === "share" && !isGuest ? (
        <form className="device-claim-form shared-device-join-form" onSubmit={joinSharedDevice}>
          <div className="shared-device-join-guide">
            <strong>장비 번호 없이 연결할 수 있습니다.</strong>
            <p>관리자가 내 로그인 이메일로 보낸 일회용 인증 코드만 입력하세요.</p>
          </div>

          <label>
            <span>가족 공유 인증 코드</span>
            <input
              value={shareCode}
              placeholder="예: F7K2-M9Q4"
              autoCapitalize="characters"
              autoComplete="one-time-code"
              onChange={(event) => setShareCode(event.target.value.toUpperCase())}
            />
          </label>

          {message && (
            <p className={`device-setup-message ${messageType}`}>{message}</p>
          )}

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "공유 권한 확인 중..." : "공유 장비 연결"}
          </button>
        </form>
      ) : (
      <form className="device-claim-form" onSubmit={registerDevice}>
        <label>
          <span>환경 시스템 번호</span>
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
              disabled={isSendingCode}
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
              : "환경 시스템 연결하고 시작"}
        </button>
      </form>
      )}

      <p className="device-setup-note">
        시스템 번호는 같은 축사의 센서, 로컬 분석 서버와 CCTV를 묶고 일회용 코드는 등록 권한을 확인합니다.
      </p>
    </section>
  );
}

export default DeviceSetupPage;
