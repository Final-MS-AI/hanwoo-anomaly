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


const MUZZLE_API = "https://hanwoo.koreacentral.cloudapp.azure.com";
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

function LoginPage({ user, setUser }) {
  const navigate = useNavigate();
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const isAndroidApp = hasAndroidAuthBridge();

  const completeGoogleLogin = useCallback(async (credential) => {
    try {
      if (!credential) {
        setErrorMessage("Google 인증 정보를 받지 못했습니다.");
        return;
      }

      setErrorMessage("");
      setIsLoggingIn(true);

      const authenticatedUser =
        await exchangeGoogleCredential(credential);

      setUser(authenticatedUser);

      setErrorMessage("");
      navigate("/dashboard");
    } catch (error) {
      console.error("Google login error:", error);

      setErrorMessage(
        error.message ??
          "Google 로그인 정보를 처리하지 못했습니다.",
      );
    } finally {
      setIsLoggingIn(false);
    }
  }, [navigate, setUser]);

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
        event.detail?.message ??
          "Google 로그인에 실패했습니다.",
      );
    };

    window.addEventListener(
      "cowow:google-login",
      handleNativeSuccess,
    );
    window.addEventListener(
      "cowow:google-login-error",
      handleNativeError,
    );

    return () => {
      window.removeEventListener(
        "cowow:google-login",
        handleNativeSuccess,
      );
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
      setErrorMessage(
        error.message ?? "게스트 로그인에 실패했습니다.",
      );
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
            src="/cowow-logo.png"
            alt="COWOW"
          />

          <img
            className="login-bull-image"
            src="/cowow-bull.png"
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
                <span className="native-google-logo">G</span>
                <span>{isLoggingIn ? "로그인 중" : "로그인"}</span>
              </button>
            ) : GOOGLE_CLIENT_ID ? (
              <GoogleLogin
                onSuccess={handleGoogleLogin}
                onError={() => {
                  setErrorMessage(
                    "Google 로그인에 실패했습니다.",
                  );
                }}
                text="signin"
                locale="ko"
                size="medium"
                width="100"
              />
            ) : (
              <button
                className="native-google-login-button"
                type="button"
                disabled
                title="VITE_GOOGLE_CLIENT_ID 설정이 필요합니다."
              >
                <span className="native-google-logo">G</span>
                <span>로그인</span>
              </button>
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
            <img
              src="/kakao-login.png"
              alt="카카오 로그인"
            />
          </button>

          <button
            className="social-provider-button naver-login-button"
            type="button"
            onClick={() => {
              startSocialLogin("naver");
            }}
            aria-label="네이버 로그인"
          >
            <span className="social-provider-logo naver-logo">
              N
            </span>
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

        {errorMessage && (
          <p className="error-message">{errorMessage}</p>
        )}
      </section>
    </main>
  );
}

