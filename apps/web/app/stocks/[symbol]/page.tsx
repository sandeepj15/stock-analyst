import StockPageClient from "../../../components/StockPageClient";
import { getPrice, getTechnicals } from "../../../lib/api";

export default async function StockPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol: rawSymbol } = await params;
  const symbol = rawSymbol.toUpperCase();
  const [price, technicals] = await Promise.all([
    getPrice(symbol, "6M").catch(() => null),
    getTechnicals(symbol, "6M").catch(() => null),
  ]);
  return (
    <StockPageClient
      symbol={symbol}
      initialPrice={price}
      initialTechnicals={technicals}
    />
  );
}

