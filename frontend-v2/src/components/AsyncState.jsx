// Loading / empty / error states. Async regions announce politely so a
// screen reader user isn't left guessing whether something is happening.

export function LoadingState({ label = 'Loading…' }) {
  return (
    <div className="state-block" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state-block state-block--error" role="alert">
      <span className="state-block__title">This could not be loaded</span>
      <span>{message || 'Something went wrong. Please try again.'}</span>
      {onRetry && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message = 'There is nothing to show here yet.', children }) {
  return (
    <div className="state-block" role="status">
      <span>{message}</span>
      {children}
    </div>
  );
}
