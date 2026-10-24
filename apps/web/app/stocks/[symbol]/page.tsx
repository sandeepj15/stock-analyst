import StockPageClient from "../../../components/StockPageClient";
import { getPrice } from "../../../lib/api";

export default async function StockPage({ params }: { params: { symbol: string } }) {
  const symbol = params.symbol.toUpperCase();
  const price = await getPrice(symbol, "6M").catch(() => null);
  return <StockPageClient symbol={symbol} initialPrice={price} />;
}

