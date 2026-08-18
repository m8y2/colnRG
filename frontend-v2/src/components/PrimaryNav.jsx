// The main site navigation. Implemented as plain links in a <nav> landmark
// (one of the two accessible patterns the spec allows) rather than a
// button-based tablist, since each item is a distinct page, not a panel
// within one page. Current page is marked with aria-current="page", which
// screen readers announce and which layout.css turns into an underline —
// never colour alone.
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
