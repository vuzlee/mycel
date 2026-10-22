/** Host models a person picks, and models they add with their own keys. */

import { del, get, post, request, shaped } from "./client";
import type { Shape } from "./client";

/** One model the picker offers; `ref` is what a question is sent with. */
export interface ModelChoice {
  ref: string;
  label: string;
  source: "host" | "own";
  enabled: boolean;
}

export interface Models {
  models: ModelChoice[];
  default_ref: string;
}

const MODEL: Shape = {
  ref: "string",
  label: "string",
  source: ["host", "own"],
  enabled: "boolean",
};

const models = (value: unknown): Models => {
  const found = shaped<Models>(value, { default_ref: "string", models: "array" }, "model list");
  shaped<ModelChoice[]>(found.models, MODEL, "model");
  return found;
};

export const fetchModels = (): Promise<Models> => get<unknown>("/models").then(models);

/** 409 when it is the last one on: something must answer. */
export const toggleModel = (ref: string, enabled: boolean): Promise<Models> =>
  request<unknown>("PUT", `/models/prefs/${encodeURIComponent(ref)}`, { enabled }).then(models);

export const setDefaultModel = (ref: string): Promise<Models> =>
  request<unknown>("PUT", "/models/default", { ref }).then(models);

/** One of this person's own models. Keys never come back: only their last four characters. */
export interface OwnModel {
  id: number;
  ref: string;
  label: string;
  model_id: string;
  api_base: string;
  key_hints: string[];
}

/** What the form sends. `keys` absent on an edit keeps the stored ones. */
export interface OwnModelInput {
  label: string;
  model_id: string;
  api_base: string;
  keys?: string[];
}

export interface OwnPresets {
  presets: Record<string, string>;
  max_models: number;
  max_keys: number;
}

export interface KeyCheck {
  hint: string;
  ok: boolean;
  kind: "quota" | "auth" | "not_found" | "unreachable" | "provider" | null;
  detail: string;
}

export interface KeyCheckState {
  job_id: string;
  status: "running" | "done";
  checks: KeyCheck[];
}

const OWN_MODEL: Shape = {
  id: "number",
  ref: "string",
  label: "string",
  model_id: "string",
  api_base: "string",
  key_hints: "array",
};
const KEY_CHECK_STATE: Shape = { job_id: "string", status: ["running", "done"], checks: "array" };

export const fetchOwnModels = (): Promise<OwnModel[]> =>
  get<unknown>("/models/own").then((v) => shaped<OwnModel[]>(v, OWN_MODEL, "own model"));

export const fetchOwnPresets = (): Promise<OwnPresets> => get<OwnPresets>("/models/own/presets");

export const addOwnModel = (input: OwnModelInput): Promise<OwnModel> =>
  post<unknown>("/models/own", input).then((v) => shaped<OwnModel>(v, OWN_MODEL, "own model"));

export const editOwnModel = (id: number, input: OwnModelInput): Promise<OwnModel> =>
  request<unknown>("PATCH", `/models/own/${id}`, input).then((v) =>
    shaped<OwnModel>(v, OWN_MODEL, "own model"),
  );

export const deleteOwnModel = (id: number): Promise<void> => del(`/models/own/${id}`);

export const deleteOwnKey = (id: number, index: number): Promise<OwnModel> =>
  request<unknown>("DELETE", `/models/own/${id}/keys/${index}`).then((v) =>
    shaped<OwnModel>(v, OWN_MODEL, "own model"),
  );

export const startKeyCheck = (id: number): Promise<KeyCheckState> =>
  post<unknown>(`/models/own/${id}/test`).then((v) =>
    shaped<KeyCheckState>(v, KEY_CHECK_STATE, "key check"),
  );

export const fetchKeyCheck = (jobId: string): Promise<KeyCheckState> =>
  get<unknown>(`/models/own/tests/${jobId}`).then((v) =>
    shaped<KeyCheckState>(v, KEY_CHECK_STATE, "key check"),
  );
