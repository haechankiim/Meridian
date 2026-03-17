import { startTransition, useDeferredValue, useEffect, useState, type FormEvent } from "react";

import { EquityCurve } from "./EquityCurve";
import { MarketPreview } from "./MarketPreview";
import { MetricCard } from "./MetricCard";
import {
  ApiError,
  deleteBacktest,
  fetchAssetCatalog,
  fetchBacktestResults,
  fetchCandles,
  fetchRecentBacktests,
  fetchRiskAnalytics,
  runBacktest,
} from "../services/api";
import type {
  AssetCatalogEntry,
  AssetClass,
  BacktestResponse,
  CandleResponse,
  RecentBacktestSummary,
  RiskAnalyticsResponse,
} from "../types/api";

const DEFAULT_SYMBOLS: Record<AssetClass, string> = {
  crypto: "BTCUSDT",
  us_equity: "AAPL",
  forex: "EUR/USD",
  asia_equity: "D05.SI",
};

export function BacktestRunner() {
  const [assetClass, setAssetClass] = useState<AssetClass>("crypto");
  const [symbolsText, setSymbolsText] = useState(DEFAULT_SYMBOLS.crypto);
  const [startDate, setStartDate] = useState("2024-01-01");
  const [endDate, setEndDate] = useState("2024-02-01");
  const [initialCapital, setInitialCapital] = useState("100000");
  const [previewSource, setPreviewSource] = useState<"auto" | "provider" | "database">("auto");
  const [recentFilter, setRecentFilter] = useState<"all" | AssetClass>("all");
  const [recentSearch, setRecentSearch] = useState("");

  const [catalogEntry, setCatalogEntry] = useState<AssetCatalogEntry | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [isCatalogLoading, setIsCatalogLoading] = useState(true);
  const [candlePreview, setCandlePreview] = useState<CandleResponse | null>(null);
  const [candleError, setCandleError] = useState<string | null>(null);
  const [isCandleLoading, setIsCandleLoading] = useState(true);

  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [riskAnalytics, setRiskAnalytics] = useState<RiskAnalyticsResponse | null>(null);
  const [recentRuns, setRecentRuns] = useState<RecentBacktestSummary[]>([]);
  const [savedBacktestId, setSavedBacktestId] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [recentRunsError, setRecentRunsError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isHydratingSavedRun, setIsHydratingSavedRun] = useState(false);
  const [isRecentRunsLoading, setIsRecentRunsLoading] = useState(true);
  const [deletingBacktestId, setDeletingBacktestId] = useState<number | null>(null);
  const deferredPreviewSymbol = useDeferredValue(primarySymbolFromInput(symbolsText, assetClass));
  const deferredRecentSearch = useDeferredValue(recentSearch.trim().toLowerCase());
  const filteredRecentRuns = recentRuns.filter((run) => {
    const matchesFilter = recentFilter === "all" || run.asset_class === recentFilter;
    const haystack = `${run.strategy_name} ${run.symbols.join(" ")} ${run.asset_class ?? ""}`.toLowerCase();
    const matchesSearch = !deferredRecentSearch || haystack.includes(deferredRecentSearch);
    return matchesFilter && matchesSearch;
  });

  useEffect(() => {
    let isCancelled = false;

    async function loadCatalog() {
      setIsCatalogLoading(true);
      setCatalogError(null);

      try {
        const response = await fetchAssetCatalog(assetClass);
        if (!isCancelled) {
          setCatalogEntry(response.assets[0] ?? null);
        }
      } catch (err) {
        if (!isCancelled) {
          if (err instanceof ApiError) {
            setCatalogError(err.detail);
          } else if (err instanceof Error) {
            setCatalogError(err.message);
          } else {
            setCatalogError("Unable to load the asset catalog.");
          }
          setCatalogEntry(null);
        }
      } finally {
        if (!isCancelled) {
          setIsCatalogLoading(false);
        }
      }
    }

    void loadCatalog();

    return () => {
      isCancelled = true;
    };
  }, [assetClass]);

  const loadRecentRuns = async () => {
    setIsRecentRunsLoading(true);
    setRecentRunsError(null);

    try {
      const response = await fetchRecentBacktests(8);
      startTransition(() => {
        setRecentRuns(response.items);
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setRecentRunsError(err.detail);
      } else if (err instanceof Error) {
        setRecentRunsError(err.message);
      } else {
        setRecentRunsError("Unable to load recent backtests.");
      }
    } finally {
      setIsRecentRunsLoading(false);
    }
  };

  useEffect(() => {
    void loadRecentRuns();
  }, []);

  useEffect(() => {
    let isCancelled = false;

    async function loadCandlePreview() {
      if (!deferredPreviewSymbol) {
        setCandlePreview(null);
        setIsCandleLoading(false);
        return;
      }

      setIsCandleLoading(true);
      setCandleError(null);

      try {
        const response = await fetchCandles(
          symbolForApi(deferredPreviewSymbol, assetClass),
          assetClass,
          startDate,
          endDate,
          true,
          previewSource,
        );
        if (!isCancelled) {
          startTransition(() => {
            setCandlePreview(response);
          });
        }
      } catch (err) {
        if (!isCancelled) {
          if (err instanceof ApiError) {
            setCandleError(err.detail);
          } else if (err instanceof Error) {
            setCandleError(err.message);
          } else {
            setCandleError("Unable to load the market preview.");
          }
          setCandlePreview(null);
        }
      } finally {
        if (!isCancelled) {
          setIsCandleLoading(false);
        }
      }
    }

    void loadCandlePreview();

    return () => {
      isCancelled = true;
    };
  }, [assetClass, deferredPreviewSymbol, previewSource, startDate, endDate]);

  const handleAssetClassChange = (nextClass: AssetClass) => {
    setAssetClass(nextClass);
    setSymbolsText(DEFAULT_SYMBOLS[nextClass]);
    setResult(null);
    setRiskAnalytics(null);
    setSavedBacktestId("");
    setSubmitError(null);
    setLookupError(null);
  };

  const hydrateSavedRun = async (backtestId: number, existingResult?: BacktestResponse) => {
    setIsHydratingSavedRun(true);
    setLookupError(null);
    setRiskAnalytics(null);

    try {
      const loadedResult = existingResult ?? (await fetchBacktestResults(backtestId));

      startTransition(() => {
        setResult(loadedResult);
        setSavedBacktestId(String(backtestId));
      });

      try {
        const loadedRisk = await fetchRiskAnalytics(backtestId);
        startTransition(() => {
          setRiskAnalytics(loadedRisk);
        });
      } catch (err) {
        if (err instanceof ApiError) {
          setLookupError(err.detail);
        } else if (err instanceof Error) {
          setLookupError(err.message);
        } else {
          setLookupError("Unable to load the saved run analytics.");
        }
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setLookupError(err.detail);
      } else if (err instanceof Error) {
        setLookupError(err.message);
      } else {
        setLookupError("Unable to load the saved run.");
      }
    } finally {
      setIsHydratingSavedRun(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setSubmitError(null);
    setLookupError(null);

    try {
      const symbols = symbolsText
        ? normalizeSymbolList(symbolsText, assetClass).map(s => symbolForApi(s, assetClass))
        : [];

      const response = await runBacktest({
        asset_class: assetClass,
        symbols,
        strategy: "momentum",
        start_date: startDate,
        end_date: endDate,
        initial_capital: Number(initialCapital || 0),
        interval: "1d",
        save_results: true,
      });

      if (response.backtest_id) {
        await hydrateSavedRun(response.backtest_id, response);
        await loadRecentRuns();
      } else {
        startTransition(() => {
          setResult(response);
          setRiskAnalytics(null);
          setSavedBacktestId("");
        });
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(err.detail);
      } else if (err instanceof Error) {
        setSubmitError(err.message);
      } else {
        setSubmitError("Backtest request failed.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleLoadSavedRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitError(null);

    const parsedId = Number.parseInt(savedBacktestId, 10);
    if (!Number.isFinite(parsedId) || parsedId <= 0) {
      setLookupError("Enter a valid saved backtest id.");
      return;
    }

    await hydrateSavedRun(parsedId);
  };

  const handleDeleteRecentRun = async (backtestId: number) => {
    const confirmed = window.confirm(`Delete saved backtest #${backtestId}? This cannot be undone.`);
    if (!confirmed) {
      return;
    }

    setDeletingBacktestId(backtestId);
    setRecentRunsError(null);

    try {
      await deleteBacktest(backtestId);

      startTransition(() => {
        setRecentRuns((current) => current.filter((run) => run.backtest_id !== backtestId));

        if (result?.backtest_id === backtestId) {
          setResult(null);
          setRiskAnalytics(null);
          setSavedBacktestId("");
        }
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setRecentRunsError(err.detail);
      } else if (err instanceof Error) {
        setRecentRunsError(err.message);
      } else {
        setRecentRunsError("Unable to delete the saved backtest.");
      }
    } finally {
      setDeletingBacktestId(null);
    }
  };

  return (
    <section className="workspace-grid">
      <div className="panel">
        <div className="section-heading">
          <div>
            <div className="eyebrow">Run Backtest</div>
            <h2>Browser-to-backend path</h2>
          </div>
          <span className="status-chip">Momentum only</span>
        </div>

        <form className="runner-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>Asset class</span>
            <select
              value={assetClass}
              onChange={(event) => handleAssetClassChange(event.target.value as AssetClass)}
            >
              <option value="crypto">Crypto</option>
              <option value="us_equity">US equities</option>
              <option value="asia_equity">Asia equities</option>
              <option value="forex">Forex</option>
            </select>
          </label>

          <label className="field field-wide">
            <span>Symbols</span>
            <input
              value={symbolsText}
              onChange={(event) => setSymbolsText(event.target.value)}
              placeholder={assetClass === "forex" ? "EUR/USD or EURUSD,GBPUSD" : "BTCUSDT or AAPL,MSFT"}
            />
          </label>

          <label className="field">
            <span>Preview source</span>
            <select
              value={previewSource}
              onChange={(event) => setPreviewSource(event.target.value as "auto" | "provider" | "database")}
            >
              <option value="auto">Auto</option>
              <option value="provider">Provider</option>
              <option value="database">Database</option>
            </select>
          </label>

          <label className="field">
            <span>Start date</span>
            <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          </label>

          <label className="field">
            <span>End date</span>
            <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          </label>

          <label className="field field-wide">
            <span>Initial capital</span>
            <input
              type="number"
              min="0"
              step="1000"
              value={initialCapital}
              onChange={(event) => setInitialCapital(event.target.value)}
            />
          </label>

          <div className="provider-card field-wide">
            <div className="provider-header">
              <strong>{catalogEntry?.provider ?? "Loading provider..."}</strong>
              <span className={`status-pill ${catalogEntry?.free_tier ? "status-online" : "status-muted"}`}>
                {catalogEntry?.free_tier ? "Free tier" : "Paid / limited"}
              </span>
            </div>
            <p className="provider-note">
              {isCatalogLoading
                ? "Loading provider metadata..."
                : catalogError
                  ? catalogError
                  : catalogEntry?.notes ?? "No provider notes available."}
            </p>
            <div className="suggestions">
              {(catalogEntry?.symbols ?? []).map((symbol) => (
                <button
                  className="chip-button"
                  key={symbol}
                  onClick={() => setSymbolsText(symbol)}
                  type="button"
                >
                  {symbol}
                </button>
              ))}
            </div>
          </div>

          <button className="primary-button field-wide" disabled={isSubmitting} type="submit">
            {isSubmitting ? "Running backtest..." : "Run saved backtest"}
          </button>
        </form>

        {submitError ? <p className="form-error">{submitError}</p> : null}

        <div className="saved-run-box">
          <div className="saved-run-header">
            <strong>Open saved run</strong>
            <span>Load any persisted backtest by id.</span>
          </div>

          <form className="saved-run-controls" onSubmit={handleLoadSavedRun}>
            <input
              inputMode="numeric"
              placeholder="2"
              value={savedBacktestId}
              onChange={(event) => setSavedBacktestId(event.target.value)}
            />
            <button className="ghost-button" disabled={isHydratingSavedRun} type="submit">
              {isHydratingSavedRun ? "Loading..." : "Load run"}
            </button>
          </form>

          {lookupError ? <p className="field-inline-error">{lookupError}</p> : null}
        </div>

        <div className="saved-run-box">
          <div className="saved-run-header">
            <strong>Recent runs</strong>
            <button className="ghost-button compact-button" onClick={() => void loadRecentRuns()} type="button">
              Refresh
            </button>
          </div>

          <div className="recent-run-filters">
            <select value={recentFilter} onChange={(event) => setRecentFilter(event.target.value as "all" | AssetClass)}>
              <option value="all">All assets</option>
              <option value="crypto">Crypto</option>
              <option value="us_equity">US equities</option>
              <option value="asia_equity">Asia equities</option>
              <option value="forex">Forex</option>
            </select>
            <input
              placeholder="Search symbol or strategy"
              value={recentSearch}
              onChange={(event) => setRecentSearch(event.target.value)}
            />
          </div>

          {isRecentRunsLoading ? (
            <p className="saved-run-copy">Loading recent saved runs...</p>
          ) : recentRunsError ? (
            <p className="field-inline-error">{recentRunsError}</p>
          ) : filteredRecentRuns.length ? (
            <div className="recent-run-list">
              {filteredRecentRuns.map((run) => (
                <div className="recent-run-card" key={run.backtest_id}>
                  <button
                    className="recent-run-open"
                    onClick={() => void hydrateSavedRun(run.backtest_id)}
                    type="button"
                  >
                    <div className="recent-run-top">
                      <strong>#{run.backtest_id}</strong>
                      <span>{run.asset_class ?? "unknown"}</span>
                    </div>
                    <div className="recent-run-main">
                      <span>{run.strategy_name}</span>
                      <span>{run.symbols.join(", ")}</span>
                    </div>
                    <div className="recent-run-meta">
                      <span>{run.created_at.slice(0, 10)}</span>
                      <span>{run.total_return !== null ? formatPercent(run.total_return) : "n/a"}</span>
                      <span>{run.max_drawdown !== null ? formatPercent(run.max_drawdown) : "n/a"}</span>
                    </div>
                  </button>
                  <button
                    className="ghost-button compact-button recent-run-delete"
                    disabled={deletingBacktestId === run.backtest_id}
                    onClick={() => void handleDeleteRecentRun(run.backtest_id)}
                    type="button"
                  >
                    {deletingBacktestId === run.backtest_id ? "Deleting..." : "Delete"}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="saved-run-copy">
              {recentRuns.length
                ? "No saved runs matched the current filter."
                : "No persisted backtests yet. Run one and it will show up here."}
            </p>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="section-heading">
          <div>
            <div className="eyebrow">Results</div>
            <h2>Preview & results</h2>
          </div>
          {result?.backtest_id ? <span className="status-chip">Run #{result.backtest_id}</span> : null}
        </div>

        <div className="market-preview-card">
          <div className="saved-run-header">
            <strong>Market preview</strong>
            <span>{deferredPreviewSymbol} · {previewSource}</span>
          </div>

          {isCandleLoading ? (
            <p className="saved-run-copy">Loading candle preview...</p>
          ) : candleError ? (
            <p className="field-inline-error">{candleError}</p>
          ) : candlePreview ? (
            <>
              <MarketPreview symbol={candlePreview.symbol} candles={candlePreview.candles} />
              <div className="preview-stat-grid">
                <MetricCard
                  label="Provider"
                  value={candlePreview.provider}
                  hint={`${candlePreview.interval} · ${candlePreview.source}`}
                />
                <MetricCard
                  label="Candles"
                  value={String(candlePreview.candles.length)}
                  hint="Preview window"
                />
                <MetricCard
                  label="RSI 14"
                  value={formatMaybeNumber(candlePreview.candles[candlePreview.candles.length - 1]?.rsi_14)}
                  hint="Latest feature"
                />
              </div>
            </>
          ) : (
            <p className="saved-run-copy">Choose a symbol to load its candle preview.</p>
          )}
        </div>

        {result ? (
          <>
            <div className="result-banner">
              <strong>{result.persisted ? "Persisted to PostgreSQL" : "In-memory only"}</strong>
              <span>
                {result.strategy_name} on {result.symbols.join(", ")} from {result.start_date} to {result.end_date}
              </span>
            </div>

            <div className="metrics-grid">
              <MetricCard
                label="Total return"
                value={formatPercent(result.metrics.total_return)}
                hint="Portfolio change"
              />
              <MetricCard
                label="Sharpe ratio"
                value={formatNumber(result.metrics.sharpe_ratio)}
                hint="Risk-adjusted return"
              />
              <MetricCard
                label="Max drawdown"
                value={formatPercent(result.metrics.max_drawdown)}
                hint="Worst peak-to-trough"
              />
              <MetricCard
                label="Volatility"
                value={formatPercent(result.metrics.volatility)}
                hint="Annualized"
              />
              <MetricCard
                label="Alpha"
                value={formatPercent(result.metrics.alpha)}
                hint="Versus benchmark"
              />
              <MetricCard
                label="Trades"
                value={String(result.metrics.total_trades)}
                hint="Executed fills"
              />
            </div>

            <EquityCurve points={result.equity_curve} />

            {riskAnalytics ? (
              <div className="risk-panel">
                <div className="trade-header">
                  <strong>Risk lens</strong>
                  <span>{riskAnalytics.risk_regime}</span>
                </div>

                <div className="metrics-grid risk-grid">
                  <MetricCard
                    label="Latest equity"
                    value={formatCurrency(riskAnalytics.latest_equity)}
                    hint="Persisted ending balance"
                  />
                  <MetricCard
                    label="Latest drawdown"
                    value={formatPercent(riskAnalytics.latest_drawdown)}
                    hint="Current underwater level"
                  />
                  <MetricCard
                    label="VaR 95"
                    value={formatPercent(riskAnalytics.var_95)}
                    hint="One-period downside"
                  />
                  <MetricCard
                    label="CVaR 95"
                    value={formatPercent(riskAnalytics.cvar_95)}
                    hint="Average tail loss"
                  />
                  <MetricCard
                    label="Peak equity"
                    value={formatCurrency(riskAnalytics.peak_equity)}
                    hint="Best portfolio value"
                  />
                  <MetricCard
                    label="Beta"
                    value={formatNumber(riskAnalytics.beta)}
                    hint="Market sensitivity"
                  />
                </div>

                {riskAnalytics.monthly_returns.length ? (
                  <div className="month-strip">
                    {riskAnalytics.monthly_returns.map((month) => (
                      <div className="month-card" key={month.month}>
                        <span>{month.month}</span>
                        <strong>{formatPercent(month.return_value)}</strong>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="trade-empty">No monthly return buckets were recorded for this run yet.</p>
                )}
              </div>
            ) : null}

            <div className="trade-panel">
              <div className="trade-header">
                <strong>Trades</strong>
                <span>{result.trades.length ? `${result.trades.length} recorded` : "No trades fired"}</span>
              </div>
              {result.trades.length ? (
                <div className="trade-table">
                  {result.trades.map((trade, index) => (
                    <div className="trade-row" key={`${trade.symbol}-${trade.timestamp}-${index}`}>
                      <span>{trade.symbol}</span>
                      <span>{trade.side}</span>
                      <span>{formatCurrency(trade.price)}</span>
                      <span>{formatNumber(trade.signal_confidence)}</span>
                      <span>{new Date(trade.timestamp).toLocaleDateString()}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="trade-empty">
                  This dataset did not trigger any entries. The API and persistence flow still completed successfully.
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="results-empty">
            <p>Run a backtest to populate metrics, the equity curve, and trade history.</p>
            <span>Preview and backtest flows are available for crypto, US equities, Asia equities, and forex.</span>
          </div>
        )}
      </div>
    </section>
  );
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatNumber(value: number) {
  return value.toFixed(2);
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatMaybeNumber(value: unknown) {
  return typeof value === "number" ? value.toFixed(2) : "n/a";
}

function primarySymbolFromInput(symbolsText: string, assetClass: AssetClass) {
  const [first] = normalizeSymbolList(symbolsText, assetClass);
  return first ?? DEFAULT_SYMBOLS[assetClass];
}

function normalizeSymbolList(symbolsText: string, assetClass: AssetClass) {
  return symbolsText
    .split(",")
    .map((symbol) => normalizeSymbol(symbol, assetClass))
    .filter(Boolean);
}

function normalizeSymbol(symbol: string, assetClass: AssetClass) {
  const cleaned = symbol.trim().toUpperCase();
  if (!cleaned) {
    return "";
  }

  if (assetClass !== "forex") {
    return cleaned;
  }

  const compact = cleaned.replace(/\s+/g, "");
  if (compact.includes("/")) {
    const [base, quote] = compact.split("/", 2);
    return `${base}/${quote}`;
  }

  if (compact.length === 6) {
    return `${compact.slice(0, 3)}/${compact.slice(3)}`;
  }

  return compact;
}

/** Convert symbol to API format - removes slashes for forex to avoid URL path issues */
function symbolForApi(symbol: string, assetClass: AssetClass): string {
  if (assetClass === "forex") {
    return symbol.replace("/", "");
  }
  return symbol;
}
