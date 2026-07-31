import { useCallback, useEffect, useState } from "react";
import { GoogleLogin, googleLogout } from "@react-oauth/google";
import { jwtDecode } from "jwt-decode";
import DemoVideoSelector from "./DemoVideoSelector.jsx";
import "./kakao-login.css";
import {
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ||
  "https://hanwoo.koreacentral.cloudapp.azure.com";

function LoginPage({ user, setUser }) {
  const navigate = useNavigate();
  const [errorMessage, setErrorMessage] = useState("");

  const handleGoogleLogin = (credentialResponse) => {
    try {
      const credential = credentialResponse?.credential;

      if (!credential) {
        setErrorMessage("Google 인증 정보를 받지 못했습니다.");
        return;
      }

      const decoded = jwtDecode(credential);

      setUser({
        loginType: "google",
        name: decoded.name ?? "이름 없음",
        email: decoded.email ?? "이메일 없음",
        picture: decoded.picture ?? null,
      });

      setErrorMessage("");
      navigate("/dashboard");
    } catch (error) {
      console.error("Login processing error:", error);
      setErrorMessage("로그인 정보를 처리하지 못했습니다.");
    }
  };

  const handleGuestLogin = () => {
    setUser({
      loginType: "guest",
      name: "게스트 사용자",
      email: "guest@cow-monitoring.local",
      picture: null,
    });

    setErrorMessage("");
    navigate("/dashboard");
  };

  if (user) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <main className="page">
      <section className="login-card">
        <div className="cow-icon">🐂</div>

        <h1>한우 행동 이상 탐지</h1>

        <p className="description">
          Google, 카카오 또는 네이버 계정으로 로그인해 주세요.
        </p>

        <div className="social-login-buttons">
          <div className="google-login-wrapper">
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
          </div>

          <button
            className="kakao-login-image-button"
            type="button"
            onClick={() => {
              window.location.assign(
                `${API_BASE_URL}/auth/kakao/login`,
              );
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
              window.location.assign(
                `${API_BASE_URL}/auth/naver/login`,
              );
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
        >
          게스트로 로그인
        </button>

        {errorMessage && (
          <p className="error-message">{errorMessage}</p>
        )}
      </section>
    </main>
  );
}

function RegisterCattleModal({ onClose, onRegistered }) {
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
    <div className="modal-backdrop">
      <section className="modal-card">
        <div className="modal-header">
          <h2>소 등록하기</h2>

          <button
            className="modal-close-button"
            type="button"
            onClick={onClose}
            aria-label="등록창 닫기"
          >
            ×
          </button>
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
              코 무늬가 정면으로 선명하게 보이는 사진을 등록해 주세요.
            </span>

            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
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
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
  const [demoInferenceResult, setDemoInferenceResult] = useState(null);

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const handleLogout = () => {
    if (user.loginType === "google") {
      googleLogout();
    }

    setUser(null);
    navigate("/login");
  };

  return (
    <main className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <p className="dashboard-subtitle dashboard-title">
            한우 모니터링 시스템
          </p>
        </div>

                <div className="header-actions header-actions-right">
          <button
            className="register-cattle-button"
            type="button"
            onClick={() => setIsRegisterOpen(true)}
          >
            + 소 등록하기
          </button>

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
<DemoVideoSelector />
<AnomalyDashboard />

      {isRegisterOpen && (
        <RegisterCattleModal
          onClose={() => setIsRegisterOpen(false)}
          onRegistered={() => {
            window.alert("소 등록이 완료되었습니다.");
          }}
        />
      )}
    </main>
  );
}

function App() {
  const navigate = useNavigate();

  const [user, setUser] = useState(() => {
    const savedUser =
      localStorage.getItem("loginUser");

    if (!savedUser) {
      return null;
    }

    try {
      return JSON.parse(savedUser);
    } catch (error) {
      console.error("Login processing error:", error);

      localStorage.removeItem("loginUser");
      return null;
    }
  });

  useEffect(() => {
    const params = new URLSearchParams(
      window.location.search,
    );

    const providerConfigs = [
      {
        queryKey: "kakao_user",
        loginType: "kakao",
        defaultName: "카카오 사용자",
      },
      {
        queryKey: "naver_user",
        loginType: "naver",
        defaultName: "네이버 사용자",
      },
    ];

    const matchedProvider = providerConfigs.find(
      ({ queryKey }) => params.has(queryKey),
    );

    if (!matchedProvider) {
      return;
    }

    const userValue = params.get(
      matchedProvider.queryKey,
    );

    if (!userValue) {
      return;
    }

    try {
      const socialUser = JSON.parse(userValue);

      const normalizedUser = {
        loginType: matchedProvider.loginType,
        providerUserId:
          socialUser.providerUserId ?? null,
        name:
          socialUser.name ||
          matchedProvider.defaultName,
        email:
          socialUser.email ||
          "이메일 정보 없음",
        picture:
          socialUser.profileImageUrl || null,
      };

      localStorage.setItem(
        "loginUser",
        JSON.stringify(normalizedUser),
      );

      setUser(normalizedUser);

      window.history.replaceState(
        {},
        document.title,
        "/dashboard",
      );

      navigate("/dashboard", {
        replace: true,
      });
    } catch (error) {
      console.error(
        "Social login processing error:",
        error,
      );

      localStorage.removeItem("loginUser");

      window.history.replaceState(
        {},
        document.title,
        "/login",
      );

      navigate("/login", {
        replace: true,
      });
    }
  }, [navigate]);

  useEffect(() => {
    if (user) {
      localStorage.setItem(
        "loginUser",
        JSON.stringify(user),
      );

      return;
    }

    localStorage.removeItem("loginUser");
  }, [user]);

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

