/** The sources a turn may use, picked as chips; with none picked the model gets no tools. */

import type { Chip } from "../api";

export const CHIPS: { id: Chip; label: string; hint: string }[] = [
  { id: "knowledge", label: "Knowledge", hint: "Your uploaded documents" },
  { id: "web", label: "Web", hint: "Search the web" },
  { id: "jira", label: "Jira", hint: "Your team's work" },
  { id: "calendar", label: "Calendar", hint: "Your events" },
  { id: "mail", label: "Mail", hint: "Your inbox headers" },
];

export const labelOf = (id: Chip): string => CHIPS.find((c) => c.id === id)?.label ?? id;

interface MenuProps {
  picked: Chip[];
  /** Chips that cannot be picked right now, with the reason shown beside them. */
  locked: Partial<Record<Chip, string>>;
  /** Narrows the list as `@` is typed. */
  filter?: string;
  onToggle: (chip: Chip) => void;
}

/** Every source with a tick; picking toggles it. The composer never changes size. */
export function ChipMenu({ picked, locked, filter = "", onToggle }: MenuProps) {
  const shown = CHIPS.filter((c) => c.label.toLowerCase().startsWith(filter.toLowerCase()));
  if (shown.length === 0) return null;
  return (
    <ul className="chip-menu" role="listbox" aria-label="Sources" aria-multiselectable>
      {shown.map((chip) => {
        const on = picked.includes(chip.id);
        return (
          <li key={chip.id}>
            <button
              type="button"
              role="option"
              aria-selected={on}
              disabled={Boolean(locked[chip.id]) && !on}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => onToggle(chip.id)}
            >
              <span className="tick">{on ? "✓" : ""}</span>
              <b>{chip.label}</b>
              <small>{locked[chip.id] ?? chip.hint}</small>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
