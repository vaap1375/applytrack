import { afterEach, expect, it, vi } from 'vitest';
const fake=vi.hoisted(()=>({signOut:vi.fn(),createClient:vi.fn()}));
vi.mock('@supabase/supabase-js',()=>({createClient:fake.createClient}));
afterEach(()=>{vi.unstubAllEnvs();vi.resetModules();localStorage.clear();});
it('uses supported persistent storage and auto-refresh, and clears storage on logout',async()=>{
 vi.stubEnv('VITE_SUPABASE_URL','https://test.supabase.co');vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY','test-public-key');
 fake.createClient.mockReturnValue({auth:{signOut:fake.signOut}});fake.signOut.mockResolvedValue({error:null});
 const {endSession,SESSION_KEY}=await import('./auth');
 expect(fake.createClient).toHaveBeenCalledWith('https://test.supabase.co','test-public-key',{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:false,storageKey:SESSION_KEY,storage:expect.any(Object)}});
 localStorage.setItem(SESSION_KEY,'saved-session');localStorage.setItem('unrelated','keep');
 await endSession();expect(fake.signOut).toHaveBeenCalledWith({scope:'local'});
 expect(localStorage.getItem(SESSION_KEY)).toBeNull();expect(localStorage.getItem('unrelated')).toBe('keep');
});
it('still clears local tokens if server logout fails',async()=>{
 vi.stubEnv('VITE_SUPABASE_URL','https://test.supabase.co');vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY','test-public-key');
 fake.createClient.mockReturnValue({auth:{signOut:fake.signOut}});fake.signOut.mockRejectedValue(new Error('offline'));
 const {endSession,SESSION_KEY}=await import('./auth');localStorage.setItem(SESSION_KEY,'saved-session');
 await endSession();expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});
it('prevents a late refresh write from restoring a logged-out browser',async()=>{
 vi.stubEnv('VITE_SUPABASE_URL','https://test.supabase.co');vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY','test-public-key');
 fake.createClient.mockReturnValue({auth:{signOut:fake.signOut}});fake.signOut.mockResolvedValue({error:null});
 const {endSession,SESSION_KEY,browserSessionStorage,beginLogin}=await import('./auth');
 await endSession();browserSessionStorage.setItem(SESSION_KEY,'late-refresh');expect(localStorage.getItem(SESSION_KEY)).toBeNull();
 beginLogin();browserSessionStorage.setItem(SESSION_KEY,'new-login');expect(localStorage.getItem(SESSION_KEY)).toBe('new-login');
});
