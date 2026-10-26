import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ReminderForm, ReminderPanel, localInputValue, localDueToUtc, type Reminder } from './Reminders';
import { request } from './api';
vi.mock('./api',()=>({request:vi.fn()}));
const api=vi.mocked(request);
const reminder:Reminder={id:'r1',application_id:'a1',title:'Follow up',due_at:'2026-10-27T17:30:00Z',completed_at:null,company_name:'Example',job_title:'Engineer',bucket:'overdue'};
const listing={items:[reminder],total:1,counts:{overdue:1,due_today:0,upcoming:0,completed:0}};
beforeEach(()=>api.mockReset());afterEach(cleanup);
it('converts UTC to explicit local calendar time including DST',()=>{
 expect(localInputValue('2026-10-27T02:30:00Z','America/Detroit')).toBe('2026-10-26T22:30');
 expect(localInputValue('2026-11-01T05:30:00Z','America/Detroit')).toBe('2026-11-01T01:30');
 expect(localInputValue('2026-11-01T06:30:00Z','America/Detroit')).toBe('2026-11-01T01:30');
 const value='2026-10-26T15:45';expect(localInputValue(localDueToUtc(value))).toBe(value);
 expect(()=>localDueToUtc('not a date')).toThrow('valid local');
});
it('creates a reminder using a UTC instant and shows errors',async()=>{
 const save=vi.fn().mockRejectedValueOnce(new Error('Try again')).mockResolvedValue(undefined);
 render(<ReminderForm onSave={save} onCancel={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('Reminder title'),{target:{value:'Follow up'}});
 fireEvent.change(screen.getByLabelText('Due date and time'),{target:{value:'2026-10-27T13:30'}});
 fireEvent.click(screen.getByRole('button',{name:'Save reminder'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Try again');
 fireEvent.click(screen.getByRole('button',{name:'Save reminder'}));
 await waitFor(()=>expect(save).toHaveBeenLastCalledWith({title:'Follow up',due_at:localDueToUtc('2026-10-27T13:30')}));
});
it('loads category counts, opens the application, and completes a reminder',async()=>{
 api.mockResolvedValue(listing);const open=vi.fn().mockResolvedValue(undefined);
 render(<ReminderPanel token="token" onOpen={open}/>);
 expect(screen.getByText('Loading reminders…')).toBeVisible();
 fireEvent.click(await screen.findByRole('button',{name:'Example · Engineer'}));
 expect(open).toHaveBeenCalledWith('a1');
 fireEvent.click(screen.getByRole('button',{name:'Complete'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/reminders/r1','token',expect.objectContaining({method:'PATCH',body:JSON.stringify({completed:true})})));
 expect(await screen.findByText('Reminder completed.')).toBeVisible();
});
it('reopens completed reminders and confirms deletion',async()=>{
 api.mockResolvedValue({...listing,items:[{...reminder,completed_at:'2026-10-27T18:00:00Z',bucket:'completed'}]});
 render(<ReminderPanel token="token" applicationId="a1" onOpen={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Reopen'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/reminders/r1','token',expect.objectContaining({body:JSON.stringify({completed:false})})));
 await screen.findByText('Reminder reopened.');
 fireEvent.click(screen.getByRole('button',{name:'Delete'}));
 expect(screen.getByRole('group',{name:'Confirm reminder deletion'})).toBeVisible();
 expect(api.mock.calls.some(args=>args[2]?.method==='DELETE')).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'Delete reminder'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/reminders/r1','token',{method:'DELETE'}));
});
it('creates directly in application details and changes category',async()=>{
 api.mockResolvedValue({...listing,items:[],total:0});
 render(<ReminderPanel token="token" applicationId="a1" onOpen={vi.fn()}/>);
 expect(await screen.findByText(/No overdue reminders/)).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'Add reminder'}));
 fireEvent.change(screen.getByLabelText('Reminder title'),{target:{value:'Assessment deadline'}});
 fireEvent.change(screen.getByLabelText('Due date and time'),{target:{value:'2026-10-28T12:00'}});
 fireEvent.click(screen.getByRole('button',{name:'Save reminder'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/reminders','token',expect.objectContaining({method:'POST',body:JSON.stringify({title:'Assessment deadline',due_at:localDueToUtc('2026-10-28T12:00'),application_id:'a1'})})));
 fireEvent.click(screen.getByRole('button',{name:/Due today/}));
 await waitFor(()=>expect(api.mock.calls.some(args=>args[0].includes('bucket=due_today'))).toBe(true));
});
it('shows request failures and supports retry',async()=>{
 api.mockRejectedValueOnce(new Error('Network unavailable')).mockResolvedValue({...listing,items:[],total:0});
 render(<ReminderPanel token="token" onOpen={vi.fn()}/>);
 expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable');
 fireEvent.click(screen.getByRole('button',{name:'Retry reminders'}));
 expect(await screen.findByText(/No overdue reminders/)).toBeVisible();
});
it('preserves the original UTC instant when editing an unchanged local due time',async()=>{
 const save=vi.fn().mockResolvedValue(undefined);
 render(<ReminderForm item={{...reminder,due_at:'2026-11-01T06:30:27Z'}} onSave={save} onCancel={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('Reminder title'),{target:{value:'Updated title'}});
 fireEvent.click(screen.getByRole('button',{name:'Save reminder'}));
 await waitFor(()=>expect(save).toHaveBeenCalledWith({title:'Updated title',due_at:'2026-11-01T06:30:27Z'}));
});
it('represents spring-forward transitions without inventing nonexistent local time',()=>{
 expect(localInputValue('2026-03-08T06:30:00Z','America/Detroit')).toBe('2026-03-08T01:30');
 expect(localInputValue('2026-03-08T07:30:00Z','America/Detroit')).toBe('2026-03-08T03:30');
 if (Intl.DateTimeFormat().resolvedOptions().timeZone==='America/Detroit') {
   expect(()=>localDueToUtc('2026-03-08T02:30')).toThrow('daylight-saving');
 }
});
