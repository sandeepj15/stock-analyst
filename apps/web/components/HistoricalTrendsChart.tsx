"use client";

import { useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ComposedChart,
  Bar,
  Cell,
  Line
} from "recharts";

interface Props {
  data: Record<string, Record<string, Record<string, string>>> | null;
}

export default function HistoricalTrendsChart({ data }: Props) {
  const chartData = useMemo(() => {
    if (!data) return [];
    
    // We want to extract Sales, Net Profit, and Operating Cash Flow over years
    // from profit-loss and cash-flow sections
    const pl = data["profit-loss"];
    const cf = data["cash-flow"];
    
    if (!pl) return [];
    
    // Find Sales and Net Profit rows
    // Screener keys are sometimes "Sales", "Net Profit"
    let salesKey = Object.keys(pl).find(k => k.includes("Sales") || k.includes("Revenue"));
    let profitKey = Object.keys(pl).find(k => k.includes("Net Profit"));
    let ocfKey = cf ? Object.keys(cf).find(k => k.includes("Operating Activity") || k.includes("CFO")) : null;
    
    if (!salesKey || !profitKey) return [];
    
    // The keys inside these are the periods e.g. "Mar 2015", "Mar 2016"
    let periods = Object.keys(pl[salesKey]).filter(k => k.match(/^[A-Z][a-z]{2} 20\d{2}$/));
    
    // Postgres JSONB strips insertion order, so we must sort them chronologically
    const parseDate = (d: string) => {
      const [month, year] = d.split(" ");
      const months = { Jan:0, Feb:1, Mar:2, Apr:3, May:4, Jun:5, Jul:6, Aug:7, Sep:8, Oct:9, Nov:10, Dec:11 };
      return new Date(parseInt(year), months[month as keyof typeof months] || 0).getTime();
    };
    periods.sort((a, b) => parseDate(a) - parseDate(b));
    
    const parsedData = periods.map(period => {
      const parseValue = (valStr: string | undefined) => {
        if (!valStr) return 0;
        return parseFloat(valStr.replace(/,/g, "")) || 0;
      };
      
      return {
        period,
        Sales: parseValue(pl[salesKey!][period]),
        "Net Profit": parseValue(pl[profitKey!][period]),
        "Operating Cash Flow": ocfKey ? parseValue(cf![ocfKey][period]) : 0,
      };
    });
    
    return parsedData;
  }, [data]);

  if (!chartData || chartData.length === 0) {
    return <div className="notice">Historical trend data unavailable.</div>;
  }

  return (
    <div className="panel">
      <h2>Long-Term Health Trends</h2>
      <p style={{ color: "var(--text-secondary)", marginBottom: "1rem" }}>
        Comparing Revenue against actual Net Profit and Operating Cash Flow to detect quality of earnings over a 10+ year horizon.
      </p>
      
      <div style={{ width: "100%", height: 350 }}>
        <ResponsiveContainer>
          <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
            <XAxis dataKey="period" stroke="var(--text-secondary)" tick={{ fontSize: 12 }} />
            <YAxis stroke="var(--text-secondary)" tick={{ fontSize: 12 }} tickFormatter={(val) => `${val / 1000}k`} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-secondary)",
                borderColor: "var(--border-color)",
                borderRadius: 4
              }}
            />
            <Legend />
            <Area type="monotone" dataKey="Sales" fill="#3b82f6" stroke="#2563eb" fillOpacity={0.2} />
            <Bar dataKey="Net Profit" maxBarSize={40}>
              {chartData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry["Net Profit"] < 0 ? "#ef4444" : "#10b981"} />
              ))}
            </Bar>
            <Line type="monotone" dataKey="Operating Cash Flow" stroke="#f59e0b" strokeWidth={3} dot={{ r: 4 }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
