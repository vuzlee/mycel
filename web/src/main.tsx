/** Routes. `/home`, `/login`, `/register` are open; `/` is Ask signed in, Home signed out. */

import { QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { lazy, StrictMode, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Waiting } from "./components/Waiting";
import { AuthProvider, useAuth } from "./context/auth";
import { ConversationsProvider } from "./context/ConversationsContext";
import { queryClient } from "./lib/queryClient";
import "./styles/index.css";

const Ask = lazy(() => import("./pages/Ask").then((m) => ({ default: m.Ask })));
const Dashboard = lazy(() => import("./pages/dashboard"));
const Home = lazy(() => import("./pages/Home").then((m) => ({ default: m.Home })));
const Forgot = lazy(() => import("./pages/Forgot").then((m) => ({ default: m.Forgot })));
const Login = lazy(() => import("./pages/Login").then((m) => ({ default: m.Login })));
const Register = lazy(() => import("./pages/Register").then((m) => ({ default: m.Register })));
const Reset = lazy(() => import("./pages/Reset").then((m) => ({ default: m.Reset })));

/** The front door, which is two doors. A stranger at `/app` is asked what this is, not
 *  asked for a password — the login form is what `Home` links to, not what greets it. */
function Front() {
  const { user } = useAuth();
  if (user === undefined) return <Waiting />;
  return user ? <Ask /> : <Home />;
}

/** The board is the one page left that is nobody's business signed out: it is a team's
 *  own tracked work, not a description of the product. A stranger is sent to the login
 *  form rather than to `/home`, because unlike the front door this link has somewhere to
 *  come back to. */
function Board() {
  const { user } = useAuth();
  const { pathname, search } = useLocation();
  if (user === undefined) return <Waiting />;
  if (user) return <Dashboard />;
  return <Navigate to="/login" replace state={{ from: pathname + search }} />;
}

function Root() {
  return (
    <BrowserRouter basename="/app">
      <AuthProvider>
        <ConversationsProvider>
          <Suspense fallback={<Waiting />}>
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
          </Suspense>
        </ConversationsProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("no #root");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <Root />
    </QueryClientProvider>
  </StrictMode>,
);
