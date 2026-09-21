/**
 * Who you are signed in as, and everything you can do about it.
 *
 * One component, used by the rail and by the home page, so the same four items are under
 * the same address on every page. Two copies would drift, and an account menu that is
 * elsewhere on one page is a menu people stop trusting.
 *
 * Everything it opens is a dialog over the page rather than a route: these are things
 * you check and dismiss, and a page for each would drop the run you were watching.
 *
 * Signing out asks first: the button sits under the cursor's resting place, and an
 * accidental sign-out costs a password to undo.
 */

import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth";
import { useThreads } from "../threads";
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

export function Account({ where }: Props) {
  const { user, signOut } = useAuth();
  const { threads } = useThreads();
  const [open, setOpen] = useState(false);
  const [panel, setPanel] = useState<Panel | null>(null);
  const box = useRef<HTMLDivElement>(null);

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

          <button
            className="out"
            role="menuitem"
            onClick={() => show("leaving")}
          >
            <SignOut />
            Sign out
          </button>
        </div>
      )}

      {panel === "profile" && (
        <Modal title="Profile" lede="The account these runs are kept under." onClose={shut}>
          <ProfilePanel threads={threads} />
        </Modal>
      )}

      {panel === "settings" && (
        <Modal title="Settings" lede="How this app looks on this machine." onClose={shut}>
          <SettingsPanel />
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
