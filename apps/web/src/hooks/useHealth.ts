import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { HealthResponse } from '../types/core-ir';

export type HealthStatus = 'loading' | 'online' | 'offline';

export interface HealthState {
  status: HealthStatus;
  data: HealthResponse | null;
  refresh: () => void;
}

const POLL_INTERVAL_MS = 15_000;
const RETRY_INTERVAL_MS = 3_000;

export function useHealth(): HealthState {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [status, setStatus] = useState<HealthStatus>('loading');
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    let timer = 0;

    const poll = async () => {
      try {
        const response = await api.health(controller.signal);
        if (!cancelled) {
          setData(response);
          setStatus('online');
          timer = window.setTimeout(poll, POLL_INTERVAL_MS);
        }
      } catch {
        if (!cancelled) {
          setData(null);
          setStatus('offline');
          timer = window.setTimeout(poll, RETRY_INTERVAL_MS);
        }
      }
    };

    void poll();

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [nonce]);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  return { status, data, refresh };
}
