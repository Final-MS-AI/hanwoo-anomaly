export const cattleSummary = {
  total: 60,
  normal: 53,
  warning: 5,
  danger: 2,
};

export const abnormalCattle = [
  {
    id: 1,
    cattleId: "COW-012",
    status: "danger",
    behavior: "장시간 누움",
    lastDetectedAt: "2026-08-03 11:18",
  },
  {
    id: 2,
    cattleId: "COW-027",
    status: "danger",
    behavior: "기립 시도 반복",
    lastDetectedAt: "2026-08-03 11:12",
  },
  {
    id: 3,
    cattleId: "COW-034",
    status: "warning",
    behavior: "이동량 감소",
    lastDetectedAt: "2026-08-03 10:54",
  },
  {
    id: 4,
    cattleId: "COW-041",
    status: "warning",
    behavior: "반추 시간 감소",
    lastDetectedAt: "2026-08-03 10:37",
  },
  {
    id: 5,
    cattleId: "COW-052",
    status: "warning",
    behavior: "급이대 체류 감소",
    lastDetectedAt: "2026-08-03 10:11",
  },
];

export const recentAlerts = [
  {
    id: 1,
    cattleId: "COW-012",
    status: "danger",
    behavior: "장시간 누움",
    time: "11:18",
  },
  {
    id: 2,
    cattleId: "COW-027",
    status: "danger",
    behavior: "기립 시도 반복",
    time: "11:12",
  },
  {
    id: 3,
    cattleId: "COW-034",
    status: "warning",
    behavior: "이동량 감소",
    time: "10:54",
  },
];
