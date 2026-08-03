import { NavLink } from "react-router-dom";

const navigationItems = [
  {
    to: "/dashboard",
    icon: "⌂",
    label: "대시보드",
  },
  {
    to: "/inference",
    icon: "▶",
    label: "영상 분석",
  },
  {
    to: "/cattle/register",
    icon: "＋",
    label: "소 등록",
  },
];

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
            {item.icon}
          </span>

          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export default BottomNavigation;