function RegisterCattleModal({
  onClose,
  onRegistered,
  embedded = false,
}) {
  const [earTagImage, setEarTagImage] = useState(null);
  const [muzzleImage, setMuzzleImage] = useState(null);
  const [earTagNumber, setEarTagNumber] = useState("");
  const [ocrStatus, setOcrStatus] = useState("idle");
  const [ocrMessage, setOcrMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const handleEarTagImageChange = async (event) => {
    const file = event.target.files?.[0] ?? null;

    setEarTagImage(file);
    setEarTagNumber("");
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
        throw new Error(
          result.detail ?? "귀표 번호 인식에 실패했습니다.",
        );
      }

      setEarTagNumber(result.ear_tag_number ?? "");
      setOcrStatus("success");
      setOcrMessage(
        "사진에서 인식한 값입니다. 틀린 경우 직접 수정해 주세요.",
      );
    } catch (error) {
      console.error("Login processing error:", error);
      setOcrStatus("error");
      setOcrMessage(
        "자동 인식에 실패했습니다. 귀표 번호를 직접 입력해 주세요.",
      );
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setErrorMessage("");

    const normalizedEarTagNumber = earTagNumber.trim();

    if (!earTagImage) {
      setErrorMessage("귀표 사진을 선택해 주세요.");
      return;
    }

    if (!normalizedEarTagNumber) {
      setErrorMessage("귀표 번호를 확인하거나 직접 입력해 주세요.");
      return;
    }

    if (!muzzleImage) {
      setErrorMessage("비문 사진을 선택해 주세요.");
      return;
    }

    setIsSubmitting(true);

    try {
      const formData = new FormData();

      formData.append(
        "ear_tag_number",
        normalizedEarTagNumber,
      );
      formData.append("ear_tag_image", earTagImage);
      formData.append("muzzle_image", muzzleImage);

      // ── 비문 임베딩 등록 (개체 식별 파트) ──
      let muzzleOk = false;
      const muzzleInput = event.target.elements.muzzle_files;
      const muzzleFiles = muzzleInput ? Array.from(muzzleInput.files) : [];
      const nationalId = normalizedEarTagNumber
        .replace(/\D/g, "")
        .slice(-12)
        .padStart(12, "0");

      if (muzzleFiles.length > 0) {
        try {
          const muzzleForm = new FormData();
          muzzleForm.append("national_id", nationalId);
          muzzleForm.append("barn_id", "");
          muzzleFiles.forEach((f) => muzzleForm.append("files", f));

          const muzzleRes = await fetch(`${MUZZLE_API}/muzzle/enroll`, {
            method: "POST",
            body: muzzleForm,
          });

          if (muzzleRes.ok) {
            muzzleOk = true;
            console.log("[비문] 등록 완료:", await muzzleRes.json());
          } else {
            console.error("[비문] 등록 실패", muzzleRes.status, await muzzleRes.text());
          }
        } catch (err) {
          console.error("[비문] 등록 오류:", err);
        }
      } else {
        console.warn("[비문] 사진이 선택되지 않아 건너뜀");
      }

      const response = await fetch(`${API_BASE_URL}/cattle`, {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail ?? "소 등록에 실패했습니다.");
      }

      onRegistered(result);
      onClose();
    } catch (error) {
      console.error("Login processing error:", error);
      setErrorMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className={
        embedded
          ? "register-page-container"
          : "modal-backdrop"
      }
    >
      <section
        className={
          embedded
            ? "register-page-card"
            : "modal-card"
        }
      >
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
              <span className="selected-file">
                선택됨: {earTagImage.name}
              </span>
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
                  <span className="ocr-status-badge loading">
                    분석 중
                  </span>
                )}

                {ocrStatus === "success" && (
                  <span className="ocr-status-badge success">
                    자동 인식
                  </span>
                )}

                {ocrStatus === "error" && (
                  <span className="ocr-status-badge error">
                    직접 입력
                  </span>
                )}
              </div>

              {ocrMessage && (
                <span
                  className={`ocr-message ${ocrStatus}`}
                >
                  {ocrMessage}
                </span>
              )}
            </label>
          )}

          <label className="image-upload-field">
            비문 사진

            <span className="upload-description">
              코가 화면에 가득 차도록 30cm 거리에서 정면 촬영해 주세요. 얼굴이나 전신이 나오면 인식되지 않습니다. 각도를 바꿔 3장 이상 선택해 주세요.
            </span>

            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              name="muzzle_files"
              multiple
              onChange={(event) => {
                setMuzzleImage(event.target.files?.[0] ?? null);
              }}
              required
            />

            {muzzleImage && (
              <span className="selected-file">
                선택됨: {muzzleImage.name}
              </span>
            )}
          </label>

          {errorMessage && (
            <p className="error-message">{errorMessage}</p>
          )}

          <button
            className="register-submit-button"
            type="submit"
            disabled={
              isSubmitting || ocrStatus === "loading"
            }
          >
            {isSubmitting ? "등록 중..." : "등록하기"}
          </button>
        </form>
      </section>
    </div>
  );
}

