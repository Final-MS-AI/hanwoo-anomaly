import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./AdminPage.css";

const MUZZLE_API = "https://hanwoo.koreacentral.cloudapp.azure.com/muzzle";
const ADMIN_API = "https://hanwoo.koreacentral.cloudapp.azure.com";
const TRACK_CACHE_KEY = "cowow-admin-tracks";
const NOTIFICATION_CACHE_KEY = "cowow-admin-notifications";
const trackDetailCache = new Map();

function readSessionCache(key, fallback) {
  try {
    const value = window.sessionStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

const navItems = [
  ["overview", "▦", "개요"],
  ["feedback", "↗", "피드백"],
  ["loop", "⟳", "학습 루프"],
  ["members", "♙", "사용자 관리"],
];

function trackToFeedback(track) {
  const bound = Boolean(track.national_id);
  return {
    id: `SEG-${track.segment_id}`,
    segmentId: track.segment_id,
    type: bound ? "ID 역전파" : "미확정 트랙",
    subject: bound ? `segment #${track.segment_id} 바인딩 완료` : `segment #${track.segment_id} ID 미확정`,
    detail: bound ? `한우 ${track.national_id}에 과거 관측 ${track.frame_count ?? 0}건 소급 적용` : `카메라 ${track.camera_id} · 추적 ID ${track.track_id} · 비문 확인 필요`,
    user: track.camera_id ? `카메라 ${track.camera_id}` : "muzzle API",
    time: track.started_at ? new Date(track.started_at).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "시간 정보 없음",
    status: bound ? "승인됨" : "검토 대기",
    tone: bound ? "green" : "blue",
    nationalId: track.national_id,
    frameCount: track.frame_count ?? 0,
    similarity: track.similarity,
  };
}

function AdminPage() {
  const navigate = useNavigate();
  const [activeNav, setActiveNav] = useState("overview");
  const [filter, setFilter] = useState("전체");
  const [feedback, setFeedback] = useState(() => readSessionCache(TRACK_CACHE_KEY, []));
  const [trackLoading, setTrackLoading] = useState(() => readSessionCache(TRACK_CACHE_KEY, []).length === 0);
  const [trackError, setTrackError] = useState("");
  const [permission, setPermission] = useState("checking");
  const [notice, setNotice] = useState("");
  const cachedNotifications = readSessionCache(NOTIFICATION_CACHE_KEY, { notifications: [], unreadCount: 0 });
  const [notifications, setNotifications] = useState(cachedNotifications.notifications || []);
  const [unreadCount, setUnreadCount] = useState(cachedNotifications.unreadCount || 0);
  const [isNotificationOpen, setIsNotificationOpen] = useState(false);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(""), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const filteredFeedback = useMemo(
    () => feedback.filter((item) => filter === "전체" || item.type === filter),
    [feedback, filter],
  );

  const loadTracks = async () => {
    setTrackLoading(true);
    setTrackError("");
    try {
      const response = await fetch(`${MUZZLE_API}/tracks?limit=50`, { credentials: "include" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const nextFeedback = (payload.tracks || []).map(trackToFeedback);
      setFeedback(nextFeedback);
      window.sessionStorage.setItem(TRACK_CACHE_KEY, JSON.stringify(nextFeedback));
    } catch {
      setTrackError("muzzle 트랙 API에 연결하지 못했습니다. 서버 상태와 CORS 설정을 확인하세요.");
      setFeedback([]);
    } finally {
      setTrackLoading(false);
    }
  };

  useEffect(() => {
    fetch(`${ADMIN_API}/admin/me`, { credentials: "include" })
      .then((response) => setPermission(response.ok ? "granted" : "denied"))
      .catch(() => setPermission("denied"));
  }, []);

  useEffect(() => {
    if (permission === "granted") {
      loadTracks();
      loadNotifications();
    }
  }, [permission]);

  const markNotificationRead = async (id) => {
    await fetch(`${ADMIN_API}/admin/notifications/${id}/read`, { method: "POST", credentials: "include" });
    setNotifications((items) => items.map((item) => item.id === id ? { ...item, is_read: true } : item));
    setUnreadCount((count) => Math.max(0, count - 1));
  };

  const markAllNotificationsRead = async () => {
    await fetch(`${ADMIN_API}/admin/notifications/read-all`, { method: "POST", credentials: "include" });
    setNotifications((items) => items.map((item) => ({ ...item, is_read: true })));
    setUnreadCount(0);
  };

  const reviewItem = (id, status) => {
    setFeedback((items) => items.map((item) => item.id === id ? { ...item, status } : item));
    setNotice(status === "승인됨" ? "피드백을 승인했습니다. 다음 학습 루프에 반영됩니다." : "피드백을 보류했습니다.");
  };

  const loadNotifications = async () => {
    try {
      const response = await fetch(`${ADMIN_API}/admin/notifications?limit=30`, { credentials: "include" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setNotifications(payload.notifications || []);
      setUnreadCount(payload.unread_count || 0);
      window.sessionStorage.setItem(NOTIFICATION_CACHE_KEY, JSON.stringify({ notifications: payload.notifications || [], unreadCount: payload.unread_count || 0 }));
    } catch {
      setNotifications([]);
      setUnreadCount(0);
    }
  };

  const refreshAdminData = () => {
    loadTracks();
    loadNotifications();
  };

  if (permission === "checking") {
    return <AdminGate title="관리자 권한을 확인하는 중입니다…" detail="로그인 세션과 관리자 허용 목록을 확인하고 있습니다." />;
  }

  if (permission === "denied") {
    return <AdminGate title="관리자 권한이 없습니다" detail="관리자 이메일로 로그인했는지 확인하거나 운영 담당자에게 권한을 요청하세요." />;
  }

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar">
        <button className="admin-brand" type="button" onClick={() => navigate("/dashboard")}>
          <span className="admin-brand-mark"><img src="/cowow-bull.png" alt="COWOW 소 캐릭터" /></span>
          <span className="admin-brand-wordmark"><img src="/cowow-logo.png" alt="COWOW" /><small>관리자</small></span>
        </button>
        <div className="admin-workspace"><span className="workspace-dot" /> 한우 · 메인 워크스페이스 <span>⌄</span></div>
        <p className="admin-nav-label">관리 메뉴</p>
        <nav className="admin-nav" aria-label="관리자 메뉴">
          {navItems.map(([key, icon, label]) => (
              <button key={key} className={activeNav === key ? "active" : ""} type="button" onClick={() => setActiveNav(key)}>
              <span>{icon}</span>{label}{key === "feedback" && feedback.filter((item) => item.status === "검토 대기").length > 0 && <b>{feedback.filter((item) => item.status === "검토 대기").length}</b>}
            </button>
          ))}
        </nav>
        <div className="admin-sidebar-bottom">
          <div className="system-status"><span /><div><strong>시스템 정상</strong><small>모든 서비스가 정상 작동 중입니다</small></div></div>
          <button type="button" className="back-to-app" onClick={() => navigate("/dashboard")}>← 앱으로 돌아가기</button>
        </div>
      </aside>

      <section className="admin-content">
        <header className="admin-topbar">
          <div className="admin-breadcrumb"><span>워크스페이스</span><i>/</i><strong>{navItems.find(([key]) => key === activeNav)?.[2]}</strong></div>
          <div className="admin-top-actions"><span className="live-pill"><span /> 운영 중</span><div className="notification-anchor"><button className="icon-button" type="button" aria-label="알림" aria-expanded={isNotificationOpen} onClick={() => { setIsNotificationOpen((open) => !open); if (!isNotificationOpen) loadNotifications(); }}>♧{unreadCount > 0 && <em>{unreadCount > 99 ? "99+" : unreadCount}</em>}</button>{isNotificationOpen && <NotificationPanel notifications={notifications} onRead={markNotificationRead} onReadAll={markAllNotificationsRead} />}</div><div className="admin-avatar">SY</div><strong>관리자</strong></div>
        </header>

        <div className="admin-main">
          <div className="admin-heading-row"><div><p className="eyebrow">2026년 8월 21일 목요일</p><h1>{activeNav === "overview" ? "관리자님, 좋은 아침이에요" : navItems.find(([key]) => key === activeNav)?.[2]} <span>✦</span></h1><p className="admin-subtitle">{activeNav === "overview" ? "오늘의 모델 상태와 피드백 흐름을 한눈에 확인하세요." : "비문 식별과 ID 역전파 운영 현황을 관리하세요."}</p></div><button className="primary-button" type="button" onClick={() => { refreshAdminData(); setNotice("최신 데이터로 새로고침했습니다."); }}>↻ 데이터 새로고침</button></div>

          {notice && <div className="admin-toast" role="status">✓ {notice}</div>}

          {activeNav === "overview" && <OverviewContent tracks={feedback} filteredFeedback={filteredFeedback} filter={filter} setFilter={setFilter} setActiveNav={setActiveNav} reviewItem={reviewItem} trackLoading={trackLoading} onBound={refreshAdminData} notifications={notifications} />}
          {activeNav === "feedback" && <FeedbackWorkspace filteredFeedback={filteredFeedback} filter={filter} setFilter={setFilter} reviewItem={reviewItem} onBound={refreshAdminData} trackLoading={trackLoading} trackError={trackError} />}
          {activeNav === "loop" && <LoopWorkspace setActiveNav={setActiveNav} />}
          {activeNav === "members" && <MembersWorkspace />}
        </div>
      </section>
    </main>
  );
}

function NotificationPanel({ notifications, onRead, onReadAll }) {
  return <div className="notification-panel" role="dialog" aria-label="관리자 알림"><div className="notification-panel-head"><strong>알림</strong><button type="button" onClick={onReadAll} disabled={!notifications.some((item) => !item.is_read)}>모두 읽음</button></div>{notifications.length === 0 ? <div className="notification-empty">새 알림이 없습니다.</div> : <div className="notification-list">{notifications.map((item) => <button className={`notification-item ${item.is_read ? "read" : "unread"}`} type="button" key={item.id} onClick={() => !item.is_read && onRead(item.id)}><span className={`notification-dot ${item.severity}`} /><span className="notification-copy"><strong>{item.title}</strong><small>{item.message}</small><time>{item.created_at ? new Date(item.created_at).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "방금 전"}</time></span></button>)}</div>}</div>;
}

function AdminGate({ title, detail }) {
  const navigate = useNavigate();
  return <main className="admin-gate"><div className="admin-gate-card"><span className="admin-brand-mark"><img src="/cowow-bull.png" alt="COWOW 소 캐릭터" /></span><h1>{title}</h1><p>{detail}</p><button className="primary-button" type="button" onClick={() => navigate("/dashboard")}>대시보드로 돌아가기</button></div></main>;
}

function OverviewContent({ tracks, filteredFeedback, filter, setFilter, setActiveNav, reviewItem, trackLoading, onBound, notifications }) {
  const [selectedSegment, setSelectedSegment] = useState(null);
  const boundCount = tracks.filter((item) => item.status === "승인됨").length;
  const unboundCount = tracks.filter((item) => item.status === "검토 대기").length;
  const bindingRate = tracks.length ? `${((boundCount / tracks.length) * 100).toFixed(1)}%` : "—";
  return <>
    <div className="metric-grid">
      <MetricCard label="ID 역전파 검토 대기" value={trackLoading ? "…" : `${unboundCount}건`} delta="muzzle API" note="미바인딩 트랙" accent="orange" icon="◌" />
      <MetricCard label="현재 바인딩 적용률" value={trackLoading ? "…" : bindingRate} delta={`${boundCount}건`} note="조회된 트랙 기준" accent="green" icon="✓" />
      <MetricCard label="비문 식별 운영 기준" value="0.70" delta="서버 적용" note="유사도 임계값" accent="blue" icon="◈" />
      <MetricCard label="전체 트랙" value={trackLoading ? "…" : `${tracks.length}개`} delta="최근 50건" note="muzzle API 조회" accent="purple" icon="⟳" />
    </div>
    <div className="admin-grid-main">
      <section className="admin-panel feedback-panel"><div className="panel-heading"><div><h2>ID 역전파 피드백</h2><p>비문 식별 결과를 트랙에 연결하기 전에 확인하세요.</p></div><button className="text-button" type="button" onClick={() => setActiveNav("feedback")}>전체 보기 →</button></div><FeedbackFilters filter={filter} setFilter={setFilter} count={filteredFeedback.length} /><div className="feedback-list">{filteredFeedback.map((item) => <FeedbackRow key={item.id} item={item} onReview={reviewItem} onSelect={setSelectedSegment} />)}</div></section>
      <LoopCard tracks={tracks} setActiveNav={setActiveNav} />
    </div>
    {selectedSegment && <TrackDetailPanel segmentId={selectedSegment} onClose={() => setSelectedSegment(null)} onChanged={onBound} />}
    <ActivityPanel notifications={notifications} />
  </>;
}

function FeedbackWorkspace({ filteredFeedback, filter, setFilter, reviewItem, onBound, trackLoading, trackError }) {
  const [selectedSegment, setSelectedSegment] = useState(null);
  return <><section className="admin-panel full-panel feedback-workspace"><div className="panel-heading"><div><h2>ID 역전파 피드백</h2><p>muzzle API에서 불러온 실제 트랙과 현재 바인딩 상태입니다.</p></div><span className="count-badge">검토 대기 {filteredFeedback.filter((item) => item.status === "검토 대기").length}건</span></div>{trackError && <div className="api-error" role="alert">⚠ {trackError}</div>}<FeedbackFilters filter={filter} setFilter={setFilter} count={filteredFeedback.length} />{trackLoading && filteredFeedback.length === 0 ? <div className="empty-state">muzzle 트랙을 불러오는 중입니다…</div> : filteredFeedback.length === 0 ? <div className="empty-state">선택한 조건에 해당하는 트랙이 없습니다.</div> : <div className="feedback-list expanded-feedback-list">{filteredFeedback.map((item) => <FeedbackRow key={item.id} item={item} onReview={reviewItem} onSelect={setSelectedSegment} expanded />)}</div>}</section>{selectedSegment && <TrackDetailPanel segmentId={selectedSegment} onClose={() => setSelectedSegment(null)} onChanged={onBound} />}<BindingForm onBound={onBound} /></>;
}

function TrackDetailPanel({ segmentId, onClose, onChanged }) {
  const [track, setTrack] = useState(null);
  const [state, setState] = useState({ type: "loading", message: "트랙 상세 정보를 불러오는 중입니다…" });
  const [isUnbinding, setIsUnbinding] = useState(false);
  const loadTrack = async ({ silent = false } = {}) => {
    if (!silent) setState({ type: "loading", message: "트랙 상세 정보를 불러오는 중입니다…" });
    try {
      const response = await fetch(`${MUZZLE_API}/tracks/${segmentId}`, { credentials: "include" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`);
      setTrack(payload);
      trackDetailCache.set(String(segmentId), payload);
      setState({ type: "", message: "" });
    } catch (error) {
      setState({ type: "error", message: `상세 조회 실패: ${error.message}` });
    }
  };
  useEffect(() => {
    const cachedTrack = trackDetailCache.get(String(segmentId));
    if (cachedTrack) {
      setTrack(cachedTrack);
      setState({ type: "", message: "" });
    }
    loadTrack({ silent: Boolean(cachedTrack) });
  }, [segmentId]);
  const handleBound = async () => {
    await loadTrack();
    onChanged();
  };
  const unbind = async () => {
    setIsUnbinding(true);
    try {
      const response = await fetch(`${MUZZLE_API}/tracks/${segmentId}/bind`, { method: "DELETE", credentials: "include" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`);
      onChanged();
      onClose();
    } catch (error) { setState({ type: "error", message: `바인딩 해제 실패: ${error.message}` }); } finally { setIsUnbinding(false); }
  };
  return <div className="track-detail-overlay" role="presentation" onClick={onClose}><section className="admin-panel track-detail-panel" onClick={(event) => event.stopPropagation()}><div className="panel-heading"><div><p className="eyebrow">TRACK DETAIL</p><h2>segment #{segmentId} 상세 정보</h2><p>실제 muzzle API 응답과 현재 ID 역전파 상태입니다.</p></div><button className="close-detail-button" type="button" onClick={onClose}>닫기 ×</button></div>{state.message && <div className={state.type === "error" ? "api-error" : "empty-state"}>{state.message}</div>}{track && <><div className="track-detail-grid"><DetailValue label="카메라" value={track.camera_id} /><DetailValue label="추적 ID" value={track.track_id} /><DetailValue label="관측 프레임" value={`${track.frame_count ?? 0}건`} /><DetailValue label="세션" value={track.session_id} /><DetailValue label="시작 시각" value={track.started_at ? new Date(track.started_at).toLocaleString("ko-KR") : "-"} /><DetailValue label="원본 영상" value={track.source_video || "-"} /><div className="binding-detail"><span>현재 바인딩</span>{track.binding ? <><strong>{track.binding.national_id}</strong><small>유사도 {Number(track.binding.similarity ?? 0).toFixed(4)} · {track.binding.source}</small><button className="unbind-button" type="button" onClick={unbind} disabled={isUnbinding}>{isUnbinding ? "해제 중…" : "바인딩 해제"}</button></> : <strong className="unbound-text">미확정 트랙</strong>}</div></div>{!track.binding && <BindingForm initialSegmentId={segmentId} compact onBound={handleBound} />}</>}</section></div>;
}

function DetailValue({ label, value }) { return <div className="detail-value"><span>{label}</span><strong>{value || "-"}</strong></div>; }

function BindingForm({ onBound, initialSegmentId = "", compact = false }) {
  const [segmentId, setSegmentId] = useState(String(initialSegmentId || ""));
  const [nationalId, setNationalId] = useState("");
  const [similarity, setSimilarity] = useState("0.70");
  const [state, setState] = useState({ type: "", message: "" });
  useEffect(() => {
    setSegmentId(String(initialSegmentId || ""));
  }, [initialSegmentId]);
  useEffect(() => {
    if (!state.message || state.type === "loading") return undefined;
    const timer = window.setTimeout(() => setState({ type: "", message: "" }), 3500);
    return () => window.clearTimeout(timer);
  }, [state.message, state.type]);
  const submit = async (event) => {
    event.preventDefault();
    setState({ type: "loading", message: "실제 트랙 바인딩 API를 호출하는 중입니다…" });
    try {
      const params = new URLSearchParams({ national_id: nationalId.trim(), similarity });
      const response = await fetch(`${MUZZLE_API}/tracks/${segmentId.trim()}/bind?${params}`, { method: "POST", credentials: "include" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.detail?.message || payload?.detail || `HTTP ${response.status}`);
      setState({ type: "success", message: `segment #${payload.segment_id}에 ${payload.national_id}를 바인딩했습니다. ${payload.affected_observations ?? 0}건의 과거 관측에 반영됩니다.` });
      if (!compact) { setSegmentId(""); setNationalId(""); }
      onBound();
    } catch (error) {
      setState({ type: "error", message: `바인딩 실패: ${error.message}` });
    }
  };
  return <section className={`admin-panel full-panel binding-form-panel ${compact ? "compact-binding-panel" : ""}`}>{!compact && <div className="panel-heading"><div><h2>트랙에 ID 직접 바인딩</h2><p>muzzle API의 POST /tracks/{"{segment_id}"}/bind를 호출합니다. 유사도 0.70 미만은 서버에서 거부됩니다.</p></div><span className="api-connected-badge">실제 API</span></div>}{compact && <div className="inline-binding-heading"><strong>이 트랙 바로 바인딩</strong><span>가축이력번호와 유사도를 확인한 뒤 적용하세요.</span></div>}<form className="binding-form" onSubmit={submit}><label>segment ID<input inputMode="numeric" value={segmentId} onChange={(event) => setSegmentId(event.target.value)} placeholder="예: 184" readOnly={compact} required /></label><label>가축이력번호<input value={nationalId} onChange={(event) => setNationalId(event.target.value)} placeholder="예: 410012345678" required /></label><label>유사도<input type="number" min="0.70" max="1" step="0.0001" value={similarity} onChange={(event) => setSimilarity(event.target.value)} required /></label><button className="primary-button" type="submit" disabled={state.type === "loading"}>{state.type === "loading" ? "처리 중…" : "ID 바인딩 적용"}</button></form>{state.message && <p className={`binding-message ${state.type}`} role="status">{state.message}</p>}</section>;
}

function FeedbackFilters({ filter, setFilter, count }) {
  return <div className="filter-row"><div className="filter-tabs">{["전체", "ID 역전파", "바인딩 충돌", "미확정 트랙"].map((item) => <button type="button" key={item} className={filter === item ? "selected" : ""} onClick={() => setFilter(item)}>{item}</button>)}</div><span className="muted-count">{count}건</span></div>;
}

function LoopWorkspace({ setActiveNav }) {
  return <><section className="admin-panel full-panel loop-detail-panel"><div className="panel-heading"><div><h2>비문 ID 역전파 흐름</h2><p>한 번의 바인딩이 트랙의 과거 관측 전체에 반영되는 과정을 확인합니다.</p></div><span className="running-badge"><span /> 진행 중</span></div><div className="large-loop"><div className="large-loop-step done"><b>✓</b><strong>비문 식별</strong><small>코무늬 임베딩과 유사도 비교</small></div><div className="large-loop-step done"><b>✓</b><strong>트랙 연결</strong><small>track_segment에 개체 바인딩</small></div><div className="large-loop-step current"><b>03</b><strong>ID 역전파</strong><small>과거 track_observation에 소급</small></div><div className="large-loop-step"><b>04</b><strong>타임라인 확인</strong><small>개체별 이력으로 조회</small></div></div></section><section className="admin-panel full-panel"><div className="panel-heading"><div><h2>최근 바인딩 작업</h2><p>muzzle API에서 조회한 트랙을 피드백에서 확인하세요.</p></div><button className="secondary-button compact-button" type="button" onClick={() => setActiveNav("feedback")}>피드백에서 확인 →</button></div><div className="empty-state">피드백에서 실제 트랙을 선택하면 상세 정보와 현재 바인딩 상태를 확인할 수 있습니다.</div></section></>;
}

function MembersWorkspace() {
  const [members, setMembers] = useState([]);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!message) return undefined;
    const timer = window.setTimeout(() => setMessage(""), 3500);
    return () => window.clearTimeout(timer);
  }, [message]);
  const loadMembers = () => fetch(`${ADMIN_API}/admin/users`, { credentials: "include" }).then((response) => response.json()).then((payload) => setMembers(payload.users || [])).catch(() => setMessage("관리자 목록을 불러오지 못했습니다."));
  useEffect(() => { loadMembers(); }, []);
  const addMember = async (event) => {
    event.preventDefault();
    const response = await fetch(`${ADMIN_API}/admin/users/by-email?email=${encodeURIComponent(email)}`, { method: "POST", credentials: "include" });
    const payload = await response.json().catch(() => ({}));
    setMessage(response.ok ? "관리자를 추가했습니다." : (payload.detail || "관리자 추가에 실패했습니다."));
    if (response.ok) { setEmail(""); loadMembers(); }
  };
  const removeMember = async (id) => {
    const response = await fetch(`${ADMIN_API}/admin/users/${id}`, { method: "DELETE", credentials: "include" });
    setMessage(response.ok ? "관리자 권한을 해제했습니다." : "관리자 권한 해제에 실패했습니다.");
    if (response.ok) loadMembers();
  };
  return <section className="admin-panel full-panel members-workspace"><div className="panel-heading"><div><h2>사용자 및 권한</h2><p>DB에 저장된 관리자 권한을 추가하거나 해제합니다.</p></div><span className="api-connected-badge">DB 권한 관리</span></div><form className="member-add-form" onSubmit={addMember}><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="추가할 사용자 이메일" required /><button className="primary-button" type="submit">+ 관리자 추가</button></form>{message && <p className="binding-message success" role="status">{message}</p>}<div className="member-list">{members.map((member, index) => <div key={member.id}><span className={`member-avatar ${["blue", "green", "orange"][index % 3]}`}>{(member.name || member.email || "A").slice(0, 2).toUpperCase()}</span><div><strong>{member.name || "이름 없음"}</strong><small>{member.email}</small></div><em>관리자</em><button className="member-remove" type="button" onClick={() => removeMember(member.id)}>해제</button></div>)}{members.length === 0 && <div className="empty-state">등록된 관리자가 없습니다.</div>}</div></section>;
}

function LoopCard({ tracks, setActiveNav }) {
  const featuredTrack = tracks.find((item) => item.status === "승인됨") || tracks[0];
  return <section className="admin-panel loop-panel"><div className="panel-heading"><div><h2>비문 ID 역전파 흐름</h2><p>확정된 개체 ID가 트랙의 과거 관측에 소급 적용됩니다.</p></div><span className="running-badge"><span /> 진행 중</span></div><div className="loop-visual"><div className="loop-line"><span className="loop-progress" /></div>{[["01", "비문 식별", "코무늬 유사도 판정", "done"], ["02", "트랙 연결", "개체 ID 바인딩", "done"], ["03", "ID 역전파", "과거 관측에 소급", "current"], ["04", "타임라인", "개체 이력 확인", "pending"]].map(([number, title, desc, state]) => <div className={`loop-step ${state}`} key={number}><span className="step-number">{state === "done" ? "✓" : number}</span><strong>{title}</strong><small>{desc}</small></div>)}</div><div className="loop-footer"><div><span>현재 트랙</span><strong>{featuredTrack ? `segment #${featuredTrack.segmentId}` : "데이터 없음"}</strong></div><div><span>소급 반영 관측</span><strong>{featuredTrack ? `${featuredTrack.frameCount}건` : "—"}</strong></div><div><span>운영 임계값</span><strong>유사도 0.70</strong></div></div><button className="secondary-button" type="button" onClick={() => setActiveNav("feedback")}>트랙 상세 보기 →</button></section>;
}

function ActivityPanel({ notifications = [] }) {
  const recent = notifications.slice(0, 3);
  const tone = (severity) => severity === "success" ? "green" : severity === "warning" ? "orange" : severity === "error" ? "orange" : "purple";
  const icon = (severity) => severity === "success" ? "✓" : severity === "error" ? "!" : "⟳";
  return <section className="admin-panel activity-panel"><div className="panel-heading"><div><h2>최근 활동</h2><p>최근 바인딩과 관리자 권한 관련 시스템 이벤트입니다.</p></div><button className="text-button" type="button">알림에서 확인 →</button></div>{recent.length === 0 ? <div className="empty-state">아직 기록된 관리자 활동이 없습니다.</div> : <div className="activity-list">{recent.map((item) => <Activity key={item.id} icon={icon(item.severity)} tone={tone(item.severity)} title={item.title} detail={item.message} time={item.created_at ? new Date(item.created_at).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "방금 전"} />)}</div>}</section>;
}

function MetricCard({ label, value, delta, note, accent, icon }) { return <article className={`metric-card ${accent}`}><div className="metric-icon">{icon}</div><p>{label}</p><strong>{value}</strong><div><span>{delta}</span> <small>{note}</small></div></article>; }
function FeedbackRow({ item, onReview, onSelect, expanded = false }) { const isPending = item.status === "검토 대기"; return <article className={`feedback-row ${expanded ? "expanded" : ""}`}><span className={`feedback-type ${item.tone}`}>{item.type}</span><div className="feedback-copy"><strong>{item.subject}</strong><span>{item.detail}</span><small>{item.id} · {item.user} · {item.time}</small></div><span className={`review-status ${item.status === "승인됨" ? "approved" : item.status === "보류됨" ? "held" : "pending"}`}>{item.status}</span>{item.segmentId && <button className="detail-action" type="button" onClick={() => onSelect?.(item.segmentId)}>상세</button>}{isPending && item.nationalId && <div className="row-actions"><button className="approve-action" type="button" onClick={() => onReview(item.id, "승인됨")} aria-label={`${item.id} 승인`}><span>✓</span> 승인</button><button className="hold-action" type="button" onClick={() => onReview(item.id, "보류됨")} aria-label={`${item.id} 보류`}><span>×</span> 보류</button></div>}</article>; }
function Activity({ icon, tone, title, detail, time }) { return <div className="activity-row"><span className={`activity-icon ${tone}`}>{icon}</span><div><strong>{title}</strong><p>{detail}</p></div><time>{time}</time></div>; }

export default AdminPage;
