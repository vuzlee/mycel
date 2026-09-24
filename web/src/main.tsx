/**
 * Seven routes, and no gate left.
 *
 * `basename="/app"` because that is where the API mounts the build; the dev server uses
 * the same base, so a path written here means the same thing in both.
 *
 * `/home`, `/login` and `/register` are open. Batch 027 deleted `/reports` and
 * `/dashboard` — the only two guarded routes — so `Gate` went with them. Batch 040 brings
 * `/dashboard` back and keeps `Gate` gone: `Board` is four lines waiting on the same one
 * `me()` call `Front` already waits on, and a shared wrapper for two callers that differ
 * in where they send a stranger is a component whose whole body is a prop.
 *
 * `/` is the app: signed in it is Ask, signed out it is the same page `/home` shows.
 * Someone arriving at the front door should be told what this is, not handed a password
 * field. A deep link still goes through the login form, because it has somewhere to
 * return to afterwards and the front page does not.
 *
 * An unknown path goes to `/home` rather than `/`: a stranger following a stale link
 * should land on the page that says what this is, not be bounced through a login form.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Ask } from "./pages/Ask";
import { Dashboard } from "./pages/Dashboard";
import { Home } from "./pages/Home";
import { Forgot } from "./pages/Forgot";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { Reset } from "./pages/Reset";
import { ThreadsProvider } from "./threads";
import "./styles.css";

/** The front door, which is two doors. A stranger at `/app` is asked what this is, not
 *  asked for a password — the login form is what `Home` links to, not what greets it. */
function Front() {
  const { user } = useAuth();
  if (user === undefined) return <div className="waiting" />;
  return user ? <Ask /> : <Home />;
}

/** The board is the one page left that is nobody's business signed out: it is a team's
 *  own tracked work, not a description of the product. A stranger is sent to the login
 *  form rather than to `/home`, because unlike the front door this link has somewhere to
 *  come back to. */
function Board() {
  const { user } = useAuth();
  if (user === undefined) return <div className="waiting" />;
  return user ? <Dashboard /> : <Navigate to="/login" replace />;
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
            <Route path="/forgot" element={<Forgot />} />
            <Route path="/reset" element={<Reset />} />
            <Route path="/dashboard" element={<Board />} />
            <Route path="/" element={<Front />} />
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
