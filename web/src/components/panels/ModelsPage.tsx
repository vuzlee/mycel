import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Models } from "../../api";
import { fetchModels, setDefaultModel, toggleModel } from "../../api";
import { OwnModels } from "./OwnModels";

export const MODELS_KEY = ["models"];

/** The models this person may ask with: a switch per model and the one picked first, then
 *  the ones they added with their own keys. The host's list comes from its config; a model
 *  that is off leaves the composer's picker. */
export function ModelsPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: MODELS_KEY, queryFn: fetchModels });
  const save = (found: Models): void => {
    client.setQueryData(MODELS_KEY, found);
  };
  const toggle = useMutation({
    mutationFn: ({ ref, on }: { ref: string; on: boolean }) => toggleModel(ref, on),
    onSuccess: save,
  });
  const pick = useMutation({ mutationFn: setDefaultModel, onSuccess: save });

  if (query.isPending) return <p className="muted">Loading…</p>;
  if (query.error) return <p className="failure">{query.error.message}</p>;

  const { models, default_ref } = query.data;
  const on = models.filter((m) => m.enabled).length;
  const failure = toggle.error ?? pick.error;

  return (
    <div className="models">
      <ul className="model-list">
        {models.map((m) => {
          const last = m.enabled && on === 1;
          return (
            <li key={m.ref} data-source={m.source}>
              <label className="switch" title={last ? "At least one model stays on" : undefined}>
                <input
                  type="checkbox"
                  checked={m.enabled}
                  disabled={last || toggle.isPending}
                  onChange={(event) => toggle.mutate({ ref: m.ref, on: event.target.checked })}
                />
                <span>{m.label}</span>
              </label>
              {m.ref === default_ref ? (
                <span className="pill on">Default</span>
              ) : (
                <button
                  className="link"
                  disabled={!m.enabled || pick.isPending}
                  onClick={() => pick.mutate(m.ref)}
                >
                  Make default
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {failure && <p className="failure">{failure.message}</p>}
      <OwnModels onChange={() => void client.invalidateQueries({ queryKey: MODELS_KEY })} />
    </div>
  );
}
