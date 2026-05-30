import { execFile } from 'child_process';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

/**
 * Read a secret from macOS Keychain.
 * Called every poll cycle — Keychain reads are cheap (~5ms).
 */
export async function getKey(serviceName: string): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync('security', [
      'find-generic-password',
      '-s', serviceName,
      '-w',
    ], { timeout: 5000 });
    const key = stdout.trim();
    return key || null;
  } catch {
    return null;
  }
}
