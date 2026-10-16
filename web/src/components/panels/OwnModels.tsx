import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { KeyCheck, OwnModel, OwnModelInput } from "../../api";
import {
  addOwnModel,
  deleteOwnKey,
  deleteOwnModel,
  editOwnModel,
  fetchKeyCheck,
  fetchOwnPresets,
  startKeyCheck,
} from "../../api";
import { Close, Plus, Spinner, Trash } from "../icons";

export const OWN_KEY = ["models", "own"];

const POLL_MS = 1500;

/** What a failed key means, in words a person can act on. */
const KIND_TEXT: Record<NonNullable<KeyCheck["kind"]>, string> = {
  quota: "out of quota",
  auth: "key rejected",
  not_found: "model id not found",
  unreachable: "endpoint not reachable",
  provider: "provider error",
};

/** One test per key, run by the worker; polled until done. Results are keyed by hint. */
export function useKeyCheck(model: OwnModel) {
  const [job, setJob] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => startKeyCheck(model.id),
    onSuccess: (state) => setJob(state.job_id),
  });
  const result = useQuery({
    queryKey: ["models", "keycheck", job],
    queryFn: () => fetchKeyCheck(job as string),
    enabled: job !== null,
    refetchInterval: (q) => (q.state.data?.status === "done" ? false : POLL_MS),
  });
  const done = result.data?.status === "done" ? result.data.checks : null;
  return {
    run: () => start.mutate(),
    running: start.isPending || (job !== null && !done),
    checks: new Map((done ?? []).map((c) => [c.hint, c])),
    error: start.error ?? result.error,
  };
}
export type KeyCheckRun = ReturnType<typeof useKeyCheck>;

/** Test, edit and delete for one own model, in the head of its row. */
export function OwnActions({
  model,
  check,
  onEdit,
  onChange,
}: {
  model: OwnModel;
  check: KeyCheckRun;
  onEdit: () => void;
  onChange: () => void;
}) {
  const client = useQueryClient();
  const remove = useMutation({
    mutationFn: deleteOwnModel,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: OWN_KEY });
      onChange();
    },
  });
  return (
    <>
      <button className="link" disabled={check.running} onClick={check.run}>
        {check.running && <Spinner className="spin" size={12} />}
        {check.running ? "Testing" : "Test keys"}
      </button>
      <button className="link" onClick={onEdit}>
        Edit
      </button>
      <button
        className="icon-button danger"
        aria-label={`Delete ${model.label}`}
        title={remove.error?.message ?? "Delete, with its keys"}
        onClick={() => {
          if (window.confirm(`Delete ${model.label} and its keys?`)) remove.mutate(model.id);
        }}
      >
        <Trash />
      </button>
    </>
  );
}

/** The keys of one model as chips: what the last test found, and a way to drop a dead one
 *  so runs stop spending time retrying it. The last key cannot go. */
