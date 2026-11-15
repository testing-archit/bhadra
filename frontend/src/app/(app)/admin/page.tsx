"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api, AdminAccount, AdminAuditEvent, AdminOverview, AdminTeam, ApiError,
  DecisionChurn, DepartmentUsage, Trace, UsageSummary,
} from "@/lib/api";
import { gnaniCostUsd } from "@/lib/pricing";
import { AdminMeetings } from "@/components/admin-meetings";
import { AdminAiCosts } from "@/components/admin-ai-costs";
import { AdminJira } from "@/components/admin-jira";
import { AdminNotetaker } from "@/components/admin-notetaker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Activity, ArrowDownToLine, ArrowUpFromLine, Ban, Building2, CheckCircle2,
  CircleDollarSign, KeyRound, Lock, Pencil, Plus, RefreshCw, Search,
  ShieldCheck, Sparkles, Trash2, UserCheck, Users, Video, XCircle,
} from "lucide-react";
import "../support-pages.css";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super admin", admin: "Admin", team_admin: "Team admin", member: "Member",
};

function estimateCostInr(usage: { ai_input_tokens: number; ai_output_tokens: number; duration_minutes: number; transcription_requests: number }, usdToInr: number) {
  const usd = (usage.ai_input_tokens / 1_000_000) * 0.3 + (usage.ai_output_tokens / 1_000_000) * 2.5 + gnaniCostUsd(usage.duration_minutes, usage.transcription_requests);
  return (usd * usdToInr).toFixed(2);
}

function relativeTime(value: string | null) {
  if (!value) return "No activity yet";
  const delta = Date.now() - new Date(value).getTime();
  if (delta < 60_000) return "Just now";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
  return new Date(value).toLocaleDateString();
}

type AccountForm = { name: string; email: string; password: string; role: string; status: string; job_title: string; team_id: string; department: string };
const EMPTY_ACCOUNT: AccountForm = { name: "", email: "", password: "", role: "member", status: "active", job_title: "", team_id: "", department: "" };

