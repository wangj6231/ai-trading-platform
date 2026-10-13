"use client";
import { useRouter } from "next/navigation";
import { TradingDashboard } from "@/components/trading-dashboard";
import { useProduct } from "./product-provider";
export function DashboardProduct() { const router = useRouter(); const { openPlan } = useProduct(); return <TradingDashboard onPaperTrade={(plan) => { openPlan(plan); router.push("/paper-trading"); }} />; }
