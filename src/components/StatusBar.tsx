import { useState, useEffect } from 'react';

interface StatusBarProps {
  lastUpdate: number;
  loading: boolean;
  onRefresh: () => void;
}

function relativeTime(ts: number): string {
  if (!ts) return '—';
  const sec = Math.floor((Date.now() - ts) / 1000);
  if (sec < 5) return '刚刚';
  if (sec < 60) return `${sec}s 前`;
  const min = Math.floor(sec / 60);
  return `${min}m 前`;
}

export function StatusBar({ lastUpdate, loading, onRefresh }: StatusBarProps) {
  const [tick, setTick] = useState(0);

  // Re-render every 10s to keep relative time fresh
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 10_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '4px 0',
      borderBottom: '1px solid #2a2a4a',
      fontSize: '12px',
      color: '#888',
    }}>
      <span>Token Eye · {relativeTime(lastUpdate)}{tick >= 0 ? '' : ''}</span>
      <button
        onClick={onRefresh}
        disabled={loading}
        style={{
          background: 'none',
          border: '1px solid #3a3a5a',
          borderRadius: '4px',
          color: '#aaa',
          cursor: loading ? 'wait' : 'pointer',
          padding: '2px 8px',
          fontSize: '11px',
          opacity: loading ? 0.5 : 1,
        }}
      >
        {loading ? '...' : '↻ 刷新'}
      </button>
    </div>
  );
}
