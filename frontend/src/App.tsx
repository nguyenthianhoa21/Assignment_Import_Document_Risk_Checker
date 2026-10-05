import { Route, Routes } from "react-router-dom";
import Navbar from "./components/common/Navbar";
import DashboardPage from "./pages/DashboardPage";
import UploadPage from "./pages/UploadPage";
import ShipmentDetailPage from "./pages/ShipmentDetailPage";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/shipments/:id" element={<ShipmentDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
