import { useEffect, useState, type FormEvent } from 'react';
import { request, statuses, type Application } from './api';

type Connection={configured:boolean;connected:boolean;email:string|null;health:string;last_sync_at:string|null;auto_updates:boolean;lookback_days:number;dry_run_at:string|null;more:boolean;stats:{processed?:number;matches?:number;updates?:number;recovered_history?:boolean}};
export type GmailItem={id:string;gmail_id:string;subject:string|null;sender:string|null;excerpt:string|null;received_at:string;classification:string;class_confidence:number;match_confidence:number;application_id:string|null;proposed_status:string|null;old_status:string|null;state:string;reason:string;evidence:{application_id:string;company_name:string;job_title:string;score:number;reasons:string[];trusted_sender:boolean}[]};
type Listing={items:GmailItem[];total:number};
const time=(value:string|null)=>value?new Date(value).toLocaleString():'Never';
const strength=(value:number)=>value>=.99?'Strong rule evidence':value>=.8?'Possible match':'Uncertain';

export function GmailReview({item,token,choices,onDone,onOpen}:{item:GmailItem;token:string;choices:Application[];onDone:()=>void;onOpen:(id:string)=>Promise<void>}){
  const [applicationId,setApplicationId]=useState(item.application_id||'');
  const [application,setApplication]=useState<Application|null>(null);
  const [status,setStatus]=useState(item.proposed_status||'');
  const [ack,setAck]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [revision,setRevision]=useState(0);
  useEffect(()=>{
    let active=true;setApplication(null);setAck(false);
    if(applicationId)request<Application>(`/applications/${applicationId}`,token).then(result=>{if(active)setApplication(result);}).catch(err=>{if(active)setError(err.message);});
    return()=>{active=false;};
  },[applicationId,token,revision]);
  async function act(action:'accept'|'dismiss'|'undo'){
    setBusy(true);setError('');
    try{
      await request(`/gmail/messages/${item.id}/${action}`,token,{method:'POST',...(action==='accept'?{body:JSON.stringify({application_id:applicationId,status,expected_revision:application!.status_revision})}:{})});
      onDone();
    }catch(err){setError((err as Error).message);setAck(false);}finally{setBusy(false);}
  }
  const options=new Map(choices.map(app=>[app.id,`${app.company_name} · ${app.job_title}`]));
  for(const candidate of item.evidence)options.set(candidate.application_id,`${candidate.company_name} · ${candidate.job_title}`);
  return <article className="gmail-item">
    <div className="gmail-item-heading"><div><strong>{item.subject||'Email text removed / unavailable'}</strong><small>{item.sender||'Sender redacted'} · {time(item.received_at)}</small></div><span className="badge">{item.classification}</span></div>
    {item.excerpt&&<p className="gmail-excerpt">{item.excerpt}</p>}
    <p className="import-help">{strength(item.class_confidence)} · Match: {strength(item.match_confidence)}. {item.reason}</p>
    <details><summary>Matching evidence</summary><p className="import-help">Source message ID: {item.gmail_id}</p>{!item.evidence.length?<p className="import-help">No reliable application identity was found.</p>:item.evidence.map(candidate=><div key={candidate.application_id} className="gmail-evidence"><strong>{candidate.company_name} · {candidate.job_title}</strong><ul>{candidate.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul><small>{candidate.trusted_sender?'DKIM-verified employer/ATS sender':'Sender identity is insufficient for automation'}</small></div>)}</details>
    {error&&<p role="alert" className="error">{error} <button className="text-button" onClick={()=>{setError('');setRevision(n=>n+1);}}>Reload application status</button></p>}
    {item.state==='review'?<>
      <div className="form-grid"><label>Application for this email<select value={applicationId} onChange={e=>setApplicationId(e.target.value)}><option value="">Choose an application…</option>{Array.from(options).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><label>Suggested status<select value={status} onChange={e=>{setStatus(e.target.value);setAck(false);}}><option value="">Choose a status…</option>{statuses.map(s=><option key={s}>{s}</option>)}</select></label></div>
      {application&&<p className="import-help">Current status: <strong>{application.status}</strong>. <button className="text-button" onClick={()=>void onOpen(application.id).catch(err=>setError(err.message))}>Open application</button></p>}
      <label className="gmail-check"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>I reviewed this email and want to apply this status, including any older message or manual correction.</label>
      <div className="gmail-actions"><button disabled={busy||!ack||!status||!application||application.status===status} onClick={()=>void act('accept')}>Accept change</button><button className="secondary" disabled={busy} onClick={()=>void act('dismiss')}>Dismiss</button></div>
    </>:<div className="gmail-actions">{item.application_id&&<button className="text-button" onClick={()=>void onOpen(item.application_id!).catch(err=>setError(err.message))}>Open application</button>}{['applied','accepted'].includes(item.state)&&<><span className="import-help">{item.old_status} → {item.proposed_status}</span><button className="secondary" disabled={busy} onClick={()=>void act('undo')}>Undo change</button></>}</div>}
  </article>;
}

export function GmailPanel({token,onChange,onOpen}:{token:string;onChange:()=>void;onOpen:(id:string)=>Promise<void>}){
  const [connection,setConnection]=useState<Connection|null>(null),[listing,setListing]=useState<Listing|null>(null),[choices,setChoices]=useState<Application[]>([]);
  const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const [tab,setTab]=useState('review'),[page,setPage]=useState(1),[refresh,setRefresh]=useState(0),[search,setSearch]=useState('');
  const [lookback,setLookback]=useState(30),[dryReview,setDryReview]=useState(false),[disconnecting,setDisconnecting]=useState(false),[purge,setPurge]=useState(true);
  const [ruleId,setRuleId]=useState(''),[aliases,setAliases]=useState(''),[domains,setDomains]=useState('');
  useEffect(()=>{
    const result=new URLSearchParams(window.location.hash.slice(1)).get('gmail');
    if(result){setNotice(result==='connected'?'Gmail connected. Start with a dry-run sync.':result==='cancelled'?'Gmail authorization was cancelled.':result==='account_mismatch'?'Disconnect and delete previous Gmail data before linking a different account.':'Gmail authorization failed or expired. Start Connect Gmail again.');window.history.replaceState(null,'',window.location.pathname+window.location.search);}
  },[]);
  useEffect(()=>{
    let active=true;setLoading(true);setError('');
    Promise.all([request<Connection>('/gmail/connection',token),request<Listing>(`/gmail/messages?state=${tab}&page=${page}`,token),request<{items:Application[]}>(`/applications?page_size=100&search=${encodeURIComponent(search)}`,token)])
      .then(([status,messages,apps])=>{if(active){setConnection(status);setLookback(status.lookback_days);setListing(messages);setChoices(apps.items);}})
      .catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[token,tab,page,refresh,search]);
  useEffect(()=>{
    let active=true;setAliases('');setDomains('');
    if(ruleId)request<{aliases:string[];sender_domains:string[]}>(`/gmail/rules/${ruleId}`,token).then(rule=>{if(active){setAliases(rule.aliases.join(', '));setDomains(rule.sender_domains.join(', '));}}).catch(err=>{if(active)setError(err.message);});
    return()=>{active=false;};
  },[ruleId,token]);
  function reload(){setRefresh(n=>n+1);onChange();}
  async function operation(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(err){setError((err as Error).message);}finally{setBusy(false);}}
  async function connect(){await operation(async()=>{const result=await request<{authorization_url:string}>('/gmail/oauth/start',token,{method:'POST',credentials:'include'});window.location.assign(result.authorization_url);});}
  async function sync(){await operation(async()=>{const result=await request<Connection>('/gmail/sync',token,{method:'POST'});setConnection(result);setNotice(result.health==='connected'?(result.more?'This batch is saved. Continue sync to process the next batch.':'Gmail sync complete. Review the results below.'):result.health==='reconnect_required'?'Gmail access expired or was revoked. Reconnect to continue.':'Sync paused or Gmail is rate-limiting requests. The checkpoint is saved; try again shortly.');setDryReview(false);reload();});}
  async function toggle(){await operation(async()=>{const updated=await request<Connection>('/gmail/settings',token,{method:'PATCH',body:JSON.stringify({auto_updates:!connection!.auto_updates,reviewed_dry_run:dryReview})});setConnection(updated);setNotice(updated.auto_updates?'Automatic updates enabled for future reliable messages only.':'Automatic updates disabled.');});}
  async function saveRules(event:FormEvent){event.preventDefault();await operation(async()=>{await request(`/gmail/rules/${ruleId}`,token,{method:'PATCH',body:JSON.stringify({aliases:aliases.split(',').map(s=>s.trim()).filter(Boolean),sender_domains:domains.split(',').map(s=>s.trim()).filter(Boolean)})});setNotice('Matching rules saved. They apply to newly processed emails; existing suggestions can be matched manually.');});}
  return <>
    <div className="page-heading"><div><span className="eyebrow">CONNECTED WORKSPACE</span><h1>Gmail integration</h1><p>Read recruiting updates, review evidence, and keep your applications current.</p></div></div>
    {notice&&<p role="status" className="notice">{notice}</p>}{error&&<div role="alert" className="error">{error} <button className="text-button" onClick={reload}>Retry Gmail</button></div>}
    {loading&&!connection?<div className="empty" role="status">Loading Gmail connection…</div>:<section className="card detail-card gmail-connection"><div className="section-heading"><div><h2>Gmail connection</h2><p>{connection?.email||'No Gmail account linked'} · {connection?.health||'Not connected'}</p></div><div className="gmail-actions"><button disabled={busy||!connection?.configured} onClick={()=>void connect()}>{connection?.connected?'Reconnect Gmail':'Connect Gmail'}</button>{connection?.email&&<button className="secondary danger" disabled={busy} onClick={()=>setDisconnecting(true)}>Disconnect Gmail</button>}</div></div>
      {!connection?.configured&&<p className="error">Gmail server credentials and encryption key are not configured. Follow the Google Cloud setup in README.md.</p>}
      <p className="import-help">Read-only Gmail access. Supabase sign-in remains separate. No email is sent, modified, or marked read.</p>
      <div className="gmail-sync-info"><span>Last successful sync: <strong>{time(connection?.last_sync_at||null)}</strong></span><span>Processed: {connection?.stats.processed??0}</span><span>Matches: {connection?.stats.matches??0}</span><span>Updates: {connection?.stats.updates??0}</span></div>
      {connection?.stats.recovered_history&&<p className="import-help">The history cursor or page token expired. A bounded lookback recovery was used; older mail outside that window was not scanned.</p>}
      <div className="gmail-actions"><label>Initial/recovery lookback (days)<input type="number" min={1} max={365} value={lookback} onChange={e=>setLookback(Number(e.target.value))}/></label><button className="secondary" disabled={busy||!connection?.connected||connection.more||lookback<1||lookback>365} onClick={()=>void operation(async()=>{await request('/gmail/settings',token,{method:'PATCH',body:JSON.stringify({lookback_days:lookback})});setNotice('Lookback saved. It affects the next initial or expired-history recovery scan.');})}>Save lookback</button><button disabled={busy||!connection?.connected} onClick={()=>void sync()}>{busy?'Working…':connection?.more?'Continue sync':'Sync Gmail now'}</button></div>
      <hr/><h2>Automatic status updates</h2><p className="import-help">Disabled by default. Only unique, strongly identified messages with explicit status language and a verified employer/ATS sender can update an application. Newer manual corrections, stale emails, Offer, and other terminal statuses are protected.</p>
      {!connection?.auto_updates&&<label className="gmail-check"><input type="checkbox" checked={dryReview} onChange={e=>setDryReview(e.target.checked)}/>I completed and reviewed a real-email dry run and want future reliable messages to update statuses.</label>}
      <button className="secondary" disabled={busy||!connection?.connected||(!connection.auto_updates&&(!connection.dry_run_at||connection.more||!dryReview))} onClick={()=>void toggle()}>{connection?.auto_updates?'Disable automatic updates':'Enable automatic updates'}</button>
      {disconnecting&&<div className="reminder-confirm"><p>Disconnect Gmail? Tokens will be removed. Application statuses and audit history are retained.</p><label className="gmail-check"><input type="checkbox" checked={purge} onChange={e=>setPurge(e.target.checked)}/>Delete retained Gmail messages, excerpts, matching rules, and sync state.</label><button className="secondary" disabled={busy} onClick={()=>setDisconnecting(false)}>Cancel</button><button className="delete-button" disabled={busy} onClick={()=>void operation(async()=>{await request('/gmail/disconnect',token,{method:'POST',body:JSON.stringify({delete_data:purge})});setDisconnecting(false);setDryReview(false);setNotice('Gmail disconnected. Local credentials removed; application audit events retained.');reload();})}>Confirm disconnect</button></div>}
    </section>}
    <section className="card gmail-review-queue"><div className="section-heading"><div><h2>Review & update history</h2><p>Rule strengths describe evidence, not measured real-world accuracy.</p></div></div>
      <div className="reminder-tabs">{[['review','Review queue'],['applied','Automatic updates'],['accepted','Approved changes'],['dismissed','Dismissed'],['undone','Undone'],['unchanged','Already current']].map(([value,label])=><button key={value} aria-pressed={tab===value} className={tab===value?'active':''} onClick={()=>{setTab(value);setPage(1);}}>{label}</button>)}</div>
      <div className="gmail-search"><label>Find an application for review or aliases<input value={search} placeholder="Search company or role…" onChange={e=>setSearch(e.target.value)}/></label></div>
      {loading?<p className="reminder-empty" role="status">Loading Gmail results…</p>:!listing?.items.length?<p className="reminder-empty">No {tab==='review'?'suggestions waiting for review':'items in this category'}.</p>:listing.items.map(item=><GmailReview key={item.id} item={item} token={token} choices={choices} onDone={reload} onOpen={onOpen}/>)}
      <footer className="table-footer"><span>{listing?.total??0} items</span><div><button className="icon-button" aria-label="Previous Gmail results" disabled={page===1||loading} onClick={()=>setPage(n=>n-1)}>←</button><span>Page {page}</span><button className="icon-button" aria-label="Next Gmail results" disabled={loading||page*20>=(listing?.total??0)} onClick={()=>setPage(n=>n+1)}>→</button></div></footer>
    </section>
    <section className="card detail-card gmail-rules"><h2>Employer matching aliases</h2><p className="import-help">Optional explicit aliases and employer sender domains help matching. Shared ATS domains alone never identify an application.</p><form className="application-form" onSubmit={event=>void saveRules(event)}><label>Application for matching rules<select value={ruleId} onChange={e=>setRuleId(e.target.value)}><option value="">Choose an application…</option>{choices.map(app=><option key={app.id} value={app.id}>{app.company_name} · {app.job_title}</option>)}</select></label><label>Company aliases (comma separated)<input value={aliases} maxLength={4000} onChange={e=>setAliases(e.target.value)} placeholder="Example Corporation, Example Labs"/></label><label>Employer domains (comma separated)<input value={domains} maxLength={4000} onChange={e=>setDomains(e.target.value)} placeholder="example.com"/></label><button disabled={busy||!ruleId}>Save matching rules</button></form></section>
  </>;
}
