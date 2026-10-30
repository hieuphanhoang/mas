import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useTheme } from "./theme";
import { ProjectsPage } from "../pages/ProjectsPage";
import { AgentsPage } from "../pages/AgentsPage";
import { ThreadsPage } from "../pages/ThreadsPage";
import { InboxPage } from "../pages/InboxPage";
import { CapabilitiesPage } from "../pages/CapabilitiesPage";
import { Glyph, Icon } from "../components/icons";

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
      <aside className="rail">
        <div className="brand">
          <span className="brand__rose"><Glyph harness="owner" size={20} /></span>
          <span className="brand__mark">MAS</span>
        </div>
        <nav className="nav" aria-label="Main">
          <NavLink to="/projects"><Icon name="projects" />Projects</NavLink>
          <NavLink to="/agents"><Icon name="agents" />Agents</NavLink>
          <NavLink to="/threads"><Icon name="threads" />Threads</NavLink>
          <NavLink to="/inbox"><Icon name="inbox" />Inbox</NavLink>
          <NavLink to="/capabilities"><Icon name="harness" />Harnesses</NavLink>
        </nav>
        <div className="rail__foot">
          <button className="btn btn--ghost btn--icon" onClick={toggle} aria-label="Toggle theme" title={theme === "dark" ? "Day chart" : "Night chart"}>
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
        </div>
      </aside>
      <main className="shell__main shell__body">
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectsPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/agents/:projectId" element={<AgentsPage />} />
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
