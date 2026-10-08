/** Routes. `/home`, `/login`, `/register` are open; `/` is Ask signed in, Home signed out. */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/auth";
import { Ask } from "./pages/Ask";
import Dashboard from "./pages/dashboard";
import { Home } from "./pages/Home";
import { Forgot } from "./pages/Forgot";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { Reset } from "./pages/Reset";
import { ConversationsProvider } from "./context/ConversationsContext";
import "./styles/index.css";

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
        <ConversationsProvider>
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
        </ConversationsProvider>
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
