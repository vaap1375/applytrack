import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const auth=vi.hoisted(()=>({getSession:vi.fn(),refreshSession:vi.fn(),endSession:vi.fn()}));
vi.mock('./auth',()=>({sessionIsEnding:()=>false,supabase:{auth:{getSession:auth.getSession,refreshSession:auth.refreshSession}},endSession:auth.endSession,temporaryAuthError:(error:{status?:number})=>error.status===0}));
import { request } from './api';
beforeEach(()=>{vi.clearAllMocks();auth.getSession.mockResolvedValue({data:{session:{access_token:'current'}},error:null});auth.endSession.mockResolvedValue(undefined);});
afterEach(()=>vi.unstubAllGlobals());
it('uses the latest SDK token and retries a 401 once with a refreshed token',async()=>{
 auth.refreshSession.mockResolvedValue({data:{session:{access_token:'refreshed'}},error:null});
 const fetch=vi.fn().mockResolvedValueOnce({status:401,ok:false}).mockResolvedValueOnce({status:200,ok:true,json:async()=>({ok:true})});vi.stubGlobal('fetch',fetch);
 expect(await request('/reminders','stale')).toEqual({ok:true});
 expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer current');
 expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer refreshed');
});
it('clears a revoked session when refresh is rejected',async()=>{
 auth.refreshSession.mockResolvedValue({data:{session:null},error:{status:400}});
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({status:401,ok:false}));
 await expect(request('/reminders','stale')).rejects.toThrow('Please sign in again');expect(auth.endSession).toHaveBeenCalled();
});
it('does not endlessly retry invalid renewed tokens',async()=>{
 auth.refreshSession.mockResolvedValue({data:{session:{access_token:'invalid'}},error:null});
 const fetch=vi.fn().mockResolvedValue({status:401,ok:false});vi.stubGlobal('fetch',fetch);
 await expect(request('/reminders','stale')).rejects.toThrow('Please sign in again');expect(fetch).toHaveBeenCalledTimes(2);expect(auth.endSession).toHaveBeenCalled();
});
it('preserves stored sessions when refresh has a temporary network failure',async()=>{
 auth.refreshSession.mockResolvedValue({data:{session:null},error:{status:0}});vi.stubGlobal('fetch',vi.fn().mockResolvedValue({status:401,ok:false}));
 await expect(request('/reminders','stale')).rejects.toThrow('Check your connection');expect(auth.endSession).not.toHaveBeenCalled();
});
it('shares one refresh for concurrent 401s',async()=>{
 let resolve!:(value:unknown)=>void;auth.refreshSession.mockReturnValue(new Promise(r=>{resolve=r;}));
 const fetch=vi.fn().mockImplementation(async (_url,init)=>init.headers.Authorization==='Bearer current'?{status:401,ok:false}:{status:200,ok:true,json:async()=>({ok:true})});vi.stubGlobal('fetch',fetch);
 const one=request('/reminders','old'),two=request('/dashboard/summary','old');
 await vi.waitFor(()=>expect(auth.refreshSession).toHaveBeenCalledTimes(1));
 resolve({data:{session:{access_token:'refreshed'}},error:null});
 await expect(Promise.all([one,two])).resolves.toEqual([{ok:true},{ok:true}]);
});
