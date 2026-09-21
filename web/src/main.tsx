/**
 * Six routes, one gate.
 *
 * `basename="/app"` because that is where the API mounts the build; the dev server uses
 * the same base, so a path written here means the same thing in both.
 *
 * `/home`, `/login` and `/register` are open; `/reports` and `/dashboard` are behind
 * `Gate`, which waits for the one `me()` call before deciding — see `auth.tsx` for why
 * "not asked yet" is not "nobody".
 *
 * `/` is neither: signed in it is the app, signed out it is the same page `/home` shows.
 * Someone arriving at the front door should be told what this is, not handed a password
 * field. A deep link still goes through the login form, because it has somewhere to
 * return to afterwards and the front page does not.
 *
 * An unknown path goes to `/home` rather than `/`: a stranger following a stale link
 * should land on the page that says what this is, not be bounced through a login form.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Ask } from "./pages/Ask";
import { Dashboard } from "./pages/Dashboard";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { Reports } from "./pages/Reports";
import { ThreadsProvider } from "./threads";
import "./styles.css";

function Gate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();

  if (user === undefined) return <div className="waiting" />;
  if (user === null) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}

const guarded = (page: React.ReactNode): React.ReactNode => <Gate>{page}</Gate>;

/** The front door, which is two doors. A stranger at `/app` is asked what this is, not
 *  asked for a password — the login form is what `Home` links to, not what greets it. */
function Front() {
  const { user } = useAuth();
  if (user === undefined) return <div className="waiting" />;
  return user ? <Ask /> : <Home />;
}

function Root() {
  return (
    <BrowserRouter basename="/app">
      <AuthProvider>
        <ThreadsProvider>
          <Routes>
            <Route path="/home" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/" element={<Front />} />
            <Route path="/reports" element={guarded(<Reports />)} />
            <Route path="/dashboard" element={guarded(<Dashboard />)} />
            <Route path="*" element={<Navigate to="/home" replace />} />
          </Routes>
        </ThreadsProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("no #root");

createRoot(root).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
