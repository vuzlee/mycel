import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { KeyCheck, OwnModel, OwnModelInput } from "../../api";
import {
  addOwnModel,
  deleteOwnModel,
  editOwnModel,
  fetchKeyCheck,
  fetchOwnModels,
  fetchOwnPresets,
  startKeyCheck,
} from "../../api";
import { Plus, Spinner, Trash } from "../icons";

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

/** Models a person adds with their own keys. Keys go in once and never come back: an edit
 *  shows their last four characters and keeps them unless new ones are typed. */
export function OwnModels({ onChange }: { onChange: () => void }) {
  const client = useQueryClient();
  const list = useQuery({ queryKey: OWN_KEY, queryFn: fetchOwnModels });
  const presets = useQuery({ queryKey: ["models", "presets"], queryFn: fetchOwnPresets });
  const [editing, setEditing] = useState<OwnModel | "new" | null>(null);

  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: OWN_KEY });
    onChange();
  };
  const remove = useMutation({ mutationFn: deleteOwnModel, onSuccess: refresh });

  if (list.isPending || presets.isPending) return <p className="muted">Loading…</p>;
  if (list.error) return <p className="failure">{list.error.message}</p>;
  const limits = presets.data;

  return (
    <section className="own-models">
      <header>
        <h4>Your own models</h4>
        <p className="muted">
          Any OpenAI-compatible endpoint, with your keys. Billed to you, not counted in the daily
          allowance.
        </p>
      </header>

      <ul className="model-list">
        {list.data.map((m) => (
          <li key={m.id} className="own">
            <div className="own-head">
              <b>{m.label}</b>
              <span className="muted">
                {m.model_id} · {m.key_hints.length} key{m.key_hints.length === 1 ? "" : "s"}
              </span>
              <span className="own-actions">
                <button className="link" onClick={() => setEditing(m)}>
                  Edit
                </button>
                <button
                  className="icon-button"
                  aria-label={`Delete ${m.label}`}
                  title="Delete, with its keys"
                  onClick={() => {
                    if (window.confirm(`Delete ${m.label} and its keys?`)) remove.mutate(m.id);
                  }}
                >
                  <Trash />
                </button>
              </span>
            </div>
            <KeyTest model={m} />
          </li>
        ))}
      </ul>

      {remove.error && <p className="failure">{remove.error.message}</p>}

      {editing ? (
        <OwnModelForm
          model={editing === "new" ? null : editing}
          presets={limits?.presets ?? {}}
          maxKeys={limits?.max_keys ?? 5}
          onDone={() => {
            setEditing(null);
            refresh();
          }}
          onCancel={() => setEditing(null)}
        />
      ) : (
        list.data.length < (limits?.max_models ?? 10) && (
          <button className="outline add-own" onClick={() => setEditing("new")}>
            <Plus /> Add a model
          </button>
        )
      )}
    </section>
  );
}

/** One request per key, run by the worker; the page polls until it is done. */
function KeyTest({ model }: { model: OwnModel }) {
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
  const running = start.isPending || (job !== null && result.data?.status !== "done");

  return (
    <div className="key-test">
      <button className="link" disabled={running} onClick={() => start.mutate()}>
        {running && <Spinner className="spin" size={12} />}
        Test keys
      </button>
      {result.data?.status === "done" && (
        <ul>
          {result.data.checks.map((c) => (
            <li key={c.hint} data-ok={c.ok}>
              {c.hint} · {c.ok ? "works" : c.kind ? KIND_TEXT[c.kind] : c.detail}
            </li>
          ))}
        </ul>
      )}
      {(start.error ?? result.error) && (
        <p className="failure">{(start.error ?? result.error)?.message}</p>
      )}
    </div>
  );
}

interface FormProps {
  model: OwnModel | null;
  presets: Record<string, string>;
  maxKeys: number;
  onDone: () => void;
  onCancel: () => void;
}

function OwnModelForm({ model, presets, maxKeys, onDone, onCancel }: FormProps) {
  const [label, setLabel] = useState(model?.label ?? "");
  const [modelId, setModelId] = useState(model?.model_id ?? "");
  const [base, setBase] = useState(model?.api_base ?? "");
  // Empty on an edit: typing here replaces every stored key; leaving it keeps them.
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
          placeholder="My Gemini"
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
        <span className="presets">
          {Object.entries(presets).map(([name, url]) => (
            <button type="button" className="link" key={name} onClick={() => setBase(url)}>
              {name}
            </button>
          ))}
        </span>
      </label>
      <label>
        <span className="label">Model id</span>
        <input
          required
          value={modelId}
          placeholder="gemini-2.5-flash"
          onChange={(e) => setModelId(e.target.value)}
        />
      </label>
      <fieldset>
        <legend className="label">
          API keys{model ? ` · kept: ${model.key_hints.join(" ")} unless you type new ones` : ""}
        </legend>
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
        {keys.length < maxKeys && (
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
