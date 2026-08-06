import { useEffect, useState } from "react";

const API_BASE_URL =
  import.meta.env.VITE_DEVICE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "";

function DeviceSharingPanel({ device }) {
  const [isOpen, setIsOpen] = useState(false);
  const [sharing, setSharing] = useState(null);
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [pendingUserId, setPendingUserId] = useState(null);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState("success");

  const loadSharing = async () => {
    if (!device?.deviceId) return;

    setIsLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/devices/sharing`, {
        credentials: "include",
      });
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.includes("application/json")) {
        throw new Error("공유 API가 서버에 연결되지 않았습니다. 서버 설정을 확인해 주세요.");
      }
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "공유 정보를 불러오지 못했습니다.");
      }

      setSharing(data);
    } catch (error) {
      setSharing(null);
      setMessageType("error");
      setMessage(error.message);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) loadSharing();
  }, [isOpen, device?.deviceId]);

  const sendShareCode = async (event) => {
    event.preventDefault();
    if (!email.trim()) return;

    setIsLoading(true);
    setMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/devices/share-code`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "공유 코드 발송에 실패했습니다.");
      }

      setMessageType("success");
      setMessage(data.message ?? "구성원 이메일로 공유 코드를 보냈습니다.");
      setEmail("");
    } catch (error) {
      setMessageType("error");
      setMessage(error.message);
    } finally {
      setIsLoading(false);
    }
  };

  const updateMember = async (member, action) => {
    const isTransfer = action === "transfer";
    const confirmed = window.confirm(
      isTransfer
        ? `${member.name || member.email}님을 관리자로 임명할까요?`
        : `${member.name || member.email}님의 장비 공유를 해제할까요?`,
    );
    if (!confirmed) return;

    setPendingUserId(member.userId);
    setMessage("");

    try {
      const response = await fetch(
        isTransfer
          ? `${API_BASE_URL}/devices/admin/transfer`
          : `${API_BASE_URL}/devices/members/${member.userId}`,
        {
          method: isTransfer ? "POST" : "DELETE",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: isTransfer
            ? JSON.stringify({ userId: member.userId })
            : undefined,
        },
      );
      const data = response.status === 204 ? {} : await response.json();

      if (!response.ok) {
        throw new Error(data.detail ?? "구성원 변경에 실패했습니다.");
      }

      setMessageType("success");
      setMessage(
        isTransfer
          ? "새 관리자를 임명했습니다. 이제 구성원 권한으로 이용합니다."
          : "구성원의 장비 공유를 해제했습니다.",
      );
      await loadSharing();
    } catch (error) {
      setMessageType("error");
      setMessage(error.message);
    } finally {
      setPendingUserId(null);
    }
  };

  if (!device || device.guest || device.role === "guest") return null;

  return (
    <section className={`device-sharing-panel ${isOpen ? "is-open" : ""}`}>
      <button
        className="device-sharing-toggle"
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((previous) => !previous)}
      >
        <span>
          <strong>가족과 장비 공유</strong>
          <small>이메일 인증으로 센서 확인과 제어 권한을 공유합니다.</small>
        </span>
        <b>{isOpen ? "접기 ▲" : "공유하기 ›"}</b>
      </button>

      {isOpen && (
        <div className="device-sharing-content">
          {isLoading && !sharing ? (
            <p className="device-sharing-loading">공유 정보를 불러오는 중...</p>
          ) : sharing ? (
            <>
              <div className="device-sharing-role">
                <span>현재 권한</span>
                <strong>{sharing?.role === "admin" ? "관리자" : "공유 구성원"}</strong>
              </div>

              {sharing?.role === "admin" && (
                <form className="device-share-email-form" onSubmit={sendShareCode}>
                  <label>
                    <span>초대할 구성원 이메일</span>
                    <input
                      type="email"
                      value={email}
                      placeholder="family@example.com"
                      autoComplete="email"
                      onChange={(event) => setEmail(event.target.value)}
                    />
                  </label>
                  <button type="submit" disabled={isLoading || !email.trim()}>
                    {isLoading ? "발송 중..." : "인증 코드 보내기"}
                  </button>
                </form>
              )}

              <div className="device-member-list">
                <div className="device-member-list-title">
                  <strong>연결된 구성원</strong>
                  <span>{sharing?.members?.length ?? 0}명</span>
                </div>

                {!sharing?.members?.length ? (
                  <p className="device-member-empty">아직 공유된 구성원이 없습니다.</p>
                ) : (
                  sharing.members.map((member) => (
                    <article className="device-member-item" key={member.userId}>
                      <div>
                        <strong>{member.name || "이름 없음"}</strong>
                        <span>{member.email}</span>
                        <small>{member.role === "admin" ? "관리자" : "구성원"}</small>
                      </div>
                      {sharing.role === "admin" && member.role !== "admin" && (
                        <div className="device-member-actions">
                          <button
                            type="button"
                            disabled={pendingUserId === member.userId}
                            onClick={() => updateMember(member, "transfer")}
                          >
                            관리자 임명
                          </button>
                          <button
                            className="remove"
                            type="button"
                            disabled={pendingUserId === member.userId}
                            onClick={() => updateMember(member, "remove")}
                          >
                            제거
                          </button>
                        </div>
                      )}
                    </article>
                  ))
                )}
              </div>
            </>
          ) : (
            <div className="device-sharing-unavailable">
              <strong>공유 정보를 불러오지 못했습니다.</strong>
              <button type="button" onClick={loadSharing}>다시 불러오기</button>
            </div>
          )}

          {message && (
            <p className={`device-sharing-message ${messageType}`} role="status">
              {message}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export default DeviceSharingPanel;
