import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { getToken } from "./api";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import SessionDetailPage from "./pages/SessionDetailPage";
import LexiconPage from "./pages/LexiconPage";
import AccountPage from "./pages/AccountPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="sessions/:id" element={<SessionDetailPage />} />
          <Route path="lexicon" element={<LexiconPage />} />
          <Route path="account" element={<AccountPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
