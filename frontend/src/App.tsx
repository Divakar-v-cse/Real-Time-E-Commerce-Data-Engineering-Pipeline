import { Link, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Overview from "./pages/Overview";
import Sales from "./pages/Sales";
import Customers from "./pages/Customers";
import Products from "./pages/Products";
import Orders from "./pages/Orders";
import DataQuality from "./pages/DataQuality";
import Pipeline from "./pages/Pipeline";
import System from "./pages/System";
import Reports from "./pages/Reports";

function NotFound() {
  return (
    <div className="card flex flex-col items-start gap-2 p-8">
      <p className="text-sm font-semibold text-slate-800">Page not found</p>
      <p className="text-xs text-slate-500">That route is not part of the dashboard.</p>
      <Link className="btn mt-1" to="/">
        Back to dashboard
      </Link>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="sales" element={<Sales />} />
        <Route path="customers" element={<Customers />} />
        <Route path="products" element={<Products />} />
        <Route path="orders" element={<Orders />} />
        <Route path="data-quality" element={<DataQuality />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="system" element={<System />} />
        <Route path="reports" element={<Reports />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
