import { BrowserWindow } from 'electron';
import { fetchAll, ProviderResult } from './provider-engine';

const DEFAULT_INTERVAL_MS = 60_000;

export class Poller {
  private timer: ReturnType<typeof setInterval> | null = null;
  private intervalMs: number;
  private lastResults: ProviderResult[] = [];
  private onResults?: (results: ProviderResult[]) => void;

  constructor(intervalMs = DEFAULT_INTERVAL_MS) {
    this.intervalMs = intervalMs;
  }

  /** Register a callback for each poll cycle (used by main.ts to push IPC). */
  setOnResults(fn: (results: ProviderResult[]) => void) {
    this.onResults = fn;
  }

  /** Run a single poll and notify. */
  async pollNow(): Promise<ProviderResult[]> {
    const results = await fetchAll();
    this.lastResults = results;
    this.onResults?.(results);
    return results;
  }

  /** Start periodic polling. Fires once immediately. */
  start() {
    if (this.timer) return;
    this.pollNow(); // fire immediately
    this.timer = setInterval(() => this.pollNow(), this.intervalMs);
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  getLastResults(): ProviderResult[] {
    return this.lastResults;
  }
}
