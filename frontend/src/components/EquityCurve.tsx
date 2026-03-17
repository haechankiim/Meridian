import type { EquityCurvePoint } from "../types/api";

interface EquityCurveProps {
  points: EquityCurvePoint[];
}

export function EquityCurve({ points }: EquityCurveProps) {
  if (points.length < 2) {
    return (
      <div className="chart-empty">
        <p>Not enough points to draw a curve yet.</p>
      </div>
    );
  }

  const width = 760;
  const height = 260;
  const padding = 20;
  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);

  const path = points
    .map((point, index) => {
      const x = padding + (index / (points.length - 1)) * (width - padding * 2);
      const y =
        height -
        padding -
        ((point.equity - min) / range) * (height - padding * 2);

      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  const areaPath = `${path} L ${width - padding} ${height - padding} L ${padding} ${height - padding} Z`;

  return (
    <div className="chart-shell">
      <div className="chart-meta">
        <span>{new Date(points[0].timestamp).toLocaleDateString()}</span>
        <span>{new Date(points[points.length - 1].timestamp).toLocaleDateString()}</span>
      </div>
      <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Equity curve">
        <defs>
          <linearGradient id="equity-fill" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#2c8375" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#2c8375" stopOpacity="0.04" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#equity-fill)" />
        <path d={path} fill="none" stroke="#1b7a68" strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <div className="chart-values">
        <strong>{formatCurrency(values[values.length - 1])}</strong>
        <span>Ending equity</span>
      </div>
    </div>
  );
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}
