import { NavLink } from "react-router-dom";

const navigationItems = [
  {
    to: "/dashboard",
    icon: "dashboard",
    label: "대시보드",
  },
  {
    to: "/inference",
    icon: "zone",
    label: "구역 지정",
  },
  {
    to: "/cattle/register",
    icon: "register",
    label: "소 등록",
  },
  {
    to: "/chat",
    icon: "chat",
    label: "AI 상담",
  },
  {
    to: "/control",
    icon: "control",
    label: "환경 제어",
  },
];

function NavigationIcon({ name }) {
  const commonProps = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };

  switch (name) {
    case "dashboard":
      return (
        <svg {...commonProps}>
          <path d="M3 11.5 12 4l9 7.5" />
          <path d="M5.5 10.5V20h13v-9.5" />
          <path d="M9.5 20v-6h5v6" />
        </svg>
      );

    case "zone":
      return (
        <svg {...commonProps}>
          <path d="M8 3H5a2 2 0 0 0-2 2v3" />
          <path d="M16 3h3a2 2 0 0 1 2 2v3" />
          <path d="M21 16v3a2 2 0 0 1-2 2h-3" />
          <path d="M8 21H5a2 2 0 0 1-2-2v-3" />
          <rect x="8" y="8" width="8" height="8" rx="1.5" />
        </svg>
      );

    case "register":
      return (
        <svg {...commonProps}>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 8v8" />
          <path d="M8 12h8" />
        </svg>
      );

    case "chat":
      return (
        <svg {...commonProps}>
          <path d="m12 3 1.25 3.75L17 8l-3.75 1.25L12 13l-1.25-3.75L7 8l3.75-1.25L12 3Z" />
          <path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7.7-2.3Z" />
          <path d="m5.5 14 .55 1.7 1.7.55-1.7.55-.55 1.7-.55-1.7-1.7-.55 1.7-.55.55-1.7Z" />
        </svg>
      );

    case "control":
      return (
        <svg {...commonProps}>
          <path d="M4 7h10" />
          <path d="M18 7h2" />
          <circle cx="16" cy="7" r="2" />
          <path d="M4 17h2" />
          <path d="M10 17h10" />
          <circle cx="8" cy="17" r="2" />
          <path d="M4 12h5" />
          <path d="M13 12h7" />
          <circle cx="11" cy="12" r="2" />
        </svg>
      );

    default:
      return null;
  }
}

function BottomNavigation() {
  return (
    <nav
      className="bottom-navigation"
      aria-label="주요 페이지"
    >
      {navigationItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `bottom-navigation-item ${
              isActive ? "active" : ""
            }`
          }
        >
          <span className="bottom-navigation-icon">
            <NavigationIcon name={item.icon} />
          </span>

          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export default BottomNavigation;
