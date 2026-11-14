import Link from "next/link";
import {
  AlertTriangle,
  CalendarDays,
  ChevronRight,
  Clock3,
  Loader2,
} from "lucide-react";
import type { MeetingSummary } from "@/lib/api";
import { MeetingPeople } from "@/components/meeting-people";

export function RecordedMeetingCard({
  meeting,
  review = false,
}: {
  meeting: MeetingSummary;
  review?: boolean;
}) {
  const processing = meeting.processing_state === "processing";
  return (
    <article className="recorded-meeting-card">
      <div className="meeting-card-meta">
        <span>
          <CalendarDays className="size-3.5" aria-hidden="true" />
          {new Date(meeting.date).toLocaleDateString(undefined, {
            day: "numeric",
            month: "short",
            year: "numeric",
          })}
        </span>
        {meeting.duration_minutes > 0 && (
          <span>
            <Clock3 className="size-3.5" aria-hidden="true" />
            {meeting.duration_minutes} min
          </span>
        )}
        {meeting.projects[0] && (
          <span className="meeting-project-chip">
            {meeting.projects[0].name}
          </span>
        )}
      </div>
      <h3>
        <Link href={`/meetings/${meeting.id}`}>{meeting.title}</Link>
      </h3>
      {meeting.summary && (
        <p className="meeting-card-summary">{meeting.summary}</p>
      )}
      {processing && (
        <p
          className="mt-2 flex items-center gap-1.5 text-xs text-primary"
          role="status"
        >
          <Loader2 className="size-3 animate-spin" aria-hidden="true" />
          Processing notes
        </p>
      )}
      {meeting.processing_state === "attention" && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-warning">
          <AlertTriangle className="size-3" aria-hidden="true" />
          Needs attention
        </p>
      )}
      <div className="meeting-card-bottom">
        <MeetingPeople names={meeting.attendees.map((person) => person.name)} />
        <Link
          href={`/meetings/${meeting.id}${review && !processing ? "?review=1" : ""}`}
          className="violet-outline"
        >
          {processing
            ? "View progress"
            : review
              ? "Review notes"
              : "Open notes"}
          <ChevronRight className="size-3.5" aria-hidden="true" />
        </Link>
      </div>
    </article>
  );
}