function AnomalyDashboard({ demoResult }) {
  const [anomalies, setAnomalies] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const loadAnomalies = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage("");

    try {
      const response = await fetch(
        `${API_BASE_URL}/anomalies/active`,
      );

      const result = await response.json();

      if (!response.ok) {
        throw new Error(
          result.detail ?? "이상 개체 조회에 실패했습니다.",
        );
      }

      setAnomalies(result.data ?? []);
    } catch (error) {
      console.error("Login processing error:", error);
      setErrorMessage(error.message);
      setAnomalies([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAnomalies();
  }, [loadAnomalies]);

  return (
    <section className="anomaly-section">
      <div className="anomaly-section-header">
        <div>
          <p className="section-label">실시간 위험 현황</p>
          <h2>이상 개체 대시보드</h2>
        </div>

        <button
          className="refresh-button"
          type="button"
          onClick={loadAnomalies}
          disabled={isLoading}
        >
          {isLoading ? "조회 중..." : "새로고침"}
        </button>
      </div>

      {isLoading && (
        <div className="dashboard-empty">
          이상 개체 정보를 불러오는 중입니다.
        </div>
      )}

      {!isLoading && errorMessage && (
        <div className="dashboard-error">
          <strong>DB 조회에 실패했습니다.</strong>
          <p>{errorMessage}</p>
        </div>
      )}

      {!isLoading &&
        !errorMessage &&
        anomalies.length === 0 && (
          <div className="dashboard-empty">
            <span className="normal-icon">✓</span>
            <strong>현재 이상이 감지된 소가 없습니다.</strong>
            <p>모든 개체가 정상 상태입니다.</p>
          </div>
        )}

      {!isLoading && anomalies.length > 0 && (
        <div className="anomaly-list">
          {anomalies.map((item) => (
            <article
              className="anomaly-card"
              key={item.anomaly_id}
            >
              <div className="anomaly-card-top">
                <div>
                  <span className="danger-badge">이상 감지</span>

                  <h3>
                    {item.ear_tag_number ??
                      `개체 ${item.cattle_id}`}
                  </h3>
                </div>

                <span className="anomaly-time">
                  {item.detected_at
                    ? new Date(
                        item.detected_at,
                      ).toLocaleString("ko-KR")
                    : "시간 정보 없음"}
                </span>
              </div>

              <dl className="anomaly-details">
                <div>
                  <dt>귀표 번호</dt>
                  <dd>{item.ear_tag_number ?? "-"}</dd>
                </div>

                <div>
                  <dt>이상 행동</dt>
                  <dd>{item.anomaly_type ?? "-"}</dd>
                </div>

                <div>
                  <dt>위험도</dt>
                  <dd>{item.severity ?? "-"}</dd>
                </div>

                <div>
                  <dt>상태</dt>
                  <dd>{item.status ?? "active"}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
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
        if (
          typeof window.COWOW_ANDROID?.googleLogout ===
          "function"
        ) {
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
            src="/cowow-logo.png"
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
                <button
                  type="button"
                  onClick={handleLogout}
                >
                  로그아웃
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
{location.pathname === "/dashboard" && (
        <AbnormalCattleDashboard />
      )}

      {location.pathname === "/inference" && (
        <DemoVideoSelector />
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

      {location.pathname === "/control" && (
        <BarnEnvironmentControl />
      )}

      {location.pathname === "/devices/setup" && (
        <DeviceSetupPage />
      )}

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
        element={
          <Navigate
            to={user ? "/dashboard" : "/login"}
            replace
          />
        }
      />

      <Route
        path="/login"
        element={
          <LoginPage
            user={user}
            setUser={setUser}
          />
        }
      />

      <Route
        path="/dashboard"
        element={
          <DashboardPage
            user={user}
            setUser={setUser}
          />
        }
      />


      <Route
        path="/inference"
        element={
          <DashboardPage
            user={user}
            setUser={setUser}
          />
        }
      />

      <Route
        path="/cattle/register"
        element={
          <DashboardPage
            user={user}
            setUser={setUser}
          />
        }
      />
      <Route
        path="/chat"
        element={
          <DashboardPage
            user={user}
            setUser={setUser}
          />
        }
      />
      <Route
        path="/control"
        element={
          <DashboardPage
            user={user}
            setUser={setUser}
          />
        }
      />
      <Route
        path="/devices/setup"
        element={
          <DashboardPage
            user={user}
            setUser={setUser}
          />
        }
      />
      <Route
        path="*"
        element={
          <Navigate
            to={user ? "/dashboard" : "/login"}
            replace
          />
        }
      />
    </Routes>
  );
}

export default App;


























