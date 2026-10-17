/** An outward link as a chip: what it opens, by name, not the url it lives at. */

import { Calendar, Globe } from "./icons";

/** What a bare url is called on screen: a calendar event by name, else its domain. */
function named(url: URL): { label: string; icon: React.ReactNode } {
  const host = url.hostname.replace(/^www\./, "");
  if (host.startsWith("calendar.") || url.pathname.startsWith("/calendar")) {
    return { label: "Open in calendar", icon: <Calendar size={12} /> };
  }
  return { label: host, icon: <Globe size={12} /> };
}

export function LinkChip({ href, children }: { href?: string; children?: React.ReactNode }) {
  let url: URL | null = null;
  try {
    url = href ? new URL(href) : null;
  } catch {
    url = null;
  }
  if (!url || !/^https?:$/.test(url.protocol)) return <>{children}</>;

  const { label, icon } = named(url);
  // A bare url in the text arrives as its own children: name it instead of printing it.
  const text = typeof children === "string" && children.startsWith("http") ? label : children;
  return (
    <a className="link-chip" href={url.href} target="_blank" rel="noreferrer" title={url.href}>
      {icon}
      <span>{text}</span>
    </a>
  );
}