export default function AdminPage() {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [teams, setTeams] = useState<AdminTeam[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [churn, setChurn] = useState<DecisionChurn | null>(null);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [audit, setAudit] = useState<AdminAuditEvent[]>([]);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [accountOpen, setAccountOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<AdminAccount | null>(null);
  const [accountForm, setAccountForm] = useState<AccountForm>(EMPTY_ACCOUNT);
  const [teamOpen, setTeamOpen] = useState(false);
  const [editingTeam, setEditingTeam] = useState<AdminTeam | null>(null);
  const [teamForm, setTeamForm] = useState({ name: "", description: "" });
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState("overview");

  // Deep links such as /admin?tab=notetaker from an admin notification.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("tab");
    if (requested) setTab(requested);
  }, []);

  async function loadAll() {
    try {
      const [o, a, tm, u, c, tr, au] = await Promise.all([
        api.adminOverview(), api.adminAccounts(), api.adminTeams(), api.adminUsageSummary(),
        api.adminDecisionChurn(), api.adminTraces(), api.adminAuditEvents(),
      ]);
      setOverview(o); setAccounts(a); setTeams(tm); setUsage(u); setChurn(c); setTraces(tr); setAudit(au);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 403) setForbidden(true);
      else setError(cause instanceof Error ? cause.message : "Admin data could not be loaded");
    }
  }

  useEffect(() => { void loadAll(); }, []);

  const filteredAccounts = useMemo(() => accounts.filter((account) => {
    const haystack = `${account.name} ${account.email} ${account.team_name} ${account.job_title}`.toLowerCase();
    return haystack.includes(search.toLowerCase()) && (roleFilter === "all" || account.role === roleFilter) && (statusFilter === "all" || account.status === statusFilter);
  }), [accounts, roleFilter, search, statusFilter]);

  function createAccount() { setEditingAccount(null); setAccountForm(EMPTY_ACCOUNT); setAccountOpen(true); }
  function editAccount(account: AdminAccount) {
    setEditingAccount(account);
    setAccountForm({ name: account.name ?? "", email: account.email, password: "", role: account.role === "super_admin" ? "admin" : account.role, status: account.status, job_title: account.job_title ?? "", team_id: account.team_id ?? "", department: account.department ?? "" });
    setAccountOpen(true);
  }
  async function saveAccount() {
    setSaving(true); setError(null);
    try {
      const body = { ...accountForm, team_id: accountForm.team_id || null, job_title: accountForm.job_title || null, department: accountForm.department || null, ...(accountForm.password ? {} : { password: undefined }) };
      if (editingAccount) await api.adminUpdateAccount(editingAccount.id, body);
      else await api.adminCreateAccount(body);
      setAccountOpen(false); setNotice(editingAccount ? "Account updated" : "Account created"); await loadAll();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Account could not be saved"); }
    finally { setSaving(false); }
  }
  async function toggleAccount(account: AdminAccount) {
    try { await api.adminUpdateAccount(account.id, { status: account.status === "active" ? "suspended" : "active" }); setNotice(account.status === "active" ? "Account suspended" : "Account reactivated"); await loadAll(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Status could not be changed"); }
  }
  function createTeam() { setEditingTeam(null); setTeamForm({ name: "", description: "" }); setTeamOpen(true); }
  function editTeam(team: AdminTeam) { setEditingTeam(team); setTeamForm({ name: team.name, description: team.description ?? "" }); setTeamOpen(true); }
  async function saveTeam() {
    setSaving(true);
    try { if (editingTeam) await api.adminUpdateTeam(editingTeam.id, teamForm); else await api.adminCreateTeam(teamForm); setTeamOpen(false); setNotice(editingTeam ? "Team updated" : "Team created"); await loadAll(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Team could not be saved"); }
    finally { setSaving(false); }
  }
  async function deleteTeam(team: AdminTeam) {
    if (!window.confirm(`Delete ${team.name}? Members will become unassigned.`)) return;
    try { await api.adminDeleteTeam(team.id); setNotice("Team deleted"); await loadAll(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Team could not be deleted"); }
  }

  if (forbidden) return <div className="signal-support grid min-h-[60vh] place-items-center"><div className="max-w-md text-center"><Lock className="mx-auto mb-4 h-9 w-9 text-muted-foreground"/><h1 className="text-xl font-semibold">Admin access required</h1><p className="mt-2 text-sm text-muted-foreground">Your account does not have an administrative role.</p></div></div>;

  return (
    <div className="signal-support flex w-full flex-col gap-5 pb-10">
      <div className="support-hero flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Workspace control</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">People, teams, usage and the audit trail for your Wilco workspace.</p>
        </div>
        <div className="flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2">
          <span className="size-2 rounded-full bg-primary" />
          <div><p className="text-xs font-medium">Workspace activity</p><p className="text-[11px] text-muted-foreground">Last activity {relativeTime(overview?.last_activity_at ?? null)}</p></div>
        </div>
      </div>

      {(error || notice) && <div className={`flex items-center justify-between rounded-xl border px-4 py-3 text-sm ${error ? "border-destructive/30 bg-destructive/5 text-destructive" : "border-success/40 bg-success/10 text-foreground"}`}><span>{error || notice}</span><button onClick={() => { setError(null); setNotice(null); }}><XCircle className="h-4 w-4"/></button></div>}

      <Tabs value={tab} onValueChange={(value) => setTab(String(value))} className="gap-5">
        <TabsList className="h-auto! w-full flex-wrap justify-start rounded-xl border bg-card p-1 shadow-sm">
          <TabsTrigger value="overview">Overview</TabsTrigger><TabsTrigger value="people">People <span className="ml-1 text-[10px] opacity-55">{accounts.length}</span></TabsTrigger><TabsTrigger value="teams">Teams <span className="ml-1 text-[10px] opacity-55">{teams.length}</span></TabsTrigger><TabsTrigger value="intelligence">Intelligence</TabsTrigger><TabsTrigger value="meetings">All meetings</TabsTrigger><TabsTrigger value="notetaker">Notetaker</TabsTrigger><TabsTrigger value="ai-spend">AI spend</TabsTrigger><TabsTrigger value="integrations">Integrations</TabsTrigger><TabsTrigger value="audit">Audit log</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-5">
          {!overview ? <Skeleton className="h-40"/> : <>
            <div className="grid grid-cols-1 gap-px overflow-hidden rounded-2xl border bg-border sm:grid-cols-2 xl:grid-cols-5">
              <Metric icon={Users} label="People" value={overview.total_users} note={`${overview.active_users} active`} />
              <Metric icon={Building2} label="Teams" value={overview.teams} note="Operating groups" />
              <Metric icon={Video} label="Meetings" value={overview.meetings} note="Available to memory" />
              <Metric icon={Sparkles} label="AI operations" value={usage?.meetings_processed ?? 0} note={`₹${usage ? estimateCostInr(usage, usage.exchange_rate.usd_to_inr) : "0.00"} estimated`} />
              <Metric icon={overview.failed_operations ? XCircle : CheckCircle2} label="Failures" value={overview.failed_operations} note={overview.failed_operations ? "Needs review" : "No current issues"} danger={overview.failed_operations > 0}/>
            </div>
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_.8fr]">
              <Card><CardHeader><CardTitle className="text-base">Organization pulse</CardTitle><p className="text-xs text-muted-foreground">Adoption and governance signals that need attention.</p></CardHeader><CardContent className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Pulse label="Account coverage" value={`${overview.active_users}/${overview.total_users} active`} state={overview.suspended_users ? `${overview.suspended_users} suspended` : "All accounts active"}/>
                <Pulse label="Team coverage" value={`${accounts.filter(a => a.team_id).length}/${accounts.length} assigned`} state={`${accounts.filter(a => !a.team_id).length} unassigned`}/>
                <Pulse label="Admin exposure" value={`${accounts.filter(a => ["admin","super_admin"].includes(a.role)).length} admins`} state="Review quarterly"/>
                <Pulse label="Decision stability" value={`${Math.round((churn?.churn_rate ?? 0) * 100)}% churn`} state={`${churn?.conflicted_decisions ?? 0} conflicts detected`}/>
              </CardContent></Card>
              <Card><CardHeader><CardTitle className="text-base">Service health</CardTitle><p className="text-xs text-muted-foreground">Core dependencies used by Wilco.</p></CardHeader><CardContent className="space-y-1">{overview.services.map(service => <div key={service.name} className="flex items-center justify-between border-b py-3 last:border-0"><span className="text-sm font-medium">{service.name}</span><span className="flex items-center gap-2 text-xs text-success"><CheckCircle2 className="h-3.5 w-3.5"/> Operational</span></div>)}</CardContent></Card>
            </div>
          </>}
        </TabsContent>

        <TabsContent value="people" className="space-y-4">
          <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end"><div><h2 className="text-xl font-semibold tracking-tight">People and access</h2><p className="mt-1 text-sm text-muted-foreground">Create accounts, assign least-privilege roles and control access.</p></div><Button onClick={createAccount}><Plus className="h-4 w-4"/> Create account</Button></div>
          <div className="flex flex-col gap-2 rounded-xl border bg-card p-3 sm:flex-row"><div className="relative flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"/><Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search name, email, team or title" className="pl-9"/></div><select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} className="h-8 rounded-lg border bg-card px-3 text-sm"><option value="all">All roles</option><option value="member">Members</option><option value="team_admin">Team admins</option><option value="admin">Admins</option><option value="super_admin">Super admins</option></select><select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="h-8 rounded-lg border bg-card px-3 text-sm"><option value="all">All status</option><option value="active">Active</option><option value="suspended">Suspended</option></select></div>
          <div className="overflow-x-auto rounded-xl border bg-card"><table className="w-full min-w-[900px] text-sm"><thead className="bg-muted/50 text-left text-[11px] uppercase tracking-wider text-muted-foreground"><tr><th className="px-4 py-3">Person</th><th>Team</th><th>Role</th><th>Status</th><th>Authentication</th><th>Last activity</th><th className="pr-4 text-right">Actions</th></tr></thead><tbody className="divide-y">{filteredAccounts.map(account => <tr key={account.id} className="group hover:bg-muted/50"><td className="px-4 py-3"><div className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-full bg-accent text-xs font-semibold text-foreground">{(account.name || account.email).slice(0,2).toUpperCase()}</span><div><p className="font-medium text-foreground">{account.name || "Unnamed account"}</p><p className="text-xs text-muted-foreground">{account.email}{account.job_title ? ` · ${account.job_title}` : ""}</p></div></div></td><td>{account.team_name || <span className="text-muted-foreground">Unassigned</span>}</td><td><Badge variant="outline">{ROLE_LABELS[account.role] || account.role}</Badge></td><td><span className={`inline-flex items-center gap-1.5 text-xs font-medium ${account.status === "active" ? "text-success" : "text-warning"}`}><span className={`h-1.5 w-1.5 rounded-full ${account.status === "active" ? "bg-success" : "bg-warning"}`}/>{account.status}</span></td><td className="text-xs text-muted-foreground">{account.auth_method}</td><td className="text-xs text-muted-foreground">{relativeTime(account.last_activity_at)}</td><td className="pr-4"><div className="flex justify-end gap-1"><Button variant="ghost" size="icon-sm" onClick={() => editAccount(account)} aria-label={`Edit ${account.name}`}><Pencil className="h-3.5 w-3.5"/></Button><Button variant="ghost" size="icon-sm" disabled={account.role === "super_admin"} onClick={() => void toggleAccount(account)} aria-label={account.status === "active" ? "Suspend account" : "Reactivate account"}>{account.status === "active" ? <Ban className="h-3.5 w-3.5"/> : <UserCheck className="h-3.5 w-3.5"/>}</Button></div></td></tr>)}</tbody></table>{filteredAccounts.length === 0 && <p className="p-10 text-center text-sm text-muted-foreground">No accounts match these filters.</p>}</div>
        </TabsContent>

        <TabsContent value="teams" className="space-y-4">
          <div className="flex items-end justify-between gap-4"><div><h2 className="text-xl font-semibold tracking-tight">Teams</h2><p className="mt-1 text-sm text-muted-foreground">Organize access and ownership around your engineering and product teams.</p></div><Button onClick={createTeam}><Plus className="h-4 w-4"/> Create team</Button></div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{teams.map(team => <Card key={team.id} className="group"><CardHeader className="pb-3"><div className="flex items-start justify-between"><span className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-foreground"><Building2 className="h-4 w-4"/></span><div className="flex opacity-0 transition-opacity group-hover:opacity-100"><Button size="icon-sm" variant="ghost" onClick={() => editTeam(team)}><Pencil className="h-3.5 w-3.5"/></Button><Button size="icon-sm" variant="ghost" className="hover:text-destructive" onClick={() => void deleteTeam(team)}><Trash2 className="h-3.5 w-3.5"/></Button></div></div><CardTitle className="mt-3 text-base">{team.name}</CardTitle><p className="min-h-10 text-xs leading-5 text-muted-foreground">{team.description || "No description yet."}</p></CardHeader><CardContent className="flex items-center justify-between border-t pt-4"><span className="flex items-center gap-2 text-xs text-muted-foreground"><Users className="h-3.5 w-3.5"/>{team.member_count} member{team.member_count === 1 ? "" : "s"}</span><span className="text-[10px] text-muted-foreground">Created {new Date(team.created_at).toLocaleDateString()}</span></CardContent></Card>)}{teams.length === 0 && <button onClick={createTeam} className="grid min-h-52 place-items-center rounded-xl border border-dashed bg-card text-sm text-muted-foreground hover:border-primary hover:text-primary"><span className="flex flex-col items-center gap-2"><Plus className="h-5 w-5"/> Create the first team</span></button>}</div>
        </TabsContent>

        <TabsContent value="intelligence" className="space-y-5">
          <div><h2 className="text-xl font-semibold tracking-tight">Usage intelligence</h2><p className="mt-1 text-sm text-muted-foreground">AI consumption, operational outcomes and decision quality.</p></div>
          <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-2 lg:grid-cols-4"><Metric icon={Video} label="Processed" value={usage?.meetings_processed ?? 0}/><Metric icon={ArrowDownToLine} label="Input tokens" value={(usage?.ai_input_tokens ?? 0).toLocaleString()}/><Metric icon={ArrowUpFromLine} label="Output tokens" value={(usage?.ai_output_tokens ?? 0).toLocaleString()}/><Metric icon={CircleDollarSign} label="Est. spend" value={`₹${usage ? estimateCostInr(usage, usage.exchange_rate.usd_to_inr) : "0.00"}`} note={usage ? `1 USD = ₹${usage.exchange_rate.usd_to_inr.toFixed(2)} · ${usage.exchange_rate.live ? usage.exchange_rate.source : "fallback rate"}` : undefined}/></div>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2"><Card><CardHeader><CardTitle className="text-base">Cost by department</CardTitle></CardHeader><CardContent className="space-y-1">{usage?.by_department.map((dept: DepartmentUsage) => <div key={dept.department} className="grid grid-cols-[1fr_auto_auto] items-center gap-4 border-b py-3 last:border-0"><div><p className="text-sm font-medium">{dept.department}</p><p className="text-[10px] text-muted-foreground">{dept.meetings_processed} operations · {dept.duration_minutes} recorded min</p></div><span className="text-xs text-muted-foreground">{dept.ai_input_tokens.toLocaleString()} tokens</span><span className="w-20 text-right text-sm font-semibold">₹{estimateCostInr(dept, usage.exchange_rate.usd_to_inr)}</span></div>)}</CardContent></Card><Card><CardHeader><CardTitle className="text-base">Decision stability</CardTitle></CardHeader><CardContent><div className="flex items-end gap-3"><span className="text-4xl font-semibold tracking-tight">{Math.round((churn?.churn_rate ?? 0)*100)}%</span><span className="pb-1 text-xs text-muted-foreground">churn across {churn?.total_decisions ?? 0} decisions</span></div><div className="mt-5 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full bg-warning" style={{width:`${Math.min(100,(churn?.churn_rate ?? 0)*100)}%`}}/></div><p className="mt-3 text-xs leading-5 text-muted-foreground">{churn?.conflicted_decisions ?? 0} decisions were later contradicted or reversed. Lower is more stable.</p></CardContent></Card></div>
          <Card><CardHeader><CardTitle className="text-base">Recent operations</CardTitle></CardHeader><CardContent className="overflow-x-auto"><table className="w-full min-w-[700px] text-sm"><thead className="text-left text-[10px] uppercase tracking-wider text-muted-foreground"><tr><th className="pb-3">Operation</th><th>Status</th><th>Duration</th><th>Tasks</th><th>Decisions</th><th>When</th></tr></thead><tbody className="divide-y">{traces.slice(0,30).map(trace => <tr key={trace.id}><td className="py-3 font-medium">{trace.meeting_title}</td><td><Badge variant={trace.status === "success" ? "outline" : "destructive"}>{trace.status}</Badge></td><td>{trace.duration_minutes} min</td><td>{trace.tasks_found}</td><td>{trace.decisions_found}</td><td className="text-xs text-muted-foreground">{relativeTime(trace.created_at)}</td></tr>)}</tbody></table></CardContent></Card>
        </TabsContent>

        <TabsContent value="meetings"><AdminMeetings /></TabsContent>
        <TabsContent value="notetaker"><AdminNotetaker /></TabsContent>
        <TabsContent value="ai-spend"><AdminAiCosts /></TabsContent>
        <TabsContent value="integrations"><AdminJira /></TabsContent>

        <TabsContent value="audit" className="space-y-4"><div><h2 className="text-xl font-semibold tracking-tight">Administrative audit log</h2><p className="mt-1 text-sm text-muted-foreground">A durable record of access, role and team changes.</p></div><div className="overflow-hidden rounded-xl border bg-card">{audit.length === 0 ? <div className="grid min-h-52 place-items-center text-center"><div><Activity className="mx-auto mb-2 h-5 w-5 text-muted-foreground"/><p className="text-sm font-medium">No administrative changes yet</p><p className="mt-1 text-xs text-muted-foreground">New account and team changes will appear here.</p></div></div> : <div className="divide-y">{audit.map(event => <div key={event.id} className="grid grid-cols-1 gap-2 px-4 py-3 sm:grid-cols-[36px_1fr_auto]"><span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-foreground"><Activity className="h-3.5 w-3.5"/></span><div><p className="text-sm"><span className="font-medium">{event.actor_email}</span> <span className="text-muted-foreground">{event.action.replace(".", " ")}</span></p><p className="mt-0.5 text-[10px] text-muted-foreground">{event.target_type} · {event.target_id}</p></div><span className="text-xs text-muted-foreground">{new Date(event.created_at).toLocaleString()}</span></div>)}</div>}</div></TabsContent>
      </Tabs>

      <Dialog open={accountOpen} onOpenChange={setAccountOpen}><DialogContent className="sm:max-w-xl"><DialogHeader><DialogTitle>{editingAccount ? "Edit account" : "Create account"}</DialogTitle><DialogDescription>{editingAccount ? "Update access, team and profile details. Leave password blank to keep it unchanged." : "Create a password account and place it in the right team with the least access needed."}</DialogDescription></DialogHeader><div className="grid grid-cols-1 gap-4 py-1 sm:grid-cols-2"><Field label="Full name"><Input value={accountForm.name} onChange={e=>setAccountForm({...accountForm,name:e.target.value})}/></Field><Field label="Email"><Input type="email" value={accountForm.email} disabled={!!editingAccount} onChange={e=>setAccountForm({...accountForm,email:e.target.value})}/></Field><Field label={editingAccount ? "New password (optional)" : "Temporary password"}><Input type="password" value={accountForm.password} onChange={e=>setAccountForm({...accountForm,password:e.target.value})}/></Field><Field label="Job title"><Input value={accountForm.job_title} onChange={e=>setAccountForm({...accountForm,job_title:e.target.value})}/></Field><Field label="Role"><select className="h-8 w-full rounded-lg border bg-card px-2 text-sm" value={accountForm.role} disabled={editingAccount?.role === "super_admin"} onChange={e=>setAccountForm({...accountForm,role:e.target.value})}><option value="member">Member</option><option value="team_admin">Team admin</option><option value="admin">Admin</option></select></Field><Field label="Status"><select className="h-8 w-full rounded-lg border bg-card px-2 text-sm" value={accountForm.status} disabled={editingAccount?.role === "super_admin"} onChange={e=>setAccountForm({...accountForm,status:e.target.value})}><option value="active">Active</option><option value="suspended">Suspended</option></select></Field><Field label="Team"><select className="h-8 w-full rounded-lg border bg-card px-2 text-sm" value={accountForm.team_id} onChange={e=>setAccountForm({...accountForm,team_id:e.target.value})}><option value="">Unassigned</option>{teams.map(team=><option key={team.id} value={team.id}>{team.name}</option>)}</select></Field><Field label="Department"><Input value={accountForm.department} onChange={e=>setAccountForm({...accountForm,department:e.target.value})}/></Field></div><DialogFooter><Button variant="outline" onClick={()=>setAccountOpen(false)}>Cancel</Button><Button disabled={saving || !accountForm.name || !accountForm.email || (!editingAccount && accountForm.password.length < 8)} onClick={()=>void saveAccount()}>{saving ? <RefreshCw className="h-4 w-4 animate-spin"/> : <KeyRound className="h-4 w-4"/>}{editingAccount ? "Save changes" : "Create account"}</Button></DialogFooter></DialogContent></Dialog>
      <Dialog open={teamOpen} onOpenChange={setTeamOpen}><DialogContent><DialogHeader><DialogTitle>{editingTeam ? "Edit team" : "Create team"}</DialogTitle><DialogDescription>Teams organize ownership and make access boundaries easier to understand.</DialogDescription></DialogHeader><Field label="Team name"><Input value={teamForm.name} onChange={e=>setTeamForm({...teamForm,name:e.target.value})}/></Field><Field label="Description"><Textarea rows={3} value={teamForm.description} onChange={e=>setTeamForm({...teamForm,description:e.target.value})}/></Field><DialogFooter><Button variant="outline" onClick={()=>setTeamOpen(false)}>Cancel</Button><Button disabled={saving || teamForm.name.trim().length < 2} onClick={()=>void saveTeam()}>{saving ? "Saving…" : editingTeam ? "Save changes" : "Create team"}</Button></DialogFooter></DialogContent></Dialog>
    </div>
  );
}

function Metric({ icon: Icon, label, value, note, danger=false }: { icon: typeof Users; label: string; value: string | number; note?: string; danger?: boolean }) { return <div className="bg-card p-5"><div className="flex items-center justify-between"><span className="text-[10px] font-semibold uppercase tracking-[.14em] text-muted-foreground">{label}</span><Icon className={`h-4 w-4 ${danger ? "text-destructive" : "text-foreground"}`}/></div><p className="mt-3 text-2xl font-semibold tracking-tight">{value}</p>{note && <p className={`mt-1 text-[10px] ${danger ? "text-destructive" : "text-muted-foreground"}`}>{note}</p>}</div>; }
function Pulse({ label, value, state }: { label: string; value: string; state: string }) { return <div className="rounded-xl border bg-muted/50 p-4"><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p><p className="mt-2 text-lg font-semibold">{value}</p><p className="mt-1 text-xs text-muted-foreground">{state}</p></div>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <div className="grid gap-1.5"><Label>{label}</Label>{children}</div>; }
