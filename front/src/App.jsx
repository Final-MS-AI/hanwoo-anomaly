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
      const response = await fetch("http://20.123.45.67:8000/db-test");
      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || "DB 조회 실패");
      }

      setRows(result.data || []);
      setMessage(`${result.count ?? 0}개의 데이터를 불러왔습니다.`);
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
        <h1>한우 모니터링 DB 테스트</h1>

        <p className="description">
          버튼을 누르면 DB 데이터를 화면에 표시합니다.
        </p>

        <button onClick={loadDatabase} disabled={loading}>
          {loading ? "조회 중..." : "DB 연결 및 조회"}
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
