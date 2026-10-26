import { endSession, supabase, temporaryAuthError, sessionIsEnding } from './auth';
export { supabase } from './auth';
let refreshing: Promise<string> | null = null;
async function refreshedToken(): Promise<string> {
  if (!refreshing) refreshing = (async () => {
    const result = await supabase!.auth.refreshSession();
    if (result.error || !result.data.session) {
      if (result.error && temporaryAuthError(result.error)) throw new Error('Could not refresh your session. Check your connection and retry.');
      await endSession(); throw new Error('Your session ended. Please sign in again.');
    }
    if (sessionIsEnding()) throw new Error('Your session ended. Please sign in again.');
    return result.data.session.access_token;
  })().finally(()=>{refreshing=null;});
  return refreshing;
}
export async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  if (sessionIsEnding()) throw new Error('Your session ended. Please sign in again.');
  let accessToken = token;
  if (supabase) {
    const {data, error} = await supabase.auth.getSession();
    if (error || !data.session) {
      if (error && temporaryAuthError(error)) throw new Error('Could not restore your session. Check your connection and retry.');
      await endSession(); throw new Error('Your session ended. Please sign in again.');
    }
    accessToken = data.session.access_token;
  }
  const send = (value: string) => fetch(`${import.meta.env.VITE_API_URL || ''}/api${path}`, {...init, headers:{...init?.headers,'Content-Type':'application/json',Authorization:`Bearer ${value}`}});
  let response = await send(accessToken);
  if (response.status === 401 && supabase) {
    response = await send(await refreshedToken());
    if (response.status === 401) {
      await endSession(); throw new Error('Your session ended. Please sign in again.');
    }
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.fields?.join('; ') || body?.error?.message || `Request failed (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const statuses = ['Saved','Applied','Assessment','Interview','Offer','Rejected','Withdrawn'] as const;
export type Status = typeof statuses[number];
export type Application = {id:string; company_name:string; job_title:string; location:string|null; job_url:string|null; external_job_id:string|null; status:Status; applied_at:string|null; notes:string|null; created_at:string; updated_at:string; status_revision:number};
export type ApplicationInput = Omit<Application,'id'|'created_at'|'updated_at'|'status_revision'>;
export type HistoryEvent = {id:string; event_type:string; source?:string; source_message_id?:string|null; source_timestamp?:string|null; notes?:string|null; old_status:string|null; new_status:string|null; created_at:string};

export type JobPreview = {
  company_name: string | null;
  job_title: string | null;
  location: string | null;
  external_job_id: string | null;
  description: string | null;
  canonical_url: string;
  source: string;
  missing_fields: string[];
  warnings: string[];
  duplicate_ids: string[];
};
