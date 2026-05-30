import fs from 'fs';
import path from 'path';
import { getKey } from './keychain';

interface ApiConfig { url: string; method?: string; authHeader?: string; authPrefix?: string; }
interface ParserConfig {
  type: 'balance' | 'plan_usage' | 'raw';
  fields?: Record<string, string>;
  arrayPath?: string;
  modelLabels?: Record<string, string>;
  showModels?: string[]; // only show these model names
}
interface DisplayConfig { unit?: string; label?: string; }
export interface ProviderConfig { id: string; name: string; keychainService: string; api: ApiConfig; parser: ParserConfig; display: DisplayConfig; }
interface ProvidersFile { providers: ProviderConfig[]; }

export interface BalanceData { type: 'balance'; balance: string; spent: string; currency: string; }
export interface ModelUsage { model: string; label: string; total: number; used: number; remaining: number; remainingPercent: number; resetMs: number; resetDisplay: string; }
export interface PlanUsageData { type: 'plan_usage'; models: ModelUsage[]; }
export interface RawData { type: 'raw'; json: unknown; }
export type ParsedData = BalanceData | PlanUsageData | RawData;
export interface ProviderResult { id: string; name: string; available: boolean; error?: string; data?: ParsedData; updatedAt: number; }

function resolveField(obj: any, fieldPath: string): any {
  if (!obj || !fieldPath) return undefined;
  return fieldPath.split('.').reduce((c, k) => c == null ? undefined : c[k], obj);
}

function formatMs(ms: number): string {
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0 ? `${h}h ${m}m ${sec}s` : `${m}m ${sec}s`;
}

function parseResponse(data: any, parser: ParserConfig): ParsedData {
  switch (parser.type) {
    case 'balance': {
      const f = parser.fields!;
      return { type: 'balance', balance: String(resolveField(data, f.balance ?? '') ?? '—'), spent: String(resolveField(data, f.spent ?? '') ?? '—'), currency: String(resolveField(data, f.currency ?? '') ?? 'USD') };
    }
    case 'plan_usage': {
      const f = parser.fields!;
      let raw: any[] = resolveField(data, parser.arrayPath ?? '') ?? [];
      // Filter to showModels if specified
      if (parser.showModels?.length) {
        raw = raw.filter(item => {
          const name = resolveField(item, f.model ?? '') ?? '';
          return parser.showModels!.some(pattern => name === pattern || name.startsWith(pattern.replace('*', '')));
        });
      }
      const models: ModelUsage[] = raw.map(item => {
        const name: string = resolveField(item, f.model ?? '') ?? 'unknown';
        const total: number = Number(resolveField(item, f.total ?? '')) || 0;
        const used: number = Number(resolveField(item, f.used ?? '')) || 0;
        const remaining = total - used;
        const remainingPercent = total > 0 ? Math.round((remaining / total) * 100) : 0;
        const resetMs: number = Number(resolveField(item, f.resetMs ?? '')) || 0;
        const label = parser.modelLabels?.[name] ?? name;
        return { model: name, label, total, used, remaining, remainingPercent, resetMs, resetDisplay: formatMs(resetMs) };
      });
      return { type: 'plan_usage', models };
    }
    default: return { type: 'raw', json: data };
  }
}

function loadProviders(): ProviderConfig[] {
  for (const p of [path.join(__dirname, '..', 'providers.json'), path.join(__dirname, '..', '..', 'providers.json'), path.join(process.cwd(), 'providers.json')]) {
    if (fs.existsSync(p)) return (JSON.parse(fs.readFileSync(p, 'utf-8')) as ProvidersFile).providers;
  }
  return [];
}

async function fetchOne(config: ProviderConfig): Promise<ProviderResult> {
  const base = { id: config.id, name: config.name, updatedAt: Date.now() };
  const key = await getKey(config.keychainService);
  if (!key) return { ...base, available: false, error: `API Key not found in Keychain (${config.keychainService})` };
  const method = (config.api.method ?? 'GET').toUpperCase();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (config.api.authHeader) headers[config.api.authHeader] = `${config.api.authPrefix ?? ''}${key}`;
  try {
    const resp = await fetch(config.api.url, { method, headers });
    if (!resp.ok) { const body = await resp.text().catch(() => ''); return { ...base, available: true, error: `HTTP ${resp.status}: ${body.slice(0, 200)}` }; }
    return { ...base, available: true, data: parseResponse(await resp.json(), config.parser) };
  } catch (err: any) { return { ...base, available: true, error: err?.message ?? String(err) }; }
}

export async function fetchAll(): Promise<ProviderResult[]> {
  const providers = loadProviders();
  return providers.length ? Promise.all(providers.map(fetchOne)) : [];
}
