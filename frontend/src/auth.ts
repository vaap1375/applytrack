import { createClient } from '@supabase/supabase-js';

export const SESSION_KEY = 'applytrack.auth';
export const AUTH_ENDED = 'applytrack:auth-ended';
let loggingOut = false;
export const sessionIsEnding = () => loggingOut;
export const beginLogin = () => { loggingOut = false; };
// Supported Supabase storage adapter. Fence late refresh writes after logout.
export const browserSessionStorage = {
  getItem: (key: string) => localStorage.getItem(key),
  setItem: (key: string, value: string) => { if (!loggingOut) localStorage.setItem(key, value); },
  removeItem: (key: string) => localStorage.removeItem(key),
};
const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
export const supabase = url && key ? createClient(url, key, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false, storageKey: SESSION_KEY, storage: browserSessionStorage },
}) : null;

export function temporaryAuthError(error: unknown): boolean {
  const value = error as {name?: string; status?: number};
  return value?.name === 'AuthRetryableFetchError' || value?.status === 0 || (value?.status || 0) >= 500;
}

export async function endSession(): Promise<void> {
  loggingOut = true;
  window.dispatchEvent(new Event(AUTH_ENDED));
  try {
    // Revoke this session's refresh token without signing out other devices.
    await supabase?.auth.signOut({scope: 'local'});
  } catch {
    // Local logout still succeeds when remote revocation is unavailable.
  } finally {
    // Supabase can return a network error before clearing storage. Always clear
    // this browser on explicit logout; no tokens/credentials are logged.
    for (const suffix of ['', '-user', '-code-verifier']) {
      try { localStorage.removeItem(SESSION_KEY + suffix); } catch { /* storage unavailable */ }
    }
    window.dispatchEvent(new Event(AUTH_ENDED));
  }
}
