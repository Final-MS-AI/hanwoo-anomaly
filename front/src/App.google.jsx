import { useState } from "react";
import { GoogleLogin, googleLogout } from "@react-oauth/google";
import { jwtDecode } from "jwt-decode";

function App() {
  const [user, setUser] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");

  const handleLoginSuccess = (credentialResponse) => {
    try {
      const credential = credentialResponse.credential;

      if (!credential) {
        throw new Error("Google 인증 토큰을 받지 못했습니다.");
      }

      const decoded = jwtDecode(credential);

      setUser({
        googleId: decoded.sub,
        name: decoded.name,
        email: decoded.email,
        picture: decoded.picture,
      });

      setErrorMessage("");
    } catch (error) {
      console.error(error);
      setErrorMessage("로그인 정보를 처리하지 못했습니다.");
    }
  };

  const handleLogout = () => {
    googleLogout();
    setUser(null);
    setErrorMessage("");
  };

  if (user) {
    return (
      <main className="page">
        <section className="login-card">
          <h1>로그인 성공</h1>

          {user.picture && (
            <img
              className="profile-image"
              src={user.picture}
              alt="Google 프로필"
              width="88"
              height="88"
            />
          )}

          <p>
            <strong>이름:</strong> {user.name}
          </p>

          <p>
            <strong>이메일:</strong> {user.email}
          </p>

          <button
            className="logout-button"
            type="button"
            onClick={handleLogout}
          >
            로그아웃
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="page">
      <section className="login-card">
        <div className="cow-icon">🐂</div>

        <h1>한우 행동 이상 탐지</h1>

        <p className="description">
          서비스 이용을 위해 Google 계정으로 로그인해 주세요.
        </p>

        <div className="google-login">
          <GoogleLogin
            onSuccess={handleLoginSuccess}
            onError={() => {
              setErrorMessage("Google 로그인에 실패했습니다.");
            }}
            text="signin_with"
            shape="rectangular"
            size="large"
          />
        </div>

        {errorMessage && (
          <p className="error-message">{errorMessage}</p>
        )}
      </section>
    </main>
  );
}

export default App;
