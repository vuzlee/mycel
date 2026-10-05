/**
 * The sources a turn may use, picked as chips. With none picked the model gets no tools:
 * it answers from what it knows, and asking about Jira without the Jira chip gets nothing.
 */

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
  onPick: (chip: Chip) => void;
}

export function ChipMenu({ picked, locked, filter = "", onPick }: MenuProps) {
  const shown = CHIPS.filter(
    (c) => !picked.includes(c.id) && c.label.toLowerCase().startsWith(filter.toLowerCase()),
  );
  if (shown.length === 0) return null;
  return (
    <ul className="chip-menu" role="listbox" aria-label="Sources">
      {shown.map((chip) => (
        <li key={chip.id}>
          <button
            type="button"
            role="option"
            aria-selected={false}
            disabled={Boolean(locked[chip.id])}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(chip.id)}
          >
            <b>{chip.label}</b>
            <small>{locked[chip.id] ?? chip.hint}</small>
          </button>
        </li>
      ))}
    </ul>
  );
}

interface ChipsProps {
  picked: Chip[];
  dimmed: Partial<Record<Chip, string>>;
  onRemove: (chip: Chip) => void;
}

/** The picked chips, highlighted inside the composer. */
export function PickedChips({ picked, dimmed, onRemove }: ChipsProps) {
  if (picked.length === 0) return null;
  return (
    <div className="chips">
      {picked.map((id) => (
        <span key={id} className="chip" data-dim={Boolean(dimmed[id])} title={dimmed[id]}>
          {labelOf(id)}
          <button type="button" aria-label={`Remove ${labelOf(id)}`} onClick={() => onRemove(id)}>
            ×
          </button>
        </span>
      ))}
    </div>
  );
}
