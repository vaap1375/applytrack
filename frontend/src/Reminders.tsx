import { useEffect, useState, type FormEvent } from 'react';
import { request } from './api';

export type Reminder = {
  id: string; application_id: string; title: string; due_at: string;
  completed_at: string | null; company_name: string; job_title: string;
  bucket: 'overdue' | 'due_today' | 'upcoming' | 'completed';
};
type Bucket = Reminder['bucket'];
type Listing = {items: Reminder[]; total: number; counts: Record<Bucket,number>};
const labels: Record<Bucket,string> = {overdue:'Overdue',due_today:'Due today',upcoming:'Upcoming',completed:'Completed'};

export function localInputValue(instant: string, timeZone?: string) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(instant));
  const part = (name: string) => parts.find(p=>p.type===name)!.value;
  return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`;
}
export function localDueToUtc(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || localInputValue(date.toISOString()) !== value) {
    throw new Error('Choose a valid local date and time. This time may fall in a daylight-saving clock change.');
  }
  return date.toISOString();
}

export function ReminderForm({item,onSave,onCancel}:{item?:Reminder;onSave:(data:{title:string;due_at:string})=>Promise<void>;onCancel:()=>void}) {
  const [busy,setBusy] = useState(false), [error,setError] = useState('');
  async function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); const fields=new FormData(event.currentTarget); setBusy(true);setError('');
    try {
      await onSave({title:String(fields.get('title')||'').trim(),due_at:item && String(fields.get('due_at')) === localInputValue(item.due_at) ? item.due_at : localDueToUtc(String(fields.get('due_at')||''))});
    } catch (err) {setError((err as Error).message);} finally {setBusy(false);}
  }
  return <form className="reminder-form" onSubmit={submit}>
    <h3>{item?'Edit reminder':'Add a reminder'}</h3>
    <label>Reminder title<input name="title" required maxLength={200} defaultValue={item?.title} placeholder="Follow up with recruiter" autoFocus/></label>
    <label>Due date and time<input name="due_at" type="datetime-local" required defaultValue={item?localInputValue(item.due_at):''}/></label>
    <p className="import-help">Your timezone: {Intl.DateTimeFormat().resolvedOptions().timeZone}. In-app only; no notifications are sent.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="form-actions"><button className="secondary" type="button" onClick={onCancel} disabled={busy}>Cancel</button><button disabled={busy}>{busy?'Saving…':'Save reminder'}</button></div>
  </form>;
}

export function ReminderPanel({token,applicationId,onOpen,refresh=0}:{token:string;applicationId?:string;onOpen:(id:string)=>Promise<void>;refresh?:number}) {
  const [data,setData]=useState<Listing|null>(null), [bucket,setBucket]=useState<Bucket>('overdue');
  const [page,setPage]=useState(1), [loading,setLoading]=useState(true), [error,setError]=useState('');
  const [revision,setRevision]=useState(0), [editing,setEditing]=useState<Reminder|'new'|null>(null);
  const [removing,setRemoving]=useState<Reminder|null>(null), [busy,setBusy]=useState(false), [notice,setNotice]=useState('');
  useEffect(()=>{
    let active=true;setLoading(true);setError('');
    const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    request<Listing>(`/reminders?timezone=${encodeURIComponent(timezone)}&bucket=${bucket}&page=${page}&page_size=10${applicationId?'&application_id='+applicationId:''}`,token)
      .then(result=>{if(active)setData(result);}).catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[token,applicationId,bucket,page,revision,refresh]);
  useEffect(()=>{
    const reload=()=>setRevision(n=>n+1);
    const timer=setInterval(reload,60000);
    window.addEventListener('focus',reload);
    return()=>{clearInterval(timer);window.removeEventListener('focus',reload);};
  },[]);
  const reload=()=>{setPage(1);setRevision(n=>n+1);};
  async function save(values:{title:string;due_at:string}) {
    await request(editing==='new'?'/reminders':`/reminders/${(editing as Reminder).id}`,token,{method:editing==='new'?'POST':'PATCH',body:JSON.stringify(editing==='new'?{...values,application_id:applicationId}:values)});
    setEditing(null);setNotice('Reminder saved.');reload();
  }
  async function complete(item:Reminder) {
    setBusy(true);setError('');
    try {await request(`/reminders/${item.id}`,token,{method:'PATCH',body:JSON.stringify({completed:!item.completed_at})});setNotice(item.completed_at?'Reminder reopened.':'Reminder completed.');reload();}
    catch(err){setError((err as Error).message);}finally{setBusy(false);}
  }
  async function remove() {
    if(!removing)return;setBusy(true);setError('');
    try {await request(`/reminders/${removing.id}`,token,{method:'DELETE'});setRemoving(null);setNotice('Reminder deleted.');reload();}
    catch(err){setError((err as Error).message);}finally{setBusy(false);}
  }
  return <section className="card reminders-card" aria-label="Follow-up reminders">
    <div className="section-heading"><div><h2>Follow-ups & deadlines</h2><p>{applicationId?'Plan the next step for this opportunity.':'Your next steps, organized by due time.'}</p></div>{applicationId&&<button className="secondary" onClick={()=>{setEditing('new');setRemoving(null);}} disabled={busy}>Add reminder</button>}</div>
    <div className="reminder-tabs" role="group" aria-label="Reminder categories">{(Object.keys(labels) as Bucket[]).map(key=><button key={key} aria-pressed={bucket===key} className={bucket===key?'active':''} onClick={()=>{setBucket(key);setPage(1);}}>{labels[key]} <span>{data?.counts[key]??'—'}</span></button>)}</div>
    {notice&&<p className="reminder-notice" role="status">{notice}</p>}
    {error&&<div className="error reminder-error" role="alert">{error} <button className="text-button" onClick={reload}>Retry reminders</button></div>}
    {editing&&<ReminderForm key={editing==='new'?'new':editing.id} item={editing==='new'?undefined:editing} onSave={save} onCancel={()=>setEditing(null)}/>}
    {removing&&<div className="reminder-confirm" role="group" aria-label="Confirm reminder deletion"><p>Delete “{removing.title}”? This cannot be undone.</p><button className="secondary" disabled={busy} onClick={()=>setRemoving(null)}>Keep reminder</button><button className="delete-button" disabled={busy} onClick={()=>void remove()}>Delete reminder</button></div>}
    {loading?<div className="empty" role="status">Loading reminders…</div>:error?<p className="reminder-empty">Reminders could not be loaded.</p>:!data?.items.length?<p className="reminder-empty">No {labels[bucket].toLowerCase()} reminders.{applicationId?' Add a reminder to plan your next step.':' Create one from an application’s detail page.'}</p>:<ul className="reminder-list">{data.items.map(item=><li key={item.id} className={item.completed_at?'reminder-completed':''}>
      <div className="reminder-copy"><strong>{item.title}</strong><button className="text-button" onClick={()=>void onOpen(item.application_id).catch(err=>setError(err.message))}>{item.company_name} · {item.job_title}</button><small><span className={`reminder-bucket ${item.bucket}`}>{labels[item.bucket]}</span> · <time dateTime={item.due_at}>{new Date(item.due_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}</time>{item.completed_at&&` · Completed ${new Date(item.completed_at).toLocaleString()}`}</small></div>
      <div className="reminder-actions"><button className="secondary" disabled={busy} onClick={()=>void complete(item)}>{item.completed_at?'Reopen':'Complete'}</button><button className="text-button" disabled={busy} onClick={()=>{setEditing(item);setRemoving(null);}}>Edit</button><button className="text-button danger" disabled={busy} onClick={()=>{setRemoving(item);setEditing(null);}}>Delete</button></div>
    </li>)}</ul>}
    <footer className="table-footer"><span>{data?.total??0} {labels[bucket].toLowerCase()}</span><div><button className="icon-button" aria-label="Previous reminders page" disabled={loading||page===1} onClick={()=>setPage(n=>n-1)}>←</button><span>Page {page}</span><button className="icon-button" aria-label="Next reminders page" disabled={loading||page*10>=(data?.total??0)} onClick={()=>setPage(n=>n+1)}>→</button></div></footer>
  </section>;
}
