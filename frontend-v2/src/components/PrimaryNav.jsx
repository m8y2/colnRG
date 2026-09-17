// The main site navigation. Implemented as plain links in a <nav> landmark
// (one of the two accessible patterns the spec allows) rather than a
// button-based tablist, since each item is a distinct page, not a panel
// within one page. Current page is marked with aria-current="page", which
// screen readers announce regardless of how layout.css styles it visually
// (currently: darker text only, by the owner's own choice -- see the
// aria-current rule there for the accessibility trade-off that leaves).
export default function PrimaryNav({ items, current }) {
  return (
    <nav className="primary-nav" aria-label="Primary">
      <ul className="primary-nav__list">
        {items.map((item) => (
          <li key={item.path}>
            <a
              className="primary-nav__link"
              href={`#/${item.path}`}
              aria-current={current === item.path ? 'page' : undefined}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
