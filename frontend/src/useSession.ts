import { useCallback, useEffect, useRef, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { AUTH_ENDED, SESSION_KEY, endSession, supabase, temporaryAuthError, sessionIsEnding } from './auth';

export function useSession() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);
  const retrySession = useCallback(() => setRetry(n=>n+1), []);

  useEffect(() => {
    if (!supabase) { setLoading(false); return; }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const client = supabase;
    async function restore() {
      if (sessionIsEnding()) { setSession(null); setLoading(false); return; }
      const current = ++generation.current;
      try {
        const {data, error: sessionError} = await client.auth.getSession();
        if (sessionError) throw sessionError;
        if (data.session) {
          // Storage is not authoritative. Verify the restored identity remotely;
          // the backend independently verifies every API access token.
          const {data: userData, error: userError} = await client.auth.getUser(data.session.access_token);
          if (userError) throw userError;
          if (!userData.user || userData.user.id !== data.session.user.id) throw new Error('Invalid session');
        }
        if (active && current === generation.current && !sessionIsEnding()) {
          setSession(data.session); setError(''); setLoading(false);
        }
      } catch (err) {
        if (!active || current !== generation.current) return;
        if (temporaryAuthError(err)) {
          setSession(null); setError('Could not verify your session. Check your connection and retry.'); setLoading(false);
        } else {
          await endSession();
          if (active) { setSession(null); setError('Your session ended. Please sign in again.'); setLoading(false); }
        }
      }
    }
    const clear = () => { generation.current++; setSession(null); setLoading(false); };
    window.addEventListener(AUTH_ENDED, clear);
    const storage = (event: StorageEvent) => { if (event.key === SESSION_KEY && !event.newValue) { clear(); void endSession(); } };
    window.addEventListener('storage', storage);
    // Keep the auth callback synchronous; SDK calls run outside its callback.
    const {data} = client.auth.onAuthStateChange((event, next) => {
      if (!active || sessionIsEnding()) return;
      if (event === 'SIGNED_OUT') { clear(); return; }
      if (event === 'TOKEN_REFRESHED') {
        generation.current++; setSession(next); setLoading(false); setError(''); return;
      }
      clearTimeout(timer);
      timer = setTimeout(()=>void restore(), 0);
    });
    void restore();
    const focus = () => { void restore(); };
    window.addEventListener('focus', focus);
    return () => {
      active = false; generation.current++; clearTimeout(timer); data.subscription.unsubscribe();
      window.removeEventListener(AUTH_ENDED, clear); window.removeEventListener('focus', focus); window.removeEventListener('storage', storage);
    };
  }, [retry]);
  return {session, loading, error, retrySession};
}
