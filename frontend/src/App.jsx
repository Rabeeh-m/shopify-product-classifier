import { Routes, Route, Navigate } from "react-router-dom";
import Navbar from "./components/Navbar";
import Footer from "./components/Footer";
import UploadPage from "./pages/UploadPage";
import ReviewPage from "./pages/ReviewPage";
import ClassifiedProducts from "./pages/ClassifiedProducts";
import ProductDetailPage from "./pages/ProductDetailPage";

export default function App() {
  return (
    <div className="app-shell">
      <Navbar />
      <main className="app">
        <Routes>
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/products" element={<ClassifiedProducts />} />
          <Route path="/products/:id" element={<ProductDetailPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="*" element={<Navigate to="/upload" replace />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}
