import { useCallback, useEffect, useState } from "react";
import { GoogleLogin, googleLogout } from "@react-oauth/google";
import { jwtDecode } from "jwt-decode";
import {
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";

const API_BASE_URL = "http://20.194.30.236:8000";

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
      console.error("Google 로그인 처리 오류:", error);
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
          Google 계정으로 로그인하거나 게스트로 체험해 보세요.
        </p>

        <div className="google-login">
          <GoogleLogin
            onSuccess={handleGoogleLogin}
            onError={() => {
              setErrorMessage("Google 로그인에 실패했습니다.");
            }}
          />
        </div>

        <div className="login-divider">
          <span>또는</span>
        </div>

        <button
          className="guest-login-button"
          type="button"
          onClick={handleGuestLogin}
        >
          게스트로 체험하기
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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setErrorMessage("");

    if (!earTagImage) {
      setErrorMessage("귀표 사진을 선택해 주세요.");
      return;
    }

    if (!muzzleImage) {
      setErrorMessage("비문 사진을 선택해 주세요.");
      return;
    }

    setIsSubmitting(true);

    try {
      const formData = new FormData();

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
      console.error("소 등록 오류:", error);
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
              onChange={(event) => {
                setEarTagImage(event.target.files?.[0] ?? null);
              }}
              required
            />

            {earTagImage && (
              <span className="selected-file">
                선택됨: {earTagImage.name}
              </span>
            )}
          </label>

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
            disabled={isSubmitting}
          >
            {isSubmitting ? "사진 분석 및 등록 중..." : "등록하기"}
          </button>
        </form>
      </section>
    </div>
  );
}

function AnomalyDashboard() {
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
      console.error("이상 개체 조회 오류:", error);
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
          <p className="dashboard-subtitle">
            한우 모니터링 시스템
          </p>
          <h1>대시보드</h1>
        </div>

        <div className="header-actions">
          <button
            className="register-cattle-button"
            type="button"
            onClick={() => setIsRegisterOpen(true)}
          >
            + 소 등록하기
          </button>

          <button
            className="logout-button header-logout"
            type="button"
            onClick={handleLogout}
          >
            로그아웃
          </button>
        </div>
      </header>

      <section className="user-card">
        {user.picture ? (
          <img
            className="profile-image"
            src={user.picture}
            alt="사용자 프로필"
            referrerPolicy="no-referrer"
          />
        ) : (
          <div className="guest-profile">G</div>
        )}

        <div>
          <h2>{user.name}</h2>
          <p>{user.email}</p>

          {user.loginType === "guest" && (
            <span className="guest-badge">게스트 모드</span>
          )}
        </div>
      </section>

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
  const [user, setUser] = useState(null);

  return (
    <Routes>
      <Route
        path="/login"
        element={<LoginPage user={user} setUser={setUser} />}
      />

      <Route
        path="/dashboard"
        element={
          <DashboardPage user={user} setUser={setUser} />
        }
      />

      <Route
        path="*"
        element={<Navigate to="/login" replace />}
      />
    </Routes>
  );
}

export default App;