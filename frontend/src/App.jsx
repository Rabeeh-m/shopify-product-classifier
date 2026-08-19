import { Routes, Route, Navigate, Link } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import ReviewPage from "./pages/ReviewPage";
import ReviewDetail from "./pages/ReviewDetail";

function NavBar() {
  return (
    <nav>
      <Link to="/upload">Upload</Link>
      <Link to="/review">Review Queue</Link>
    </nav>
  );
}

export default function App() {
  return (
    <div className="app">
      <NavBar />
      <Routes>
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/review/:id" element={<ReviewDetail />} />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Routes>
    </div>
  );
}
