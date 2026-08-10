import { Routes, Route, Navigate } from "react-router-dom";
import DashboardLayout from "./layout/DashboardLayout";
import DashboardPage from "./pages/DashboardPage";
import AgentsPage from "./pages/AgentsPage";
import AlertsPage from "./pages/AlertsPage";
import BaselinesPage from "./pages/BaselinesPage";
import ScansPage from "./pages/ScansPage";
import ReportsPage from "./pages/ReportsPage";
import ReportDetailPage from "./pages/ReportDetailPage";
import ExclusionsPage from "./pages/ExclusionsPage";
import UsersPage from "./pages/UsersPage";
import AuditPage from "./pages/AuditPage";
import SessionsPage from "./pages/SessionsPage";
import SystemHealthPage from "./pages/SystemHealthPage";
import LoginPage from "./pages/LoginPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = localStorage.getItem("fim_token");
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <DashboardLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="baselines" element={<BaselinesPage />} />
        <Route path="scans" element={<ScansPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/:reportId" element={<ReportDetailPage />} />
        <Route path="exclusions" element={<ExclusionsPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="sessions" element={<SessionsPage />} />
        <Route path="system-health" element={<SystemHealthPage />} />
      </Route>
    </Routes>
  );
}
