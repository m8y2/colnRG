import { useId } from 'react';

// A native <select>, styled with CSS rather than rebuilt as a custom
// dropdown — keyboard and screen-reader behaviour comes for free this way.
export default function NativeSelect({ id, label, hint, value, onChange, options, ...rest }) {
  const generatedId = useId();
  const selectId = id || generatedId;
  const hintId = hint ? `${selectId}-hint` : undefined;
  return (
    <div className="field">
      <label className="field__label" htmlFor={selectId}>{label}</label>
      {hint && <span className="field__hint" id={hintId}>{hint}</span>}
      <select
        id={selectId}
        className="native-select"
        value={value}
        onChange={onChange}
        aria-describedby={hintId}
        {...rest}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}
