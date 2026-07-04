import { useEffect, useRef, useState } from "react";

export function useSnapshot() {
  const [snapshot, setSnapshot] = useState(null);
  const [connection, setConnection] = useState("connecting");
  const [error, setError] = useState(null);
  const connectionRef = useRef("connecting");

  useEffect(() => {
    let cancelled = false;

    function updateConnection(nextConnection) {
      connectionRef.current = nextConnection;
      setConnection(nextConnection);
    }

    async function loadInitialSnapshot() {
      try {
        const response = await fetch("/api/snapshot");
        if (!response.ok) {
          throw new Error(`Snapshot failed: ${response.status}`);
        }
        const payload = await response.json();
        if (!cancelled) {
          setSnapshot(payload);
          updateConnection("polling");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          updateConnection("offline");
        }
      }
    }

    loadInitialSnapshot();

    const stream = new EventSource("/api/stream");
    stream.addEventListener("open", () => {
      if (!cancelled) updateConnection("live");
    });
    stream.addEventListener("snapshot", (event) => {
      if (!cancelled) {
        setSnapshot(JSON.parse(event.data));
        updateConnection("live");
        setError(null);
      }
    });
    stream.addEventListener("error", () => {
      if (!cancelled) updateConnection("reconnecting");
    });

    const poll = window.setInterval(async () => {
      if (cancelled || connectionRef.current === "live") return;
      try {
        const response = await fetch("/api/snapshot");
        const payload = await response.json();
        if (!cancelled) setSnapshot(payload);
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    }, 10000);

    return () => {
      cancelled = true;
      stream.close();
      window.clearInterval(poll);
    };
  }, []);

  return { snapshot, connection, error };
}
