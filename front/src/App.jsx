import { useCallback, useEffect, useState } from "react";
import { GoogleLogin, googleLogout } from "@react-oauth/google";
import DemoVideoSelector from "./DemoVideoSelector.jsx";
import BottomNavigation from "./BottomNavigation.jsx";
import AbnormalCattleDashboard from "./AbnormalCattleDashboard.jsx";
import RagChatbot from "./RagChatbot.jsx";
import BarnEnvironmentControl from "./BarnEnvironmentControl.jsx";
import DeviceSetupPage from "./DeviceSetupPage.jsx";
import {
  createGuestSession,
  exchangeGoogleCredential,
  getCurrentUser,
  GOOGLE_CLIENT_ID,
  hasAndroidAuthBridge,
  logoutSession,
  startSocialLogin,
} from "./auth.js";
import "./kakao-login.css";

import "./mobile-header-fix.css";
import {
  Navigate,
  Route,
  Routes,
  useNavigate,
  useLocation,
} from "react-router-dom";

// 비문 API는 프론트가 두 도메인에서 서빙되므로 반드시 절대 주소로 고정한다.
const MUZZLE_API = "https://hanwoo.koreacentral.cloudapp.azure.com";
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

// 비문 등록 시 사진 간 일치도 판정에 쓰는 기준값 (백엔드와 동일)
const MUZZLE_CONSISTENCY_THRESHOLD = 0.45;

function LoginPage({ user, setUser }) {
  const navigate = useNavigate();
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const isAndroidApp = hasAndroidAuthBridge();

  const completeGoogleLogin = useCallback(
    async (credential) => {
      try {
        if (!credential) {
          setErrorMessage("Google 인증 정보를 받지 못했습니다.");
          return;
        }

        setErrorMessage("");
        setIsLoggingIn(true);

        const authenticatedUser = await exchangeGoogleCredential(credential);

        setUser(authenticatedUser);

        setErrorMessage("");
        navigate("/dashboard");
      } catch (error) {
        console.error("Google login error:", error);

        setErrorMessage(
          error.message ?? "Google 로그인 정보를 처리하지 못했습니다.",
        );
      } finally {
        setIsLoggingIn(false);
      }
    },
    [navigate, setUser],
  );

  const handleGoogleLogin = (credentialResponse) => {
    completeGoogleLogin(credentialResponse?.credential);
  };

  useEffect(() => {
    if (!isAndroidApp) {
      return undefined;
    }

    const handleNativeSuccess = (event) => {
      completeGoogleLogin(event.detail?.idToken);
    };

    const handleNativeError = (event) => {
      setIsLoggingIn(false);
      setErrorMessage(
        event.detail?.message ?? "Google 로그인에 실패했습니다.",
      );
    };

    window.addEventListener("cowow:google-login", handleNativeSuccess);
    window.addEventListener("cowow:google-login-error", handleNativeError);

    return () => {
      window.removeEventListener("cowow:google-login", handleNativeSuccess);
      window.removeEventListener(
        "cowow:google-login-error",
        handleNativeError,
      );
    };
  }, [completeGoogleLogin, isAndroidApp]);

  const handleNativeGoogleLogin = () => {
    setErrorMessage("");
    setIsLoggingIn(true);

    try {
      window.COWOW_ANDROID.googleLogin();
    } catch (error) {
      console.error("Native Google login error:", error);
      setIsLoggingIn(false);
      setErrorMessage("앱에서 Google 로그인을 시작하지 못했습니다.");
    }
  };

  const handleGuestLogin = async () => {
    try {
      setErrorMessage("");
      setIsLoggingIn(true);

      const guestUser = await createGuestSession();
      setUser(guestUser);
      navigate("/dashboard");
    } catch (error) {
      console.error("Guest login error:", error);
      setErrorMessage(error.message ?? "게스트 로그인에 실패했습니다.");
    } finally {
      setIsLoggingIn(false);
    }
  };

  if (user) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <main className="page">
      <section className="login-card">
        <div className="login-brand">
          <img
            className="login-cowow-logo"
            src="/cowow-logo.png?v=20260811-1"
            alt="COWOW"
          />

          <img
            className="login-bull-image"
            src="/cowow-bull.png?v=20260811-1"
            alt="COWOW 황소 캐릭터"
          />
        </div>

        <div className="social-login-buttons">
          <div className="google-login-wrapper">
            {isAndroidApp ? (
              <button
                className="native-google-login-button"
                type="button"
                onClick={handleNativeGoogleLogin}
                disabled={isLoggingIn}
              >
                <span>
                  {isLoggingIn ? "Google 로그인 중" : "Google로 로그인"}
                </span>
              </button>
            ) : GOOGLE_CLIENT_ID ? (
              <GoogleLogin
                onSuccess={handleGoogleLogin}
                onError={() => {
                  setErrorMessage("Google 로그인에 실패했습니다.");
                }}
                text="signin"
                locale="ko"
                size="medium"
                width="100"
              />
            ) : (
              <p className="google-login-config-error" role="alert">
                Google 로그인 설정을 불러오지 못했습니다.
              </p>
            )}
          </div>

          <button
            className="kakao-login-image-button"
            type="button"
            onClick={() => {
              startSocialLogin("kakao");
            }}
            aria-label="카카오 로그인"
          >
            <img src="/kakao-login.png?v=20260811-1" alt="카카오 로그인" />
          </button>

          <button
            className="social-provider-button naver-login-button"
            type="button"
            onClick={() => {
              startSocialLogin("naver");
            }}
            aria-label="네이버 로그인"
          >
            <span className="social-provider-logo naver-logo">N</span>
            <span>로그인</span>
          </button>
        </div>

        <div className="login-divider">
          <span>또는</span>
        </div>

        <button
          className="guest-login-button"
          type="button"
          onClick={handleGuestLogin}
          disabled={isLoggingIn}
        >
          {isLoggingIn ? "로그인 중..." : "게스트로 로그인"}
        </button>

        {errorMessage && <p className="error-message">{errorMessage}</p>}
      </section>
    </main>
  );
}

