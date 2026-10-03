import { useEffect, useState } from "react";

import { getHealth } from "../api.js";

const POLL_MS = 30_000;

/**
 * Polls GET /health. Returns "checking" | "online" | "offline".
 * This reflects API reachability only; language-model availability is
 * reported per request (HTTP 503 LLM_UNAVAILABLE).
 */
export function useServiceHealth() {
  const [state, setState] = useState("checking");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const body = await getHealth();
        if (!cancelled) setState(body?.status === "ok" ? "online" : "offline");
      } catch {
        if (!cancelled) setState("offline");
      }
    }

    check();
    const timer = setInterval(check, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return state;
}
