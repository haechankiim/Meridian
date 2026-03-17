import { useEffect, useState } from "react";

import { ApiError, fetchHealth } from "../services/api";
import type { HealthResponse } from "../types/api";

export function useBackendHealth() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const nextHealth = await fetchHealth();
      setHealth(nextHealth);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Unknown backend error");
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  return { health, error, isLoading, refresh };
}
