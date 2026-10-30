import type { Metadata } from "next";
import "./globals.css";
import "./product.css";
import { ProductShell } from "@/components/product/product-shell";
import { connection } from "next/server";
import { paperServerConfig } from "@/lib/product/server-runtime";

export const metadata: Metadata = {
  title: "Axiom Market Intelligence",
  description: "Binance Spot market dashboard with server-owned closed 15m strategy evidence",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  await connection();
  return (
    <html lang="en">
      <body><ProductShell selection={paperServerConfig().public}>{children}</ProductShell></body>
    </html>
  );
}
