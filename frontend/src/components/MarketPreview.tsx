import type { CandleRecord } from "../types/api";

interface MarketPreviewProps {
  symbol: string;
  candles: CandleRecord[];
}

export function MarketPreview({ symbol, candles }: MarketPreviewProps) {
  if (candles.length < 2) {
    return (
      <div className="chart-empty">
        <p>Not enough candles to draw a preview for {symbol} yet.</p>
      </div>
    );
  }

  const width = 760;
  const height = 300;
  const paddingX = 18;
  const topPadding = 16;
  const gap = 2;
  const priceChartHeight = 205;
  const volumeChartHeight = 54;
  const volumeTop = height - volumeChartHeight - 8;

  const lows = candles.map((candle) => candle.low);
  const highs = candles.map((candle) => candle.high);
  const minPrice = Math.min(...lows);
  const maxPrice = Math.max(...highs);
  const priceRange = Math.max(maxPrice - minPrice, 1);
  const volumes = candles.map((candle) => Number(candle.volume ?? 0));
  const maxVolume = Math.max(...volumes, 1);
  const candleWidth = Math.max(((width - paddingX * 2) / candles.length) - gap, 3);

  const candleMarks = candles.map((candle, index) => {
    const x = paddingX + index * (candleWidth + gap) + candleWidth / 2;
    const wickTop = scalePrice(candle.high, minPrice, priceRange, priceChartHeight, topPadding);
    const wickBottom = scalePrice(candle.low, minPrice, priceRange, priceChartHeight, topPadding);
    const bodyTop = scalePrice(Math.max(candle.open, candle.close), minPrice, priceRange, priceChartHeight, topPadding);
    const bodyBottom = scalePrice(Math.min(candle.open, candle.close), minPrice, priceRange, priceChartHeight, topPadding);
    const bodyHeight = Math.max(bodyBottom - bodyTop, 2);
    const color = candle.close >= candle.open ? "#1b7a68" : "#c45c2c";
    const volumeHeight = (Number(candle.volume ?? 0) / maxVolume) * volumeChartHeight;

    return {
      key: `${candle.timestamp}-${index}`,
      x,
      bodyX: x - candleWidth / 2,
      wickTop,
      wickBottom,
      bodyTop,
      bodyHeight,
      color,
      volumeY: volumeTop + (volumeChartHeight - volumeHeight),
      volumeHeight,
    };
  });

  const first = candles[0];
  const last = candles[candles.length - 1];
  const priceMove = (last.close - first.close) / first.close;
  const priceMoveClass = priceMove >= 0 ? "price-up" : "price-down";
  const latestRsi = typeof last.rsi_14 === "number" ? last.rsi_14 : null;

  return (
    <div className="chart-shell">
      <div className="chart-meta">
        <span>{new Date(first.timestamp).toLocaleDateString()}</span>
        <span>{new Date(last.timestamp).toLocaleDateString()}</span>
      </div>

      <svg className="chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${symbol} candlestick preview`}>
        <rect x="0" y={volumeTop - 6} width={width} height="1" fill="rgba(29, 33, 32, 0.08)" />

        {candleMarks.map((mark) => (
          <g key={mark.key}>
            <line
              x1={mark.x}
              y1={mark.wickTop}
              x2={mark.x}
              y2={mark.wickBottom}
              stroke={mark.color}
              strokeWidth="2"
            />
            <rect
              x={mark.bodyX}
              y={mark.bodyTop}
              width={candleWidth}
              height={mark.bodyHeight}
              rx="1.5"
              fill={mark.color}
              opacity="0.9"
            />
            <rect
              x={mark.bodyX}
              y={mark.volumeY}
              width={candleWidth}
              height={Math.max(mark.volumeHeight, 2)}
              rx="1.5"
              fill={mark.color}
              opacity="0.28"
            />
          </g>
        ))}
      </svg>

      <div className="preview-footer">
        <div className="preview-value-block">
          <strong>{formatCurrency(last.close)}</strong>
          <span>Latest close</span>
        </div>
        <div className={`preview-move ${priceMoveClass}`}>
          <strong>{formatSignedPercent(priceMove)}</strong>
          <span>Window move</span>
        </div>
        <div className="preview-value-block">
          <strong>{formatCompactVolume(Number(last.volume ?? 0))}</strong>
          <span>Latest volume</span>
        </div>
        <div className="preview-value-block">
          <strong>{latestRsi !== null ? latestRsi.toFixed(1) : "n/a"}</strong>
          <span>RSI 14</span>
        </div>
      </div>
    </div>
  );
}

function scalePrice(
  value: number,
  minPrice: number,
  priceRange: number,
  priceChartHeight: number,
  topPadding: number,
) {
  return topPadding + ((maxNormalized(value, minPrice, priceRange)) * priceChartHeight);
}

function maxNormalized(value: number, minPrice: number, priceRange: number) {
  return 1 - ((value - minPrice) / priceRange);
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value > 1000 ? 0 : 2,
  }).format(value);
}

function formatSignedPercent(value: number) {
  const percent = (value * 100).toFixed(2);
  return `${value >= 0 ? "+" : ""}${percent}%`;
}

function formatCompactVolume(value: number) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}
