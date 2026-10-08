import StockPageClient from "../../../components/StockPageClient";

export default function StockPage({ params }: { params: { symbol: string } }) {
  return <StockPageClient symbol={params.symbol.toUpperCase()} />;
}
