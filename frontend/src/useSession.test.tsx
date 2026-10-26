import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { AuthChangeEvent, Session } from '@supabase/supabase-js';
import { useSession } from './useSession';
const mocks=vi.hoisted(()=>({getSession:vi.fn(),getUser:vi.fn(),unsubscribe:vi.fn(),callback:null as ((event:AuthChangeEvent,session:Session|null)=>void)|null,endSession:vi.fn()}));
vi.mock('./auth',()=>({sessionIsEnding:()=>false,
 AUTH_ENDED:'test:auth-ended',SESSION_KEY:'test.auth',
 temporaryAuthError:(error:{status?:number})=>error.status===0,
 endSession:mocks.endSession,
 supabase:{auth:{getSession:mocks.getSession,getUser:mocks.getUser,onAuthStateChange:(callback:typeof mocks.callback)=>{mocks.callback=callback;return {data:{subscription:{unsubscribe:mocks.unsubscribe}}};}}},
}));
const session={access_token:'stored-token',user:{id:'owner',email:'owner@example.com'}} as Session;
beforeEach(()=>{
 vi.clearAllMocks();mocks.getSession.mockResolvedValue({data:{session},error:null});
 mocks.getUser.mockResolvedValue({data:{user:{id:'owner'}},error:null});
 mocks.endSession.mockImplementation(async()=>{window.dispatchEvent(new Event('test:auth-ended'));});
});
afterEach(cleanup);
it('restores and validates a saved session after remount',async()=>{
 const first=renderHook(()=>useSession());expect(first.result.current.loading).toBe(true);
 await waitFor(()=>expect(first.result.current.session?.access_token).toBe('stored-token'));
 expect(mocks.getUser).toHaveBeenCalledWith('stored-token');first.unmount();
 const refreshed=renderHook(()=>useSession());
 await waitFor(()=>expect(refreshed.result.current.session?.user.id).toBe('owner'));
 expect(mocks.unsubscribe).toHaveBeenCalled();
});
it('handles no stored session and signed-out events',async()=>{
 mocks.getSession.mockResolvedValueOnce({data:{session:null},error:null});
 const {result}=renderHook(()=>useSession());await waitFor(()=>expect(result.current.loading).toBe(false));
 expect(result.current.session).toBeNull();expect(mocks.getUser).not.toHaveBeenCalled();
});
it('clears invalid server-rejected sessions',async()=>{
 mocks.getUser.mockResolvedValue({data:{user:null},error:{status:401}});
 const {result}=renderHook(()=>useSession());
 await waitFor(()=>expect(result.current.error).toContain('Please sign in again'));
 expect(result.current.session).toBeNull();expect(mocks.endSession).toHaveBeenCalled();
});
it('lets transient validation failures retry without deleting the saved session',async()=>{
 mocks.getUser.mockResolvedValueOnce({data:{user:null},error:{status:0}});
 const {result}=renderHook(()=>useSession());
 await waitFor(()=>expect(result.current.error).toContain('Check your connection'));
 expect(mocks.endSession).not.toHaveBeenCalled();
 act(()=>result.current.retrySession());
 await waitFor(()=>expect(result.current.session?.user.id).toBe('owner'));
});
it('updates tokens and clears the workspace on logout',async()=>{
 const {result}=renderHook(()=>useSession());await waitFor(()=>expect(result.current.session).not.toBeNull());
 act(()=>mocks.callback!('TOKEN_REFRESHED',{...session,access_token:'renewed-token'}));
 expect(result.current.session?.access_token).toBe('renewed-token');
 act(()=>mocks.callback!('SIGNED_OUT',null));expect(result.current.session).toBeNull();
});
it('does not restore stale state after logout during validation',async()=>{
 let resolve!:(value:unknown)=>void;
 mocks.getUser.mockReturnValue(new Promise(r=>{resolve=r;}));
 const {result}=renderHook(()=>useSession());await waitFor(()=>expect(mocks.getUser).toHaveBeenCalled());
 act(()=>mocks.callback!('SIGNED_OUT',null));
 await act(async()=>resolve({data:{user:{id:'owner'}},error:null}));
 expect(result.current.session).toBeNull();
});
it('handles SDK rejection of expired/revoked refresh tokens',async()=>{
 mocks.getSession.mockResolvedValue({data:{session:null},error:{status:400}});
 const {result}=renderHook(()=>useSession());
 await waitFor(()=>expect(result.current.loading).toBe(false));
 expect(mocks.endSession).toHaveBeenCalled();expect(result.current.session).toBeNull();
});
it('clears and fences the local session when another tab removes storage',async()=>{
 const {result}=renderHook(()=>useSession());await waitFor(()=>expect(result.current.session).not.toBeNull());
 act(()=>window.dispatchEvent(new StorageEvent('storage',{key:'test.auth',newValue:null})));
 expect(result.current.session).toBeNull();expect(mocks.endSession).toHaveBeenCalled();
});
