import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";
import type { ModelChoice, Models, OwnModel } from "../../api";
import { fetchModels, fetchOwnModels, setDefaultModel, toggleModel } from "../../api";
import { KeyChips, OWN_KEY, OwnActions, OwnModelEditor, useKeyCheck } from "./OwnModels";

export const MODELS_KEY = ["models"];

/** One list of the models this person may ask with: a switch, the one picked first, and for
 *  their own models the test, edit and delete in the same row. */
export function ModelsPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: MODELS_KEY, queryFn: fetchModels });
  const own = useQuery({ queryKey: OWN_KEY, queryFn: fetchOwnModels });
  const [editing, setEditing] = useState<OwnModel | "new" | null>(null);
  const save = (found: Models): void => {
    client.setQueryData(MODELS_KEY, found);
  };
  const refresh = (): void => void client.invalidateQueries({ queryKey: MODELS_KEY });
  const toggle = useMutation({
    mutationFn: ({ ref, on }: { ref: string; on: boolean }) => toggleModel(ref, on),
    onSuccess: save,
  });
  const pick = useMutation({ mutationFn: setDefaultModel, onSuccess: save });

  if (query.error ?? own.error)
    return <p className="failure">{(query.error ?? own.error)?.message}</p>;
  if (!query.data || !own.data) return <p className="muted">Loading…</p>;

  const { models, default_ref } = query.data;
  const byRef = new Map(own.data.map((m) => [m.ref, m]));
  const on = models.filter((m) => m.enabled).length;
  const failure = toggle.error ?? pick.error;

  return (
    <div className="models">
      <ul className="model-list">
        {models.map((m) => (
          <ModelRow
            key={m.ref}
            choice={m}
            mine={byRef.get(m.ref)}
            isDefault={m.ref === default_ref}
            last={m.enabled && on === 1}
            busy={toggle.isPending}
            picking={pick.isPending}
            onToggle={(next) => toggle.mutate({ ref: m.ref, on: next })}
            onPick={() => pick.mutate(m.ref)}
            onEdit={setEditing}
            onChange={refresh}
          />
        ))}
      </ul>
      {failure && <p className="failure">{failure.message}</p>}
      <OwnModelEditor
        editing={editing}
        count={own.data.length}
        setEditing={setEditing}
        onChange={refresh}
      />
      <p className="muted own-note">
        Your own models: any OpenAI-compatible endpoint, with your keys. Billed to you, not counted
        in the daily allowance.
      </p>
    </div>
  );
}

interface RowProps {
  choice: ModelChoice;
  mine: OwnModel | undefined;
  isDefault: boolean;
  last: boolean;
  busy: boolean;
  picking: boolean;
  onToggle: (on: boolean) => void;
  onPick: () => void;
  onEdit: (m: OwnModel) => void;
  onChange: () => void;
}

function ModelRow(props: RowProps) {
  return props.mine ? <OwnRow {...props} mine={props.mine} /> : <Row {...props} />;
}

/** An own model shares one key test between the head's button and the chips below. */
function OwnRow(props: RowProps & { mine: OwnModel }) {
  const check = useKeyCheck(props.mine);
  return (
    <Row
      {...props}
      detail={props.mine.model_id}
      actions={
        <OwnActions
          model={props.mine}
          check={check}
          onEdit={() => props.onEdit(props.mine)}
          onChange={props.onChange}
        />
      }
      below={<KeyChips model={props.mine} check={check} />}
    />
  );
}

function Row(props: RowProps & { detail?: string; actions?: ReactNode; below?: ReactNode }) {
  const m = props.choice;
  return (
    <li data-source={m.source}>
      <div className="model-head">
        <input
          type="checkbox"
          aria-label={`Use ${m.label}`}
          title={props.last ? "At least one model stays on" : undefined}
          checked={m.enabled}
          disabled={props.last || props.busy}
          onChange={(event) => props.onToggle(event.target.checked)}
        />
        <span className="model-name">
          <b>{m.label}</b>
          <span className="muted">{props.detail ?? "included"}</span>
        </span>
        <span className="model-actions">
          {props.isDefault ? (
            <span className="pill on">Default</span>
          ) : (
            <button className="link" disabled={!m.enabled || props.picking} onClick={props.onPick}>
              Make default
            </button>
          )}
          {props.actions}
        </span>
      </div>
      {props.below}
    </li>
  );
}
