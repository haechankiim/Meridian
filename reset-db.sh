#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$ROOT_DIR/backend/.venv311/bin/python"

require_file() {
  local file_path="$1"
  local hint="$2"

  if [[ ! -e "$file_path" ]]; then
    echo "$hint"
    exit 1
  fi
}

confirm_reset() {
  if [[ "${1:-}" == "--yes" ]]; then
    return 0
  fi

  echo "This will delete all Meridian market data and saved backtests from PostgreSQL."
  echo "Tables cleared: assets, candles, features, backtests, backtest_results, trades."
  read -r -p "Type RESET to continue: " response

  if [[ "$response" != "RESET" ]]; then
    echo "Reset cancelled."
    exit 0
  fi
}

require_file "$PYTHON_BIN" "Backend venv not found at backend/.venv311. Create it first."
confirm_reset "${1:-}"

cd "$ROOT_DIR"
"$PYTHON_BIN" - <<'PY'
import asyncio

from sqlalchemy import text

from backend.app.database import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                TRUNCATE TABLE
                    trades,
                    backtest_results,
                    backtests,
                    features,
                    candles,
                    assets
                RESTART IDENTITY CASCADE
                """
            )
        )

    print("Meridian DB cleared.")


asyncio.run(main())
PY
