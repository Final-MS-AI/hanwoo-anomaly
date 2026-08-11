import { useMemo, useState } from "react";
import "./AbnormalCattleDashboard.css";
import DashboardAlertFeedback from "./DashboardAlertFeedback";
import {
  abnormalCattle,
  cattleSummary,
  recentAlerts,
} from "./data/mockDashboardData";

function AbnormalCattleDashboard() {
  const [filter, setFilter] = useState("all");
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);

  const filteredCattle = useMemo(() => {
    if (filter === "all") {
      return abnormalCattle;
    }

    return abnormalCattle.filter(
      (cattle) => cattle.status === filter,
    );
  }, [filter]);

  return (
    <section className="abnormal-dashboard">
      <div className="abnormal-dashboard-header">
        <div>
          <span className="dashboard-label">실시간 개체 관리</span>
          <h2>이상 개체 대시보드</h2>
          <p>행동 변화가 감지된 개체를 확인합니다.</p>
        </div>

        <span className="dashboard-update-time">
          최종 갱신 11:20
        </span>
      </div>

      <div className="dashboard-summary-grid">
        <article className="dashboard-summary-card">
          <span>전체 개체</span>
          <strong>{cattleSummary.total}</strong>
          <small>마리</small>
        </article>

        <article className="dashboard-summary-card normal">
          <span>정상</span>
          <strong>{cattleSummary.normal}</strong>
          <small>마리</small>
        </article>

        <article className="dashboard-summary-card warning">
          <span>주의</span>
          <strong>{cattleSummary.warning}</strong>
          <small>마리</small>
        </article>

        <article className="dashboard-summary-card danger">
          <span>위험</span>
          <strong>{cattleSummary.danger}</strong>
          <small>마리</small>
        </article>
      </div>

      <div className="dashboard-priority-card">
        <div className="dashboard-priority-status">
          <span className="cattle-status-dot danger" />
          <div>
            <strong>지금 확인할 위험 개체</strong>
            <span>
              위험 {cattleSummary.danger}마리 · 주의 {cattleSummary.warning}마리
            </span>
          </div>
        </div>

        <button
          className="dashboard-details-button"
          type="button"
          aria-expanded={isDetailsOpen}
          aria-controls="dashboard-details"
          onClick={() => setIsDetailsOpen((previous) => !previous)}
        >
          {isDetailsOpen ? "상세 현황 접기" : "상세 현황 보기"}
          <span aria-hidden="true">{isDetailsOpen ? "▲" : "›"}</span>
        </button>
      </div>

      <div
        id="dashboard-details"
        className={`dashboard-content-grid ${
          isDetailsOpen ? "is-open" : "is-collapsed"
        }`}
      >
        <div className="dashboard-panel">
          <div className="dashboard-panel-header">
            <div>
              <h3>이상 개체 목록</h3>
              <p>위험도에 따라 개체를 분류합니다.</p>
            </div>

            <div className="dashboard-filter-buttons">
              <button
                type="button"
                className={filter === "all" ? "active" : ""}
                onClick={() => setFilter("all")}
              >
                전체
              </button>

              <button
                type="button"
                className={filter === "danger" ? "active" : ""}
                onClick={() => setFilter("danger")}
              >
                위험
              </button>

              <button
                type="button"
                className={filter === "warning" ? "active" : ""}
                onClick={() => setFilter("warning")}
              >
                주의
              </button>
            </div>
          </div>

          <div className="abnormal-cattle-list">
            {filteredCattle.map((cattle) => (
              <article
                className={`abnormal-cattle-item ${cattle.status}`}
                key={cattle.id}
              >
                <div className="cattle-status-area">
                  <span
                    className={`cattle-status-dot ${cattle.status}`}
                  />
                  <strong>{cattle.cattleId}</strong>
                </div>

                <span className="cattle-behavior">
                  {cattle.behavior}
                </span>

                <time>{cattle.lastDetectedAt}</time>

                <DashboardAlertFeedback cattle={cattle} />
              </article>
            ))}
          </div>
        </div>

        <aside className="dashboard-panel recent-alert-panel">
          <div className="dashboard-panel-header">
            <div>
              <h3>최근 이상 알림</h3>
              <p>최근 감지된 주요 행동입니다.</p>
            </div>
          </div>

          <div className="recent-alert-list">
            {recentAlerts.map((alert) => (
              <article
                className={`recent-alert-item ${alert.status}`}
                key={alert.id}
              >
                <span
                  className={`cattle-status-dot ${alert.status}`}
                />

                <div>
                  <strong>{alert.cattleId}</strong>
                  <p>{alert.behavior}</p>
                </div>

                <time>{alert.time}</time>
              </article>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}

export default AbnormalCattleDashboard;

