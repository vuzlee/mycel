/** Who you are signed in as, and everything you can do about it. */

import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { useConversations } from "../context/ConversationsContext";
import { Modal } from "./Modal";
import { HelpPanel, ProfilePanel, SettingsPanel } from "./panels";
import { Chevron, Gear, Person, Question, SignOut } from "./icons";

interface Props {
  /** `rail` is the strip at the foot of the sidebar; `bar` is the pill in a page header. */
  where: "rail" | "bar";
}

/** Which dialog is up, if any. One at a time: they are all the same size and open from
 *  the same menu, so stacking them would only hide one behind another. */
type Panel = "profile" | "settings" | "help" | "leaving";

/** Fired on `window` with a section id as `detail` to open Settings there. */
export const OPEN_SETTINGS = "mycel:open-settings";

export const openSettings = (section: string): void => {
  window.dispatchEvent(new CustomEvent(OPEN_SETTINGS, { detail: section }));
};

export function Account({ where }: Props) {
  const { user, signOut } = useAuth();
  const { conversations } = useConversations();
  const [open, setOpen] = useState(false);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [section, setSection] = useState<string | undefined>(undefined);
  const box = useRef<HTMLDivElement>(null);

  // Anywhere in the app can open Settings at a section, e.g. the model picker's "Add".
  useEffect(() => {
    if (where !== "rail") return;
    const open = (event: Event): void => {
      setSection((event as CustomEvent<string>).detail);
      setPanel("settings");
    };
    window.addEventListener(OPEN_SETTINGS, open);
    return () => window.removeEventListener(OPEN_SETTINGS, open);
  }, [where]);

  // Click away or press Escape. A menu that only closes by its own button is a menu that
  // stays open behind whatever you clicked next.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent): void => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const key = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  if (!user) return null;

  const show = (which: Panel): void => {
    setOpen(false);
    setSection(undefined);
    setPanel(which);
  };

  const shut = (): void => setPanel(null);

  return (
    <div className="account-menu" data-where={where} ref={box}>
      <button
        className="me"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((on) => !on)}
        title={user.email}
      >
        <span className="avatar" aria-hidden>
          {user.email.charAt(0).toUpperCase()}
        </span>
        <span className="named">
          <span className="as">Signed in as</span>
          <span className="addr">{user.email}</span>
        </span>
        <Chevron className="caret" />
      </button>

      {open && (
        <div className="menu" role="menu">
          <div className="head">
            <span className="avatar" aria-hidden>
              {user.email.charAt(0).toUpperCase()}
            </span>
            <span className="named">
              <span className="as">Signed in as</span>
              <span className="addr">{user.email}</span>
            </span>
          </div>

          <button role="menuitem" onClick={() => show("profile")}>
            <Person />
            Profile
          </button>
          <button role="menuitem" onClick={() => show("settings")}>
            <Gear />
            Settings
          </button>
          <button role="menuitem" onClick={() => show("help")}>
            <Question />
            Help
          </button>

          <button className="out" role="menuitem" onClick={() => show("leaving")}>
            <SignOut />
            Sign out
          </button>
        </div>
      )}

      {panel === "profile" && (
        <Modal title="Profile" lede="The account these runs are kept under." onClose={shut}>
          <ProfilePanel conversations={conversations} />
        </Modal>
      )}

      {panel === "settings" && (
        <Modal
          title="Settings"
          lede="How it looks here, and the accounts it reads as you."
          onClose={shut}
          wide
        >
          <SettingsPanel start={section} />
        </Modal>
      )}

      {panel === "help" && (
        <Modal title="Help" lede="What to do first, and what to expect back." onClose={shut}>
          <HelpPanel />
        </Modal>
      )}

      {panel === "leaving" && (
        <div className="scrim asking" data-open onClick={shut}>
          <div className="ask-card" onClick={(event) => event.stopPropagation()}>
            <h2>Sign out?</h2>
            <p>Your runs stay where they are. Signing back in brings them with you.</p>
            <div className="choices">
              <button onClick={shut}>Stay signed in</button>
              <button className="primary" onClick={() => void signOut()}>
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
