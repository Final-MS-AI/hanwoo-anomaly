import { useState } from "react";
import "./App.css";

function App() {
  const [rows, setRows] = useState([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const loadDatabase = async () => {
    setLoading(true);
    setMessage("");

    try {
      const response = await fetch("/api/health");

      if (!response.ok) {
        throw new Error(`HTTP 오류: ${response.status}`);
      }

      const text = await response.text();

      if (!text) {
        throw new Error("서버 응답이 비어 있습니다.");
      }

      const result = JSON.parse(text);

      if (result.status === "healthy") {
        setRows([]);
        setMessage("FastAPI 서버 연결 성공");
      } else {
        throw new Error("서버 상태가 정상적이지 않습니다.");
      }
    } catch (error) {
      setRows([]);
      setMessage(`연결 실패: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="page">
      <section className="card">
        <h1>한우모니터링 서버 테스트</h1>

        <p className="description">
          버튼을 누르면 FastAPI 서버 연결 상태를 확인합니다.
        </p>

        <button
          type="button"
          onClick={loadDatabase}
          disabled={loading}
        >
          {loading ? "확인 중..." : "서버 연결 확인"}
        </button>

        {message && <p className="status">{message}</p>}

        {rows.length > 0 && (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>메시지</th>
                  <th>생성 시각</th>
                </tr>
              </thead>

              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.id}</td>
                    <td>{row.message}</td>
                    <td>
                      {row.created_at
                        ? new Date(row.created_at).toLocaleString("ko-KR")
                        : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

export default App;
EOF
