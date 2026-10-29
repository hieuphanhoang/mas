import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useTheme } from "./theme";
import { ProjectsPage } from "../pages/ProjectsPage";
import { ControlRoomPage } from "../pages/ControlRoomPage";
import { ThreadsPage } from "../pages/ThreadsPage";
import { InboxPage } from "../pages/InboxPage";
import { CapabilitiesPage } from "../pages/CapabilitiesPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Shell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

function Shell() {
  const { theme, toggle } = useTheme();
  return (
    <div className="shell">
      <header className="shell__bar">
        <span className="brand">MAS</span>
        <nav className="nav">
          <NavLink to="/projects">Projects</NavLink>
          <NavLink to="/room">Control room</NavLink>
          <NavLink to="/threads">Threads</NavLink>
          <NavLink to="/inbox">Inbox</NavLink>
          <NavLink to="/capabilities">Harnesses</NavLink>
        </nav>
        <button className="btn btn--ghost" onClick={toggle} aria-label="Toggle theme" title="Toggle theme">
          {theme === "dark" ? "Light" : "Dark"}
        </button>
      </header>
      <main className="shell__body">
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectsPage />} />
          <Route path="/room" element={<ControlRoomPage />} />
          <Route path="/room/:projectId" element={<ControlRoomPage />} />
          <Route path="/threads" element={<ThreadsPage />} />
          <Route path="/threads/:projectId" element={<ThreadsPage />} />
          <Route path="/threads/:projectId/:logId/:threadId" element={<ThreadsPage />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/capabilities" element={<CapabilitiesPage />} />
        </Routes>
      </main>
    </div>
  );
}