export function KeyChips({ model, check }: { model: OwnModel; check: KeyCheckRun }) {
  const client = useQueryClient();
  const drop = useMutation({
    mutationFn: (index: number) => deleteOwnKey(model.id, index),
    onSuccess: () => void client.invalidateQueries({ queryKey: OWN_KEY }),
  });
  const tested = model.key_hints.filter((h) => check.checks.has(h));
  const working = tested.filter((h) => check.checks.get(h)?.ok).length;
  const failure = drop.error ?? check.error;

  return (
    <div className="key-row">
      <ul className="key-chips">
        {model.key_hints.map((h, i) => {
          const c = check.checks.get(h);
          const state = c ? (c.ok ? "ok" : "bad") : check.running ? "busy" : "idle";
          const note = c && !c.ok ? (c.kind ? KIND_TEXT[c.kind] : c.detail) : null;
          return (
            <li key={`${h}-${i}`} className="key-chip" data-state={state} title={c?.detail}>
              <span className="dot" aria-hidden />
              <code>{h}</code>
              {note && <span className="note">{note}</span>}
              {model.key_hints.length > 1 && (
                <button
                  className="chip-x"
                  aria-label={`Remove key ${h}`}
                  title="Remove this key"
                  disabled={drop.isPending}
                  onClick={() => {
                    if (window.confirm(`Remove key ${h}?`)) drop.mutate(i);
                  }}
                >
                  <Close size={11} />
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {tested.length > 0 && !check.running && (
        <span className="key-summary" data-all={working === tested.length}>
          {working === tested.length
            ? `All ${working} key${working === 1 ? "" : "s"} work`
            : `${working} of ${tested.length} work`}
        </span>
      )}
      {failure && <span className="failure">{failure.message}</span>}
    </div>
  );
}

/** The add button, or the form while adding or editing. Keys go in once and never come back:
 *  an edit shows their last four characters and keeps them unless new ones are typed. */
export function OwnModelEditor({
  editing,
  count,
  setEditing,
  onChange,
}: {
  editing: OwnModel | "new" | null;
  count: number;
  setEditing: (m: OwnModel | "new" | null) => void;
  onChange: () => void;
}) {
  const client = useQueryClient();
  const presets = useQuery({ queryKey: ["models", "presets"], queryFn: fetchOwnPresets });
  const limits = presets.data;
  if (editing)
    return (
      <OwnModelForm
        key={editing === "new" ? "new" : editing.id}
        model={editing === "new" ? null : editing}
        maxKeys={limits?.max_keys ?? 5}
        onDone={() => {
          setEditing(null);
          void client.invalidateQueries({ queryKey: OWN_KEY });
          onChange();
        }}
        onCancel={() => setEditing(null)}
      />
    );
  if (count >= (limits?.max_models ?? 10)) return null;
  return (
    <button className="outline add-own" onClick={() => setEditing("new")}>
      <Plus /> Add your own model
    </button>
  );
}

interface FormProps {
  model: OwnModel | null;
  maxKeys: number;
  onDone: () => void;
  onCancel: () => void;
}

function OwnModelForm({ model, maxKeys, onDone, onCancel }: FormProps) {
  const [label, setLabel] = useState(model?.label ?? "");
  const [modelId, setModelId] = useState(model?.model_id ?? "");
  const [base, setBase] = useState(model?.api_base ?? "");
  // On an edit, typed keys are added after the stored ones.
  const [keys, setKeys] = useState<string[]>([""]);

  const save = useMutation({
    mutationFn: () => {
      const typed = keys.map((k) => k.trim()).filter(Boolean);
      const input: OwnModelInput = { label, model_id: modelId, api_base: base };
      if (!model || typed.length) input.keys = typed;
      return model ? editOwnModel(model.id, input) : addOwnModel(input);
    },
    onSuccess: onDone,
  });

  return (
    <form
      className="own-form"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label>
        <span className="label">Name</span>
        <input
          required
          maxLength={80}
          value={label}
          placeholder="My model"
          onChange={(e) => setLabel(e.target.value)}
        />
      </label>
      <label>
        <span className="label">Base URL</span>
        <input
          required
          value={base}
          placeholder="https://…/v1"
          onChange={(e) => setBase(e.target.value)}
        />
      </label>
      <label>
        <span className="label">Model id</span>
        <input
          required
          value={modelId}
          placeholder="the id your provider uses"
          onChange={(e) => setModelId(e.target.value)}
        />
      </label>
      <fieldset>
        <legend className="label">{model ? "Add keys (optional)" : "API keys"}</legend>
        {keys.map((k, i) => (
          <input
            key={i}
            type="password"
            autoComplete="off"
            required={!model && i === 0}
            value={k}
            placeholder={i === 0 ? "sk-…" : "another key, tried when one runs out"}
            onChange={(e) => setKeys(keys.map((v, j) => (j === i ? e.target.value : v)))}
          />
        ))}
        {keys.length < maxKeys - (model?.key_hints.length ?? 0) && (
          <button type="button" className="link" onClick={() => setKeys([...keys, ""])}>
            <Plus size={12} /> Add key
          </button>
        )}
      </fieldset>

      {save.error && <p className="failure">{save.error.message}</p>}

      <div className="form-actions">
        <button type="button" className="outline" onClick={onCancel}>
          Cancel
        </button>
        <button className="primary" type="submit" disabled={save.isPending}>
          {save.isPending && <Spinner className="spin" size={14} />}
          {model ? "Save" : "Add"}
        </button>
      </div>
    </form>
  );
}
