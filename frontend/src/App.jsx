import { Routes, Route, Navigate, Link, useNavigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./components/AuthContext";
import LoginPage from "./pages/LoginPage";
import UploadPage from "./pages/UploadPage";
import ReviewPage from "./pages/ReviewPage";
import ReviewDetail from "./pages/ReviewDetail";

function ProtectedRoute({ children }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

function NavBar() {
  const { token, logout } = useAuth();
  const navigate = useNavigate();
  if (!token) return null;

  return (
    <nav>
      <Link to="/upload">Upload</Link>
      <Link to="/review">Review Queue</Link>
      <span className="spacer" />
      <button
        className="logout-btn"
        onClick={() => {
          logout();
          navigate("/login");
        }}
      >
        Logout
      </button>
    </nav>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <div className="app">
        <NavBar />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/upload"
            element={
              <ProtectedRoute>
                <UploadPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/review"
            element={
              <ProtectedRoute>
                <ReviewPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/review/:id"
            element={
              <ProtectedRoute>
                <ReviewDetail />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/upload" replace />} />
        </Routes>
      </div>
    </AuthProvider>
  );
}
