"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import type { RuntimeSelection } from "@/lib/product/contracts";
import { ProductProvider, useProduct } from "./product-provider";

const links = [["/", "Dashboard"], ["/paper-trading", "Paper Trading"], ["/positions", "Positions"], ["/orders", "Orders"], ["/journal", "Journal"], ["/analytics", "Analytics"]] as const;
function Navigation() {
  const pathname = usePathname();
  const { snapshot } = useProduct();
  return <header className="product-nav">
    <div className="product-brand"><Link href="/">AXIOM<span>Trading workspace</span></Link><span className="product-account-badge">{snapshot.account.data?.environment ?? "ACCOUNT LOADING"} · {snapshot.source}</span></div>
    <nav aria-label="Product navigation">{links.map(([href, label]) => <Link key={href} href={href} aria-current={(href === "/" ? pathname === "/" : pathname.startsWith(href)) ? "page" : undefined}>{label}</Link>)}</nav>
  </header>;
}
export function ProductShell({ children, selection }: { children: ReactNode; selection?: RuntimeSelection }) { return <ProductProvider selection={selection}><Navigation />{children}</ProductProvider>; }
