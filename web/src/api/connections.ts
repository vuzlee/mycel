/** Accounts a person connects, one per plugin. */

import { del, get } from "./client";

/** One plugin as this person sees it. `configured` is about the deployment, not the person:
 *  with no OAuth client the panel says so rather than offering a button that errors. */
export interface PluginStatus {
  key: string;
  name: string;
  offers: string;
  configured: boolean;
  who: string | null;
  since: string | null;
  note: string | null;
}

export const fetchPlugins = (): Promise<PluginStatus[]> => get<PluginStatus[]>("/connections");

/** A navigation, not a call: consent happens on the provider's own screen, and the server
 *  comes back to `/app/home` with the outcome in the query string. */
export function connectPlugin(key: string): void {
  window.location.href = `/connections/${key}/start`;
}

export const disconnectPlugin = (key: string): Promise<void> => del(`/connections/${key}`);
