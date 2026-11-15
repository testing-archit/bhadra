"use client";

import { buildStrip, formatMoment, type DebriefMark, type StripSegment } from "@/lib/debrief-strip";
import type { MeetingDetail, TranscriptSegment } from "@/lib/api";
import { cn } from "@/lib/utils";

export function meetingMarks(meeting: Pick<MeetingDetail, "tasks" | "decisions" | "risks">, segments: TranscriptSegment[]): DebriefMark[] {
  const timed = new Map(segments.filter(s=>s.start_ms!==null).map(s=>[s.id,s]));
  return ([...meeting.tasks.map(item=>({item,kind:"task" as const,label:item.description})),
    ...meeting.decisions.map(item=>({item,kind:"decision" as const,label:item.decision})),
    ...meeting.risks.map(item=>({item,kind:"risk" as const,label:item.description}))]).flatMap(({item,kind,label})=>{
      const evidence=item.evidence?.[0], segment=evidence && timed.get(evidence.segment_id);
      return segment ? [{id:item.id,at_ms:segment.start_ms!,kind,label,segmentId:segment.id}] : [];
    }).sort((a,b)=>a.at_ms-b.at_ms);
}

export function DebriefStrip({ segments, marks=[], duration_ms, variant="sheet", size="md", selectedId, onMarkClick }: {
  segments: StripSegment[]; marks?: DebriefMark[]; duration_ms: number;
  variant?: "ink" | "sheet"; size?: "sm" | "md" | "lg"; selectedId?: string | null;
  onMarkClick?: (mark: DebriefMark) => void;
}) {
  const strip=buildStrip(segments,marks,duration_ms,size==="sm"?40:size==="md"?64:120);
  if(!strip) return null;
  return <div className={cn("debrief-strip",`debrief-${variant}`,`debrief-${size}`)}>
    <div className="debrief-track">
      <div className="debrief-bars" aria-hidden="true">{strip.bars.map((height,index)=><i key={index} style={{height:`${height*100}%`}}/>)}</div>
      {strip.marks.map(mark=>onMarkClick ? <button key={mark.id} className="debrief-tick" style={{left:`${mark.position}%`}} aria-label={`${formatMoment(mark.at_ms)} ${mark.kind}: ${mark.label}`} aria-pressed={selectedId===mark.id} onClick={()=>onMarkClick(mark)}/> : <i key={mark.id} className="debrief-tick" aria-hidden="true" style={{left:`${mark.position}%`}}/>) }
    </div>
    {size==="lg"&&<><div className="debrief-axis" aria-hidden="true"><span>00:00</span><span>{formatMoment(duration_ms/2)}</span><span>{formatMoment(duration_ms)}</span></div><ul className="debrief-mark-list" aria-label="Meeting moments">{strip.marks.map(mark=><li key={mark.id}><button onClick={()=>onMarkClick?.(mark)} aria-pressed={selectedId===mark.id}><time>{formatMoment(mark.at_ms)}</time><span>{mark.kind}</span>{mark.label}</button></li>)}</ul></>}
  </div>;
}