function RegisterCattleModal({ onClose, onRegistered, embedded = false }) {
  // ── 비문 사진 상태는 이 컴포넌트에 단 한 번만 선언한다 ──
  const [muzzleFiles, setMuzzleFiles] = useState([]);
  const [muzzlePreviews, setMuzzlePreviews] = useState([]);
  const [enrollResult, setEnrollResult] = useState(null);

  const [earTagImage, setEarTagImage] = useState(null);
  const [earTagNumber, setEarTagNumber] = useState("");
  const [ocrResult, setOcrResult] = useState(null);
  const [ocrStatus, setOcrStatus] = useState("idle");
  const [ocrMessage, setOcrMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  // 썸네일 URL은 파일이 바뀔 때만 만들고, 바뀌면 이전 것을 해제한다(메모리 누수 방지).
  useEffect(() => {
    if (muzzleFiles.length === 0) {
      setMuzzlePreviews([]);
      return undefined;
    }

    const urls = muzzleFiles.map((file) => URL.createObjectURL(file));
    setMuzzlePreviews(urls);

    return () => {
      urls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [muzzleFiles]);

  const handleMuzzleFilesChange = (event) => {
    setMuzzleFiles(Array.from(event.target.files ?? []));
    setEnrollResult(null);
    setErrorMessage("");
  };

  const handleEarTagImageChange = async (event) => {
    const file = event.target.files?.[0] ?? null;

    setEarTagImage(file);
    setEarTagNumber("");
    setOcrResult(null);
    setOcrMessage("");
    setErrorMessage("");

    if (!file) {
      setOcrStatus("idle");
      return;
    }

    setOcrStatus("loading");

    try {
      const formData = new FormData();
      formData.append("ear_tag_image", file);

      const response = await fetch(`${API_BASE_URL}/ocr/ear-tag`, {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail ?? "귀표 번호 인식에 실패했습니다.");
      }

      setEarTagNumber(result.ear_tag_number ?? "");
      setOcrResult(result);

      if (result.success) {
        setOcrStatus("success");
        setOcrMessage(
          "사진에서 귀표 번호를 정상적으로 인식했습니다. 결과를 확인해 주세요."
        );
      } else if (result.reason === "single_image_unconfirmed") {
        setOcrStatus("warning");
        setOcrMessage(
          "귀표 번호를 인식했지만 정확한 등록을 위해 사용자 확인이 필요합니다."
        );
      } else if (result.reason === "ear_tag_not_detected") {
        setOcrStatus("error");
        setOcrMessage(
          "사진에서 귀표를 찾지 못했습니다. 귀표가 화면에 크게 보이도록 다시 촬영해 주세요."
        );
      } else if (result.reason === "crop_quality_rejected") {
        setOcrStatus("error");
        setOcrMessage(
          "귀표는 감지했지만 이미지 품질이 낮아 번호를 판독하지 못했습니다. 흔들림, 거리, 빛 반사를 확인한 뒤 다시 촬영해 주세요."
        );
      } else if (result.reason === "ear_tag_number_not_found") {
        setOcrStatus("error");
        setOcrMessage(
          "귀표는 감지했지만 번호를 읽지 못했습니다. 더 선명한 사진으로 다시 시도하거나 귀표 번호를 직접 입력해 주세요."
        );
      } else {
        setOcrStatus("error");
        setOcrMessage(
          "귀표 번호를 자동으로 판독하지 못했습니다. 다른 사진으로 다시 시도하거나 직접 입력해 주세요."
        );
      }
    } catch (error) {
      console.error("Ear tag OCR error:", error);
      setOcrStatus("error");
      setOcrMessage("자동 인식에 실패했습니다. 귀표 번호를 직접 입력해 주세요.");
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setErrorMessage("");
    setEnrollResult(null);

    const normalizedEarTagNumber = earTagNumber.trim();

    if (!earTagImage) {
      setErrorMessage("귀표 사진을 선택해 주세요.");
      return;
    }

    if (!normalizedEarTagNumber) {
      setErrorMessage("귀표 번호를 확인하거나 직접 입력해 주세요.");
      return;
    }

    if (muzzleFiles.length === 0) {
      setErrorMessage("비문 사진을 1장 이상 선택해 주세요.");
      return;
    }

    setIsSubmitting(true);

    // 가축이력번호는 숫자만 남겨 12자리 문자열로 통일한다(귀표 OCR이 9자리를 주는 경우 대비).
    const nationalId = normalizedEarTagNumber
      .replace(/\D/g, "")
      .slice(-12)
      .padStart(12, "0");

    // ── ① 비문 임베딩 등록 (개체 식별 파트) — /cattle 보다 먼저 호출한다 ──
    let muzzleOk = false;

    try {
      const muzzleForm = new FormData();
      muzzleForm.append("national_id", nationalId);
      muzzleForm.append("barn_id", "");
      muzzleFiles.forEach((file) => muzzleForm.append("files", file));

      // Content-Type을 직접 지정하지 않는다. 브라우저가 boundary와 함께 자동 설정한다.
      const muzzleResponse = await fetch(`${MUZZLE_API}/muzzle/enroll`, {
        method: "POST",
        body: muzzleForm,
      });

      let payload = null;
      try {
        payload = await muzzleResponse.json();
      } catch {
        payload = null;
      }

      if (muzzleResponse.ok) {
        muzzleOk = true;
        setEnrollResult({ status: "success", data: payload ?? {} });
        console.log("[비문] 등록 완료:", payload);
      } else if (
        muzzleResponse.status === 422 &&
        payload?.detail?.error === "inconsistent_images"
      ) {
        setEnrollResult({
          status: "inconsistent",
          message:
            payload.detail.message ??
            "사진들이 서로 다른 개체로 판정되었습니다. 같은 소의 코 사진만 넣어 주세요.",
        });
        console.warn("[비문] 사진 일치도 미달:", payload.detail);
      } else {
        setEnrollResult({
          status: "error",
          message: `비문 등록에 실패했습니다. (HTTP ${muzzleResponse.status})`,
        });
        console.error("[비문] 등록 실패", muzzleResponse.status, payload);
      }
    } catch (error) {
      setEnrollResult({
        status: "error",
        message: `비문 API에 연결하지 못했습니다. (${error.message})`,
      });
      console.error("[비문] 등록 오류:", error);
    }

    // 비문 등록이 실패하면 개체 정보만 저장하지 않는다(사진을 고쳐 다시 시도).
    if (!muzzleOk) {
      setIsSubmitting(false);
      return;
    }

    // ── ② 팀원 백엔드 개체 등록 — 여기서 실패해도 위 비문 등록은 이미 완료됐다 ──
    try {
      const formData = new FormData();
      formData.append("ear_tag_number", normalizedEarTagNumber);
      formData.append("ear_tag_image", earTagImage);
      formData.append("muzzle_image", muzzleFiles[0]); // 팀원 백엔드는 1장만 받는다

      const response = await fetch(`${API_BASE_URL}/cattle`, {
        method: "POST",
        body: formData,
      });

      let result = null;
      try {
        result = await response.json();
      } catch {
        result = null;
      }

      if (!response.ok) {
        const detail =
          typeof result?.detail === "string" ? result.detail : null;
        throw new Error(
          detail ?? `개체 정보 저장에 실패했습니다. (HTTP ${response.status})`,
        );
      }

      onRegistered(result);
      onClose();
    } catch (error) {
      console.error("Cattle registration error:", error);
      setErrorMessage(
      "비문 등록은 완료되었습니다. 개체 기본정보 저장은 백엔드 준비 중입니다.",
    );
      setIsSubmitting(false);
    }
  };

  const enrollData = enrollResult?.status === "success" ? enrollResult.data : null;
  const consistency =
    typeof enrollData?.consistency === "number" ? enrollData.consistency : null;

  return (
    <div className={embedded ? "register-page-container" : "modal-backdrop"}>
      <section className={embedded ? "register-page-card" : "modal-card"}>
        <div className="modal-header">
          <h2>소 등록하기</h2>
          {!embedded && (
            <button
              className="modal-close-button"
              type="button"
              onClick={onClose}
              aria-label="등록창 닫기"
            >
              ×
            </button>
          )}
        </div>

        <form className="cattle-form" onSubmit={handleSubmit}>
          <label className="image-upload-field">
            귀표 사진
            <span className="upload-description">
              귀표 번호가 선명하게 보이는 사진을 등록해 주세요.
            </span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={handleEarTagImageChange}
              required
            />
            {earTagImage && (
              <span className="selected-file">선택됨: {earTagImage.name}</span>
            )}
          </label>

          {earTagImage && (
            <label className="ocr-result-field">
              귀표 번호
              <span className="upload-description">
                자동 인식 결과를 확인하고 틀리면 수정해 주세요.
              </span>
              <div className="ocr-input-wrapper">
                <input
                  className="ocr-result-input"
                  type="text"
                  value={earTagNumber}
                  onChange={(event) => {
                    setEarTagNumber(event.target.value);
                  }}
                  placeholder={
                    ocrStatus === "loading"
                      ? "귀표 번호 인식 중..."
                      : "귀표 번호를 입력해 주세요."
                  }
                  disabled={ocrStatus === "loading"}
                  required
                />

                {ocrStatus === "loading" && (
                  <span className="ocr-status-badge loading">분석 중</span>
                )}

                {ocrStatus === "success" && (
                  <span className="ocr-status-badge success">자동 인식</span>
                )}

                {ocrStatus === "warning" && (
                  <span className="ocr-status-badge warning">확인 필요</span>
                )}

                {ocrStatus === "error" && (
                  <span className="ocr-status-badge error">직접 입력</span>
                )}
              </div>

              {ocrMessage && (
                <span className={`ocr-message ${ocrStatus}`}>{ocrMessage}</span>
              )}

              {ocrResult &&
                ocrStatus === "error" &&
                [
                  "ear_tag_not_detected",
                  "crop_quality_rejected",
                  "ear_tag_number_not_found",
                ].includes(ocrResult.reason) && (
                  <section className="ocr-failure-panel">
                    <strong className="ocr-failure-title">
                      {ocrResult.reason === "ear_tag_not_detected"
                        ? "귀표를 찾지 못했습니다."
                        : ocrResult.reason === "crop_quality_rejected"
                          ? "귀표 이미지 품질이 부족합니다."
                          : "귀표 번호를 읽지 못했습니다."}
                    </strong>

                    <span className="ocr-failure-description">
                      {ocrResult.reason === "ear_tag_not_detected"
                        ? "귀표가 화면 중앙에 크고 선명하게 보이도록 다시 촬영해 주세요."
                        : ocrResult.reason === "crop_quality_rejected"
                          ? "사진의 흔들림, 촬영 거리, 빛 반사를 확인한 뒤 다시 촬영해 주세요."
                          : "귀표 번호가 선명하게 보이는 다른 사진으로 다시 시도하거나 번호를 직접 입력해 주세요."}
                    </span>

                    <span className="ocr-failure-help">
                      다른 사진을 선택하면 AI 분석을 다시 실행합니다.
                    </span>
                  </section>
                )}

              {ocrResult?.ocr_log_id &&
                (ocrResult.success ||
                  ocrResult.reason === "single_image_unconfirmed") && (
                  <section className="ocr-visualization">
                  <div className="ocr-visualization-header">
                    <strong>AI 귀표 분석 과정</strong>
                    <span>
                      객체 탐지 후 OCR로 귀표 번호를 판독합니다.
                    </span>
                  </div>

                  <div className="ocr-visualization-grid">
                    <article className="ocr-visualization-card">
                      <div className="ocr-step-label">
                        1. YOLO 귀표 위치 탐지
                      </div>

                      <img
                        className="ocr-visualization-image"
                        src={`${API_BASE_URL}/ocr/results/${ocrResult.ocr_log_id}/annotated`}
                        alt="YOLO가 귀표 위치를 탐지한 결과"
                      />

                      <span className="ocr-visualization-caption">
                        AI가 이미지에서 귀표 위치를 Bounding Box로 탐지합니다.
                      </span>
                    </article>

                    <article className="ocr-visualization-card">
                      <div className="ocr-step-label">
                        2. OCR 분석 영역
                      </div>

                      <img
                        className="ocr-visualization-image crop"
                        src={`${API_BASE_URL}/ocr/results/${ocrResult.ocr_log_id}/evidence`}
                        alt="OCR에 사용된 귀표 영역"
                      />

                      <span className="ocr-visualization-caption">
                        탐지한 귀표 영역만 잘라 OCR 판독에 사용합니다.
                      </span>
                    </article>
                  </div>

                  <div className="ocr-visualization-result">
                    <div>
                      <span>판독 귀표번호</span>
                      <strong>
                        {ocrResult.ear_tag_number ?? "-"}
                      </strong>
                    </div>

                    <div>
                      <span>OCR 신뢰도</span>
                      <strong>
                        {Math.round(
                          (ocrResult.confidence ?? 0) * 1000
                        ) / 10}%
                      </strong>
                    </div>

                    <div>
                      <span>등록 개체</span>
                      <strong>
                        {ocrResult.registered ? "확인됨" : "미등록"}
                      </strong>
                    </div>

                    <div>
                      <span>판독 상태</span>
                      <strong>
                        {ocrResult.requires_human_confirmation
                          ? "사용자 확인 필요"
                          : "확인 완료"}
                      </strong>
                    </div>
                  </div>
                </section>
              )}
            </label>
          )}

          <label className="image-upload-field">
            비문 사진
            <span className="upload-description">
              코가 화면에 가득 차도록 30cm 거리에서 정면 촬영해 주세요. 얼굴이나
              전신이 나오면 인식되지 않습니다. 각도를 바꿔 3장 이상 선택하면
              정확도가 올라갑니다.
            </span>

            <input
              type="file"
              name="muzzle_files"
              accept="image/*"
              multiple
              onChange={handleMuzzleFilesChange}
            />

            {muzzleFiles.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <b>{muzzleFiles.length}장 선택됨</b>
                {muzzleFiles.length < 3 && (
                  <span style={{ color: "#b45309", marginLeft: 8 }}>
                    각도를 바꿔 3장 이상 넣으면 정확도가 올라갑니다
                  </span>
                )}

                <div
                  style={{
                    display: "flex",
                    gap: 6,
                    marginTop: 6,
                    flexWrap: "wrap",
                  }}
                >
                  {muzzlePreviews.map((url, index) => (
                    <img
                      key={url}
                      src={url}
                      alt={`비문 사진 ${index + 1}`}
                      style={{
                        width: 72,
                        height: 72,
                        objectFit: "cover",
                        borderRadius: 6,
                      }}
                    />
                  ))}
                </div>
              </div>
            )}
          </label>

          {enrollResult?.status === "success" && (
            <div
              style={{
                marginTop: 12,
                padding: 12,
                borderRadius: 8,
                border: "1px solid #16a34a",
                background: "#f0fdf4",
                color: "#14532d",
                fontSize: 14,
              }}
            >
              <b>비문 등록 완료</b>
              <div style={{ marginTop: 6, lineHeight: 1.7 }}>
                개체번호 {enrollData?.national_id ?? "-"}
                <br />
                내부 ID {enrollData?.cattle_id ?? "-"}
                <br />
                사용한 사진 {enrollData?.images_used ?? muzzleFiles.length}장
                <br />
                사진 일치도{" "}
                {consistency === null
                  ? "측정값 없음"
                  : `${consistency.toFixed(4)} (기준 ${MUZZLE_CONSISTENCY_THRESHOLD} 이상)`}
              </div>

              {muzzlePreviews.length > 0 && (
                <div
                  style={{
                    display: "flex",
                    gap: 6,
                    marginTop: 8,
                    flexWrap: "wrap",
                  }}
                >
                  {muzzlePreviews.map((url, index) => (
                    <img
                      key={`enrolled-${url}`}
                      src={url}
                      alt={`등록된 비문 사진 ${index + 1}`}
                      style={{
                        width: 56,
                        height: 56,
                        objectFit: "cover",
                        borderRadius: 6,
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {(enrollResult?.status === "inconsistent" ||
            enrollResult?.status === "error") && (
            <div
              style={{
                marginTop: 12,
                padding: 12,
                borderRadius: 8,
                border: "1px solid #dc2626",
                background: "#fef2f2",
                color: "#7f1d1d",
                fontSize: 14,
                lineHeight: 1.7,
              }}
            >
              <b>
                {enrollResult.status === "inconsistent"
                  ? "사진이 서로 다른 개체로 판정됐습니다"
                  : "비문 등록에 실패했습니다"}
              </b>
              <div style={{ marginTop: 6 }}>{enrollResult.message}</div>
            </div>
          )}

          {errorMessage && <p className="error-message">{errorMessage}</p>}

          <button
            className="register-submit-button"
            type="submit"
            disabled={isSubmitting || ocrStatus === "loading"}
          >
            {isSubmitting ? "등록 중..." : "등록하기"}
          </button>
        </form>
      </section>
    </div>
  );
}

function DashboardPage({ user, setUser }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    setIsProfileMenuOpen(false);
  }, [location.pathname]);

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const handleLogout = async () => {
    if (user.loginType === "google") {
      try {
        if (typeof window.COWOW_ANDROID?.googleLogout === "function") {
          window.COWOW_ANDROID.googleLogout();
        } else {
          googleLogout();
        }
      } catch (error) {
        console.error("Google logout error:", error);
      }
    }

    try {
      await logoutSession();
    } catch (error) {
      console.error("Logout error:", error);
    } finally {
      setUser(null);
      navigate("/login", { replace: true });
    }
  };

  return (
    <main className="dashboard-page">
      <header className="dashboard-header app-header">
        <button
          className="header-logo-button"
          type="button"
          onClick={() => navigate("/dashboard")}
          aria-label="대시보드로 이동"
        >
          <img
            className="dashboard-cowow-logo"
            src="/cowow-logo.png?v=20260811-1"
            alt="COWOW"
          />
        </button>

        <div className="header-actions header-actions-right">
          <div className="profile-menu-wrapper">
            <button
              className="header-user profile-menu-button"
              type="button"
              onClick={() => {
                setIsProfileMenuOpen((previous) => !previous);
              }}
              aria-expanded={isProfileMenuOpen}
            >
              {user.picture ? (
                <img
                  className="header-profile-image"
                  src={user.picture}
                  alt="사용자 프로필"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="header-guest-profile">G</div>
              )}

              <div className="header-user-info">
                <strong>{user.name}</strong>
                <span>{user.email}</span>
              </div>

              <span className="profile-menu-arrow">
                {isProfileMenuOpen ? "▲" : "▼"}
              </span>
            </button>

            {isProfileMenuOpen && (
              <div className="profile-dropdown">
                <button type="button" onClick={handleLogout}>
                  로그아웃
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {location.pathname === "/dashboard" && <AbnormalCattleDashboard />}
      {location.pathname === "/inference" && (
        <div
          style={{
            background: "#fff",
            borderRadius: "16px",
            padding: "20px",
            margin: "16px auto",
            width: "min(1120px, calc(100% - 48px))",
            boxSizing: "border-box",
            boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
          }}
        >
          <div style={{ fontSize: "1.35rem", fontWeight: 700, marginBottom: "16px" }}>급이대 구역 지정하기</div>
          <iframe
            src="/zone-setup.html"
            title="급이대 구역 지정"
            scrolling="no"
            onLoad={(ev) => {
              const fit = () => {
                try {
                  const d = ev.target.contentWindow.document;
                  ev.target.style.height = d.documentElement.scrollHeight + "px";
                } catch (err) {}
              };
              fit();
              setInterval(fit, 500);
            }}
            style={{ width: "100%", height: "600px", border: "none", borderRadius: "12px", display: "block", overflow: "hidden" }}
          />
        </div>
      )}
      {location.pathname === "/cattle/register" && (
        <RegisterCattleModal
            embedded
            onClose={() => navigate("/dashboard")}
            onRegistered={() => {
              window.alert("소 등록이 완료되었습니다.");
              navigate("/dashboard");
            }}
          />
      )}

      {location.pathname === "/chat" && <RagChatbot />}

      {location.pathname === "/control" && <BarnEnvironmentControl />}

      {location.pathname === "/devices/setup" && <DeviceSetupPage user={user} />}

      <BottomNavigation />
    </main>
  );
}

function App() {
  const navigate = useNavigate();
  const [user, setUser] = useState(undefined);

  useEffect(() => {
    localStorage.removeItem("loginUser");

    const controller = new AbortController();

    getCurrentUser({ signal: controller.signal })
      .then((authenticatedUser) => {
        setUser(authenticatedUser);

        const params = new URLSearchParams(window.location.search);
        if (authenticatedUser && params.get("auth") === "success") {
          window.history.replaceState({}, document.title, "/dashboard");
          navigate("/dashboard", { replace: true });
        }
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          console.error("Session restore error:", error);
          setUser(null);
        }
      });

    return () => controller.abort();
  }, [navigate]);

  if (user === undefined) {
    return (
      <main className="page auth-loading-page">
        <p>로그인 상태를 확인하고 있습니다.</p>
      </main>
    );
  }

  return (
    <Routes>
      <Route
        path="/"
        element={<Navigate to={user ? "/dashboard" : "/login"} replace />}
      />

      <Route
        path="/login"
        element={<LoginPage user={user} setUser={setUser} />}
      />

      <Route
        path="/dashboard"
        element={<DashboardPage user={user} setUser={setUser} />}
      />

      <Route
        path="/inference"
        element={<DashboardPage user={user} setUser={setUser} />}
      />

      <Route
        path="/cattle/register"
        element={<DashboardPage user={user} setUser={setUser} />}
      />

      <Route
        path="/chat"
        element={<DashboardPage user={user} setUser={setUser} />}
      />

      <Route
        path="/control"
        element={<DashboardPage user={user} setUser={setUser} />}
      />

      <Route
        path="/devices/setup"
        element={<DashboardPage user={user} setUser={setUser} />}
      />

      <Route
        path="*"
        element={<Navigate to={user ? "/dashboard" : "/login"} replace />}
      />
    </Routes>
  );
}

export default App;
