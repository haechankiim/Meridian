import { BacktestRunner } from "./components/BacktestRunner";
import { useBackendHealth } from "./hooks/useBackendHealth";

function App() {
  const { health, isLoading, error, refresh } = useBackendHealth();
  const connectionStatus = isLoading ? "Checking backend" : error ? "Backend offline" : "Backend ready";

  return (
    <div className="app-shell">
      <div className="glow glow-left" />
      <div className="glow glow-right" />

      <header className="hero panel">
        <div className="eyebrow">Meridian Frontend MVP</div>
        <div className="hero-grid">
          <div>
            <h1>Run a backtest, inspect the curve, and keep the browser flow honest.</h1>
            <p className="hero-copy">
              This first screen is intentionally narrow: pick a free provider-backed market,
              run the existing momentum strategy, and read the same metrics the backend just
              proved out live.
            </p>
          </div>

          <aside className="hero-status">
            <div className={`status-pill ${error ? "status-offline" : "status-online"}`}>
              {connectionStatus}
            </div>
            <p className="status-copy">
              {health ? `${health.service} says ${health.status}.` : "The page will keep working once the API is reachable."}
            </p>
            <button className="ghost-button" onClick={() => void refresh()} type="button">
              Recheck API
            </button>
          </aside>
        </div>
      </header>

      <main>
        <BacktestRunner />
      </main>
    </div>
  );
}

export default App;
