import { NavLink } from "react-router-dom";

import { MODERN_NAV_ITEMS, ModernSpace } from "../navigation";
import IslandIcon from "./IslandIcon";

type Props = { activeSpace?: ModernSpace };

export function IslandDock({ activeSpace }: Props) {
  return (
    <nav aria-label="主要导航" className="island-dock">
      {MODERN_NAV_ITEMS.map((item) => (
        <NavLink
          key={item.space}
          to={item.to}
          className={`island-dock__item ${item.primary ? "island-dock__item--primary" : ""} ${activeSpace === item.space ? "is-active" : ""}`}
        >
          <span className="island-dock__icon"><IslandIcon name={item.icon} /></span>
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function IslandRail({ activeSpace }: Props) {
  return (
    <aside className="island-rail">
      <NavLink to="/home" className="island-brand" aria-label="IceBuddy 今日岛屿">
        <span className="island-brand__mark">❄</span>
        <span><strong>IceBuddy</strong><small>冰上成长岛</small></span>
      </NavLink>
      <nav aria-label="主要导航" className="island-rail__nav">
        {MODERN_NAV_ITEMS.map((item) => (
          <NavLink key={item.space} to={item.to} className={`island-rail__item ${item.primary ? "island-rail__item--primary" : ""} ${activeSpace === item.space ? "is-active" : ""}`}>
            <span className="island-rail__icon"><IslandIcon name={item.icon} /></span>
            <span><strong>{item.label}</strong><small>{item.detail}</small></span>
          </NavLink>
        ))}
      </nav>
      <div className="island-rail__note">
        <span aria-hidden="true">🌱</span>
        <p>今天也记录一点小进步</p>
      </div>
    </aside>
  );
}
