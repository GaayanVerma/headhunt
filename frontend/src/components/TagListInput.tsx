import { useState, KeyboardEvent } from "react";

interface Props {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}

export function TagListInput({ values, onChange, placeholder }: Props) {
  const [draft, setDraft] = useState("");

  function commit() {
    const trimmed = draft.trim();
    if (trimmed && !values.includes(trimmed)) {
      onChange([...values, trimmed]);
    }
    setDraft("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && draft === "" && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  function remove(index: number) {
    onChange(values.filter((_, i) => i !== index));
  }

  return (
    <div>
      {values.length > 0 && (
        <div className="tag-list">
          {values.map((value, i) => (
            <span className="tag-pill" key={`${value}-${i}`}>
              {value}
              <button type="button" onClick={() => remove(i)} aria-label={`Remove ${value}`}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="tag-input-row">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commit}
          placeholder={placeholder}
        />
      </div>
    </div>
  );
}
