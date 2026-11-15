"use client";
import { useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Check, Quote } from "lucide-react";
import type { EvidenceRef, MeetingDetail, TranscriptSegment } from "@/lib/api";
import { formatMoment } from "@/lib/debrief-strip";
import { meetingMarks } from "./debrief-strip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ListenInLanguage } from "@/components/listen-in-language";

export function MeetingDebrief({meeting,segments,selectedId,onSelect,onEvidence,children}:{
  meeting:MeetingDetail;segments:TranscriptSegment[];selectedId:string|null;
  onSelect:(id:string)=>void;onEvidence:(ref:EvidenceRef)=>void;children:ReactNode;
}){
  const [filter,setFilter]=useState("all"),[summaryOpen,setSummaryOpen]=useState(false);
  const marks=meetingMarks(meeting,segments), mark=marks.find(row=>row.id===selectedId)??marks[0];
  const index=mark?marks.findIndex(row=>row.id===mark.id):-1;
  const rows=[...meeting.decisions.map(row=>({id:row.id,kind:"decision",title:row.decision,detail:row.reason,evidence:row.evidence,verified:!!row.verified_at})),
    ...meeting.tasks.map(row=>({id:row.id,kind:"task",title:row.description,detail:row.owner??"Unassigned",evidence:row.evidence,verified:!!row.verified_at})),
    ...meeting.risks.map(row=>({id:row.id,kind:"risk",title:row.description,detail:row.severity,evidence:row.evidence,verified:false}))];
  const item=mark&&rows.find(row=>row.id===mark.id), evidence=item?.evidence?.[0];
  return <div className="meeting-debrief-grid">
    <section className="work-sheet moment-panel" aria-labelledby="moment-heading"><header className="sheet-heading"><h2 id="moment-heading">Moment.</h2><div className="moment-arrows"><Button variant="ghost" size="icon" aria-label="Previous moment" disabled={!marks.length} onClick={()=>onSelect(marks[(index-1+marks.length)%marks.length].id)}><ChevronLeft/></Button><Button variant="ghost" size="icon" aria-label="Next moment" disabled={!marks.length} onClick={()=>onSelect(marks[(index+1)%marks.length].id)}><ChevronRight/></Button></div></header>
      {item&&mark?<><div className="moment-meta"><Badge variant={mark.kind==="decision"?"mint":mark.kind==="task"?"peach":"rose"}>{mark.kind}</Badge><time>{formatMoment(mark.at_ms)}</time></div><h3>{item.title}</h3>{evidence&&<><span className="moment-speaker">{evidence.speaker}</span><button className="moment-quote" onClick={()=>onEvidence(evidence)}><Quote className="size-4" aria-hidden="true"/><span>“{evidence.excerpt}”</span></button></>}</>:<p className="text-sm text-muted-foreground">No sourced moments yet.</p>}
      <div className="moment-listen"><ListenInLanguage text={meeting.summary??""} title={meeting.title} compact onListen={()=>setSummaryOpen(true)}/>{summaryOpen&&<p className="moment-summary">{meeting.summary}</p>}</div>
    </section>
    {children}
    <section className="work-sheet outcome-panel" aria-labelledby="outcomes-heading"><header className="sheet-heading"><h2 id="outcomes-heading">Out of this meeting.</h2><span>{rows.length}</span></header>
      <ToggleGroup value={[filter]} onValueChange={values=>{if(values[0])setFilter(values[0]);}} aria-label="Filter meeting outcomes" className="outcome-filters"><ToggleGroupItem value="all">All</ToggleGroupItem><ToggleGroupItem value="decision">Decisions</ToggleGroupItem><ToggleGroupItem value="task">Tasks</ToggleGroupItem></ToggleGroup>
      <ul>{rows.filter(row=>filter==="all"||row.kind===filter).map(row=><li key={row.id}><button id={`outcome-${row.id}`} className="outcome-row" aria-pressed={mark?.id===row.id} onClick={()=>onSelect(row.id)}><span className="outcome-kind">{row.kind==="decision"?"D":row.kind==="task"?"T":"R"}</span><span><strong>{row.title}</strong><small>{row.detail}</small></span>{row.verified&&<Check className="size-4" aria-label="Confirmed"/>}</button></li>)}</ul>
      {rows.length===0&&<p className="text-sm text-muted-foreground">No items yet.</p>}
    </section>
  </div>;
}
