import { useState, useEffect } from 'react';
import { ProviderCard } from './components/ProviderCard';
import { StatusBar } from './components/StatusBar';

interface ProviderResult {
  id: string;
  name: string;
  available: boolean;
  error?: string;
  data?: any;
  updatedAt: number;
}

declare global {
  interface Window {
    electronAPI: {
      getUsage: () => Promise<ProviderResult[]>;
      refreshNow: () => Promise<ProviderResult[]>;
      onUsageUpdate: (cb: (data: ProviderResult[]) => void) => () => void;
    };
  }
}

export default function App() {
  const [results, setResults] = useState<ProviderResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<number>(0);

  useEffect(() => {
    // Initial fetch
    window.electronAPI.getUsage().then((data) => {
      if (data.length > 0) {
        setResults(data);
        setLastUpdate(Date.now());
      }
      setLoading(false);
    });

    // Subscribe to live updates
    const unsub = window.electronAPI.onUsageUpdate((data) => {
      setResults(data);
      setLastUpdate(Date.now());
      setLoading(false);
    });

    return unsub;
  }, []);

  const handleRefresh = async () => {
    setLoading(true);
    const data = await window.electronAPI.refreshNow();
    setResults(data);
    setLastUpdate(Date.now());
    setLoading(false);
  };

  return (
    <div style={{ padding: '12px 16px', minHeight: '100vh' }}>
      <StatusBar
        lastUpdate={lastUpdate}
        loading={loading}
        onRefresh={handleRefresh}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px' }}>
        {results.length === 0 && !loading && (
          <div style={{ textAlign: 'center', color: '#888', padding: '40px 0' }}>
            No providers configured
          </div>
        )}
        {results.map((r) => (
          <ProviderCard key={r.id} result={r} />
        ))}
      </div>
    </div>
  );
}
