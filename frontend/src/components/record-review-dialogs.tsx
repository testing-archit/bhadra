"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

function ReviewFooter({ saving, disabled, onCancel, onSave }: { saving: boolean; disabled: boolean; onCancel: () => void; onSave: () => void }) {
  return (
    <DialogFooter>
      <Button variant="outline" onClick={onCancel} disabled={saving}>Cancel</Button>
      <Button onClick={onSave} disabled={saving || disabled}>{saving ? "Saving…" : "Save and verify"}</Button>
    </DialogFooter>
  );
}

export function SummaryReviewDialog({ open, summary, onOpenChange, onSave }: { open: boolean; summary: string; onOpenChange: (open: boolean) => void; onSave: (summary: string) => Promise<void> }) {
  const [value, setValue] = useState(summary);
  const [saving, setSaving] = useState(false);
  async function save() { setSaving(true); try { await onSave(value.trim()); onOpenChange(false); } finally { setSaving(false); } }
  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader><DialogTitle>Review meeting summary</DialogTitle></DialogHeader>
        <div className="grid gap-2 py-2"><Label htmlFor="review-summary">Summary</Label><Textarea id="review-summary" rows={14} value={value} onChange={(event) => setValue(event.target.value)} /></div>
        <ReviewFooter saving={saving} disabled={!value.trim()} onCancel={() => onOpenChange(false)} onSave={() => void save()} />
      </DialogContent>
    </Dialog>
  );
}

export function DecisionReviewDialog({ open, value, onOpenChange, onSave }: { open: boolean; value: { decision: string; reason: string | null; alternatives: string[]; participants: string[] }; onOpenChange: (open: boolean) => void; onSave: (fields: { decision: string; reason: string; alternatives: string[]; participants: string[] }) => Promise<void> }) {
  const [decision, setDecision] = useState(value.decision);
  const [reason, setReason] = useState(value.reason || "");
  const [alternatives, setAlternatives] = useState((value.alternatives ?? []).join(", "));
  const [participants, setParticipants] = useState((value.participants ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  async function save() { setSaving(true); try { const split = (text: string) => text.split(",").map((item) => item.trim()).filter(Boolean); await onSave({ decision: decision.trim(), reason: reason.trim(), alternatives: split(alternatives), participants: split(participants) }); onOpenChange(false); } finally { setSaving(false); } }
  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader><DialogTitle>Review decision</DialogTitle></DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2"><Label htmlFor="review-decision">Decision</Label><Textarea id="review-decision" rows={3} value={decision} onChange={(event) => setDecision(event.target.value)} /></div>
          <div className="grid gap-2"><Label htmlFor="review-reason">Reason</Label><Textarea id="review-reason" rows={3} value={reason} onChange={(event) => setReason(event.target.value)} /></div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2"><div className="grid gap-2"><Label htmlFor="review-alternatives">Rejected alternatives</Label><Input id="review-alternatives" value={alternatives} onChange={(event) => setAlternatives(event.target.value)} placeholder="Comma separated" /></div><div className="grid gap-2"><Label htmlFor="review-participants">Participants</Label><Input id="review-participants" value={participants} onChange={(event) => setParticipants(event.target.value)} placeholder="Comma separated" /></div></div>
        </div>
        <ReviewFooter saving={saving} disabled={!decision.trim()} onCancel={() => onOpenChange(false)} onSave={() => void save()} />
      </DialogContent>
    </Dialog>
  );
}

export function RiskReviewDialog({ open, value, onOpenChange, onSave }: { open: boolean; value: { description: string; severity: string | null }; onOpenChange: (open: boolean) => void; onSave: (fields: { description: string; severity: string }) => Promise<void> }) {
  const [description, setDescription] = useState(value.description);
  const [severity, setSeverity] = useState(value.severity || "Medium");
  const [saving, setSaving] = useState(false);
  async function save() { setSaving(true); try { await onSave({ description: description.trim(), severity }); onOpenChange(false); } finally { setSaving(false); } }
  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>Review risk</DialogTitle></DialogHeader>
        <div className="grid gap-4 py-2"><div className="grid gap-2"><Label htmlFor="review-risk">Risk</Label><Textarea id="review-risk" rows={4} value={description} onChange={(event) => setDescription(event.target.value)} /></div><div className="grid gap-2"><Label>Severity</Label><Select value={severity} onValueChange={(next) => setSeverity(next ?? "Medium")}><SelectTrigger><SelectValue>{(current: string) => current}</SelectValue></SelectTrigger><SelectContent>{["High", "Medium", "Low"].map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent></Select></div></div>
        <ReviewFooter saving={saving} disabled={!description.trim()} onCancel={() => onOpenChange(false)} onSave={() => void save()} />
      </DialogContent>
    </Dialog>
  );
}
