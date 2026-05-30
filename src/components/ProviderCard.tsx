interface ProviderResult {
  id: string;
  name: string;
  available: boolean;
  error?: string;
  data?: any;
  updatedAt: number;
}

interface ProviderCardProps {
  result: ProviderResult;
}

function statusColor(result: ProviderResult): string {
  if (result.error || !result.available) return '#e74c3c';
  if (!result.data) return '#888';
  if (result.data.type === 'plan_usage') {
    const minPct = Math.min(...(result.data.models?.map((m: any) => m.remainingPercent) ?? [100]));
    if (minPct < 10) return '#e74c3c';
    if (minPct < 20) return '#f39c12';
  }
  return '#2ecc71';
}

function BalanceView({ data }: { data: any }) {
  const symbol = data.currency === 'CNY' ? '¥' : data.currency === 'USD' ? '$' : data.currency + ' ';
  return (
    <div style={{ padding: '8px 0' }}>
      <div style={{ fontSize: '28px', fontWeight: 600, color: '#fff' }}>{symbol}{data.balance}</div>
    </div>
  );
}

function PlanUsageView({ data }: { data: any }) {
  const models = data.models ?? [];
  if (models.length === 0) return <div style={{ color: '#888', padding: '8px 0', fontSize: '13px' }}>无数据</div>;
  return (
    <div style={{ padding: '6px 0' }}>
      {models.map((m: any, i: number) => (
        <div key={i} style={{ marginBottom: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '3px' }}>
            <span style={{ color: '#ddd', fontWeight: 500 }}>{m.label}</span>
            <span style={{ color: '#aaa' }}>{m.remaining} / {m.total}</span>
          </div>
          <div style={{ background: '#2a2a4a', borderRadius: '3px', height: '6px', overflow: 'hidden' }}>
            <div style={{
              width: `${m.remainingPercent}%`, height: '100%',
              background: m.remainingPercent < 10 ? '#e74c3c' : m.remainingPercent < 20 ? '#f39c12' : '#2ecc71',
              borderRadius: '3px', transition: 'width 0.3s ease',
            }} />
          </div>
          <div style={{ fontSize: '11px', color: '#666', marginTop: '2px' }}>重置: {m.resetDisplay}</div>
        </div>
      ))}
    </div>
  );
}

function ErrorView({ result }: { result: ProviderResult }) {
  const isMissingKey = result.error?.includes('API Key not found');
  return (
    <div style={{ padding: '10px 0' }}>
      <div style={{ color: isMissingKey ? '#f39c12' : '#e74c3c', fontSize: '13px', marginBottom: isMissingKey ? '6px' : 0 }}>
        {result.error}
      </div>
      {isMissingKey && (
        <div style={{
          background: '#111122', padding: '6px 8px', borderRadius: '4px',
          fontSize: '11px', color: '#888', fontFamily: 'monospace', wordBreak: 'break-all',
        }}>
          security add-generic-password -s "{result.id.toUpperCase()}_API_KEY" -w "your-key"
        </div>
      )}
    </div>
  );
}

export function ProviderCard({ result }: ProviderCardProps) {
  const color = statusColor(result);
  return (
    <div style={{ background: '#16162a', borderRadius: '8px', padding: '12px 14px', border: '1px solid #2a2a4a' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: color, marginRight: '8px', flexShrink: 0, display: 'inline-block' }} />
        <span style={{ fontWeight: 600, fontSize: '14px', color: '#eee' }}>{result.name}</span>
      </div>
      {!result.available || result.error ? (
        <ErrorView result={result} />
      ) : result.data?.type === 'balance' ? (
        <BalanceView data={result.data} />
      ) : result.data?.type === 'plan_usage' ? (
        <PlanUsageView data={result.data} />
      ) : (
        <div style={{ color: '#888', padding: '8px 0', fontSize: '13px' }}>等待数据...</div>
      )}
    </div>
  );
}
