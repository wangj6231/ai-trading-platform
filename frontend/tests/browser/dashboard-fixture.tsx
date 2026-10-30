// TEST ONLY. Mount real dashboard/client/UI; market responses are isolated browser fixtures.
import { createRoot } from "react-dom/client";
import { TradingDashboard } from "@/components/trading-dashboard";
import "@/app/globals.css";

createRoot(document.getElementById("dashboard")!).render(<TradingDashboard />);
