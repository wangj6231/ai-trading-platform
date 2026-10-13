import { TradeDetailPage } from "@/components/product/journal-pages";
export default async function Page({ params }: { params: Promise<{ tradeId: string }> }) { const { tradeId } = await params; return <TradeDetailPage tradeId={tradeId} />; }
