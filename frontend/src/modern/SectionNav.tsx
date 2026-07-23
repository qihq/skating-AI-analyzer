import { Link } from "react-router-dom";

export type SectionItem = { id: string; label: string; to: string };

export default function SectionNav({ items, activeId, label }: { items: SectionItem[]; activeId: string; label: string }) {
  return (
    <nav aria-label={label} className="island-section-nav">
      {items.map((item) => (
        <Link key={item.id} to={item.to} aria-current={item.id === activeId ? "page" : undefined} className={item.id === activeId ? "is-active" : ""}>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
