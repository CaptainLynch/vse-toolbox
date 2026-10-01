// Searchable token multi-select (legacy createSearchMultiSelect).
// Controlled: `values` in, `onChange(values)` out. Only one option list is
// open at a time across the page.
import { html, useEffect, useRef, useState } from "/static/host/vendor/preact-htm.js";
import { safeDisplayValue } from "./format.js";

let activeCloser = null;

function normalizeOptions(options, labelFor) {
  return (options || []).map((option) => {
    if (Array.isArray(option)) return { value: String(option[0]), label: String(option[1]) };
    const value = String(option);
    return { value, label: String(labelFor(value) || value) };
  });
}

export function SearchMultiSelect({
  ariaLabel,
  placeholder,
  options,
  values,
  onChange,
  normalizeValue = (value) => value,
  labelFor = (value) => value,
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef(null);
  const rootRef = useRef(null);
  const selected = Array.isArray(values) ? values : [];
  const items = normalizeOptions(options, labelFor);

  const close = useRef(null);
  close.current = () => setOpen(false);
  const closer = useRef(() => close.current());
  useEffect(() => () => {
    if (activeCloser === closer.current) activeCloser = null;
  }, []);

  const openList = () => {
    if (open) return;
    if (activeCloser && activeCloser !== closer.current) activeCloser();
    activeCloser = closer.current;
    setOpen(true);
  };
  const closeList = () => {
    setOpen(false);
    if (activeCloser === closer.current) activeCloser = null;
  };

  const emit = (next) => {
    if (onChange) onChange(next);
  };
  const addValue = (raw) => {
    const value = normalizeValue(String(raw || "").trim());
    setText("");
    if (!value || selected.includes(value)) return;
    emit([...selected, value]);
  };
  const removeValue = (value) => {
    emit(selected.filter((item) => item !== value));
    if (inputRef.current) inputRef.current.focus();
  };

  const query = text.trim().toLocaleLowerCase();
  const matches = items.filter((option) => {
    if (selected.includes(option.value)) return false;
    return !query || option.label.toLocaleLowerCase().includes(query) || option.value.toLocaleLowerCase().includes(query);
  });

  const onKeyDown = (event) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addValue(text);
    } else if (event.key === "Escape" && open) {
      closeList();
    } else if (event.key === "Backspace" && !text && selected.length > 0) {
      emit(selected.slice(0, -1));
    }
  };

  return html`<div
    class="analysis-multi-select"
    role="group"
    aria-label=${ariaLabel}
    ref=${rootRef}
    onfocusout=${(event) => {
      if (!rootRef.current || !rootRef.current.contains(event.relatedTarget)) closeList();
    }}
  >
    <div class="analysis-multi-select-control" onClick=${() => inputRef.current && inputRef.current.focus()}>
      <div class="analysis-multi-select-tokens">
        ${selected.map((value) => html`<span class="analysis-filter-token" key=${value}>
          <span class="analysis-filter-token-label">${safeDisplayValue(labelFor(value))}</span>
          <button
            type="button"
            class="analysis-filter-token-remove"
            aria-label=${`移除 ${safeDisplayValue(labelFor(value))}`}
            onClick=${(event) => { event.stopPropagation(); removeValue(value); }}
          >×</button>
        </span>`)}
        <input
          ref=${inputRef}
          type="text"
          class="analysis-multi-select-input"
          placeholder=${placeholder}
          aria-label=${ariaLabel}
          autocomplete="off"
          value=${text}
          onFocus=${openList}
          onInput=${(event) => { setText(event.currentTarget.value); openList(); }}
          onKeyDown=${onKeyDown}
        />
      </div>
    </div>
    <div class="analysis-multi-select-options" role="listbox" hidden=${!open || matches.length === 0}>
      ${matches.slice(0, 30).map((option) => html`<button
        type="button"
        key=${option.value}
        class="analysis-multi-select-option"
        role="option"
        data-value=${option.value}
        onMouseDown=${(event) => event.preventDefault()}
        onClick=${() => addValue(option.value)}
      >${option.label}</button>`)}
    </div>
  </div>`;
}
