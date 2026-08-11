import { useEffect, useState } from "react";

const MUZZLE_API = "https://hanwoo.koreacentral.cloudapp.azure.com/muzzle";

export default function MuzzleVideoPanel() {
  const [videos, setVideos] = useState([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${MUZZLE_API}/videos`)
      .then((r) => r.json())
      .then((d) => {
        setVideos(d.videos || []);
        if (d.videos?.length) setSelected(d.videos[0]);
      })
      .catch(() => setError("영상 목록을 불러오지 못했습니다."));
  }, []);

  const run = async () => {
    if (!selected) return;
    setLoading(true); setResult(null); setError("");
    try {
      const stem = selected.replace(/\.mp4$/, "");
      const r = await fetch(`${MUZZLE_API}/videos/${stem}/identify`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setResult(await r.json());
    } catch (e) {
      setError(`분석에 실패했습니다 (${e.message})`);
    } finally {
      setLoading(false);
    }
  };

  const confirmed = result?.decision === "confirmed";
  const nConfirmed = result?.frames?.filter((f) => f.confirmed).length ?? 0;

  const S = {
    wrap: { padding: 16, maxWidth: 720, margin: "0 auto" },
    box: { border: "1px dashed #c9b8a8", borderRadius: 12, padding: 16, marginBottom: 16 },
    h: { fontWeight: 700, fontSize: 16, marginBottom: 6 },
    sub: { fontSize: 13, color: "#7a6a5c", lineHeight: 1.5, marginBottom: 12 },
    sel: { width: "100%", padding: 10, borderRadius: 8, border: "1px solid #d8cec4", fontSize: 15 },
    btn: {
      width: "100%", padding: 14, marginTop: 12, borderRadius: 10, border: "none",
      background: loading ? "#9aa89a" : "#2f6b3d", color: "#fff", fontSize: 16,
      fontWeight: 700, cursor: loading ? "default" : "pointer",
    },
    card: (ok) => ({
      border: `1px solid ${ok ? "#7fb98a" : "#d9c48a"}`,
      background: ok ? "#f2f9f3" : "#fdf8ec",
      borderRadius: 12, padding: 16, marginBottom: 16,
    }),
    err: { border: "1px solid #e0a0a0", background: "#fdf2f2", borderRadius: 12, padding: 16, color: "#a33" },
    table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
    th: { textAlign: "left", padding: "6px 4px", borderBottom: "1px solid #e5ded6", color: "#7a6a5c", fontWeight: 600 },
    td: { padding: "6px 4px", borderBottom: "1px solid #f0ebe5" },
    why: { marginTop: 12, paddingTop: 12, borderTop: "1px dashed #cfc4b8", fontSize: 13, color: "#5c5147", lineHeight: 1.7 },
  };

  return (
    <div style={S.wrap}>
      <div style={S.box}>
        <div style={S.h}>초크포인트 영상 분석</div>
        <div style={S.sub}>
          급이대·음수대 영상에서 비문으로 개체를 확정합니다. 여러 프레임의 판정을
          유사도 가중 투표로 종합하며, 확신이 부족하면 ID를 부여하지 않습니다.
        </div>
        <select style={S.sel} value={selected} onChange={(e) => setSelected(e.target.value)}>
          {videos.length === 0 && <option>영상 없음</option>}
          {videos.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <button style={S.btn} onClick={run} disabled={loading || !selected}>
          {loading ? "분석 중… (10~30초)" : "분석 시작"}
        </button>
      </div>

      {error && <div style={S.err}>{error}</div>}

      {result && (
        <>
          <div style={S.card(confirmed)}>
            {confirmed ? (
              <>
                <div style={{ fontWeight: 700, marginBottom: 8 }}>✅ 개체 확정</div>
                <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: 1 }}>
                  {result.national_id}
                </div>
                <div style={{ fontSize: 13, color: "#4a6b50", marginTop: 6 }}>
                  분석 프레임 {result.frames.length}장 중 {nConfirmed}장이 임계값{" "}
                  {result.threshold}를 넘었습니다.
                </div>
              </>
            ) : (
              <>
                <div style={{ fontWeight: 700, marginBottom: 8 }}>⏸ 미확정 — ID를 부여하지 않았습니다</div>
                <div style={{ fontSize: 13, color: "#6b5c3f" }}>
                  분석 프레임 {result.frames.length}장 모두 임계값 {result.threshold}에
                  도달하지 못했습니다.
                </div>
              </>
            )}

            <div style={S.why}>
              <b>▸ 왜 이렇게 판단했나</b>
              <br />
              {confirmed
                ? "등록된 코무늬 특징과의 유사도가 임계값을 넘은 프레임들이 같은 개체를 가리켜 동일 개체로 확정했습니다."
                : "유사도가 임계값에 못 미쳐 ID를 부여하지 않았습니다. 잘못 붙이면 두 개체의 건강 이력이 함께 오염되므로, 확신이 없을 때는 보류합니다. 소는 급이대·음수대를 하루에 여러 번 방문하므로 다음 방문에서 다시 확인합니다."}
            </div>
          </div>

          <div style={{ ...S.box, borderStyle: "solid" }}>
            <div style={S.h}>프레임별 판정</div>
            <table style={S.table}>
              <thead>
                <tr>
                  <th style={S.th}>프레임</th>
                  <th style={S.th}>추적</th>
                  <th style={S.th}>1위 후보</th>
                  <th style={S.th}>유사도</th>
                  <th style={S.th}>판정</th>
                </tr>
              </thead>
              <tbody>
                {result.frames.map((f) => (
                  <tr key={f.frame}>
                    <td style={S.td}>{f.frame}</td>
                    <td style={S.td}>{f.match}</td>
                    <td style={S.td}>{f.top1 ?? "—"}</td>
                    <td style={S.td}>{f.similarity?.toFixed(4)}</td>
                    <td style={{ ...S.td, color: f.confirmed ? "#2f6b3d" : "#8a7a4f" }}>
                      {f.confirmed ? "확정" : "보류"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ fontSize: 12, color: "#8a7a6c", marginTop: 10, lineHeight: 1.6 }}>
              1위 후보는 참고 정보입니다. 임계값 미달 프레임은 후보가 있어도 ID를
              부여하지 않습니다.
            </div>
          </div>
        </>
      )}
    </div>
  );
}