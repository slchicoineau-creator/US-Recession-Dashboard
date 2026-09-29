/**
 * "Refresh Now" button — triggers POST /api/refresh.
 * Polls /api/refresh/status to track completion, then calls onDone().
 */
import React, { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

export default function RefreshButton({ onDone }) {
  const [running, setRunning] = useState(false);
  const pollRef = useRef(null);

  const handleClick = async () => {
    if (running) return;
    try {
      await api.refresh();
      setRunning(true);
    } catch {
      // already running or error
    }
  };

  useEffect(() => {
    if (!running) return;
    pollRef.current = setInterval(async () => {
      try {
        const { running: still } = await api.refreshStatus();
        if (!still) {
          clearInterval(pollRef.current);
          setRunning(false);
          onDone?.();
        }
      } catch {
        clearInterval(pollRef.current);
        setRunning(false);
      }
    }, 2000);
    return () => clearInterval(pollRef.current);
  }, [running]);

  return (
    <button className="btn btn-primary" onClick={handleClick} disabled={running}>
      {running ? <><span className="spinner" /> Refreshing…</> : "↺ Refresh Now"}
    </button>
  );
}
