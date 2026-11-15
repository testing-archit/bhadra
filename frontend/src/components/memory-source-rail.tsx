"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { api, type ChatSource, type MeetingSummary, type TranscriptSegment } from "@/lib/api";
import { DebriefStrip } from "@/components/meeting/debrief-strip";
import { formatMoment } from "@/lib/debrief-strip";

export const memorySourceKey=(source:ChatSource)=>source.tag??source.meeting_id??source.meeting_title;
export function MemorySourceRail({sources,meetings,selected,onSelect,onAsk,busy}:{
  sources:ChatSource[];meetings:MeetingSummary[];selected:{key:string;seq?:number}|null;
  onSelect:(source:ChatSource)=>void;onAsk:(question:string)=>void;busy:boolean;
}){
  const [timings,setTimings]=useState<Record<string,TranscriptSegment[]>>({});
  const recent=!sources.length;
  const shown=recent?meetings.slice(0,3).map(row=>({meeting_id:row.id,meeting_title:row.title,meeting_date:row.date} as ChatSource)):sources;
  const ids=[...new Set(shown.flatMap(source=>source.meeting_id?[source.meeting_id]:[]))].join(",");
  useEffect(()=>{
    let active=true;
    for(const id of ids.split(",").filter(Boolean))if(!timings[id])void api.getTranscript(id,{limit:500}).then(page=>{if(active)setTimings(value=>({...value,[id]:page.segments}));}).catch(()=>{});
    return()=>{active=false;};
    // Timing reads are cached per accessible meeting, independent of selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[ids]);
  return <aside className="memory-source-rail"><section className="work-sheet memory-sources-sheet" aria-labelledby="memory-sources-heading"><header className="sheet-heading"><h2 id="memory-sources-heading">{recent?"Recent meetings.":"Sources."}</h2><span>{shown.length}</span></header>
    {shown.map((source,index)=>{
      const key=memorySourceKey(source),isSelected=selected?.key===key;
      const ref=source.segments?.find(row=>isSelected&&row.seq===selected.seq)??source.segments?.[0];
      const segments=source.meeting_id?timings[source.meeting_id]??[]:[];
      const duration=meetings.find(row=>row.id===source.meeting_id)?.duration_minutes;
      const sourcePath=source.meeting_id?`/meetings/${source.meeting_id}${ref?.segment_id?`?segment=${encodeURIComponent(ref.segment_id)}${ref.start_ms!==null?`&t=${ref.start_ms}`:""}`:""}`:null;
      const timed=ref?.segment_id&&segments.find(row=>row.id===ref.segment_id&&row.start_ms!==null);
      return <article key={key} id={`memory-source-${key}`} className="memory-source-card" data-selected={isSelected} data-dimmed={!!selected&&!isSelected}>
        <button className="memory-source-select" onClick={()=>onSelect(source)} aria-pressed={isSelected}><span>{recent?<ArrowUpRight className="size-4"/>:source.tag?.replace("M","")??index+1}</span><strong>{source.meeting_title}</strong></button>
        <span className="memory-source-date">{new Date(source.meeting_date).toLocaleDateString("en-IN",{day:"numeric",month:"short",timeZone:"Asia/Kolkata"})}{ref?.start_ms!==null&&ref?.start_ms!==undefined?` · ${formatMoment(ref.start_ms)}`:""}</span>
        <DebriefStrip size="sm" segments={segments} duration_ms={duration?duration*60000:Math.max(0,...segments.map(row=>row.end_ms??0))} marks={timed?[{id:ref!.segment_id!,at_ms:timed.start_ms!,kind:"decision",label:ref!.excerpt,segmentId:ref!.segment_id!}]:[]}/>
        {ref&&<blockquote>“{ref.excerpt}”</blockquote>}
        {sourcePath&&<Link href={sourcePath} className="memory-source-open">Open meeting<ArrowUpRight className="size-3"/></Link>}
      </article>;
    })}
    {!shown.length&&<p className="text-sm text-muted-foreground">Your meeting sources will appear here.</p>}
  </section><section className="ink-panel memory-related"><h2>Related.</h2>{["What changed since that decision?","Who owns the follow-ups?","Which risks remain?"].map(question=><button key={question} disabled={busy} onClick={()=>onAsk(question)}>{question}<ArrowUpRight className="size-4"/></button>)}</section></aside>;
}
