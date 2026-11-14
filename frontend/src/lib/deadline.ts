const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];

function startOfDay(d: Date): Date {
  const copy = new Date(d);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

function nextWeekday(from: Date, targetDay: number, forceNextWeek: boolean): Date {
  const result = startOfDay(from);
  let diff = (targetDay - result.getDay() + 7) % 7;
  if (forceNextWeek) diff += 7;
  result.setDate(result.getDate() + diff);
  return result;
}

function endOfWeek(from: Date): Date {
  // "this week" resolves to the coming Friday, the common EOW deadline in
  // the transcripts this app extracts from.
  return nextWeekday(from, 5, false);
}

function endOfMonth(from: Date): Date {
  return new Date(from.getFullYear(), from.getMonth() + 1, 0);
}

/**
 * Best-effort resolution of the free-text `dueDate` Gemini extracts
 * ("Friday", "next Wednesday", "EOD", "by month end") into an absolute date
 * relative to the meeting's date. Returns null when the phrase doesn't match
 * a known pattern — callers should treat that as "unknown", not "overdue".
 */
export function parseRelativeDeadline(deadline: string, meetingDate: string): Date | null {
  const text = deadline.trim().toLowerCase();
  if (!text) return null;

  const meeting = startOfDay(new Date(meetingDate));
  if (isNaN(meeting.getTime())) return null;

  if (/\b(today|eod|cob|end of day)\b/.test(text)) return meeting;
  if (/\btomorrow\b/.test(text)) {
    const d = new Date(meeting);
    d.setDate(d.getDate() + 1);
    return d;
  }
  if (/\b(this week|end of week|eow)\b/.test(text)) return endOfWeek(meeting);
  if (/\bnext week\b/.test(text)) {
    const d = endOfWeek(meeting);
    d.setDate(d.getDate() + 7);
    return d;
  }
  if (/\b(month end|end of month|eom)\b/.test(text)) return endOfMonth(meeting);

  for (let i = 0; i < WEEKDAYS.length; i++) {
    if (text.includes(WEEKDAYS[i])) {
      const forceNextWeek = /\bnext\b/.test(text);
      return nextWeekday(meeting, i, forceNextWeek);
    }
  }

  // Explicit dates: "2026-03-15", "15/03/2026", "March 15", "15 March 2026"
  const isoMatch = text.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (isoMatch) {
    const [, y, m, d] = isoMatch;
    const parsed = new Date(Number(y), Number(m) - 1, Number(d));
    if (!isNaN(parsed.getTime())) return parsed;
  }

  const slashMatch = text.match(/(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?/);
  if (slashMatch) {
    const [, a, b, y] = slashMatch;
    const year = y ? (y.length === 2 ? 2000 + Number(y) : Number(y)) : meeting.getFullYear();
    // Ambiguous day/month order — assume day-first (matches the Indian
    // business context this extraction prompt is tuned for).
    const parsed = new Date(year, Number(b) - 1, Number(a));
    if (!isNaN(parsed.getTime())) return parsed;
  }

  const monthNameMatch = text.match(
    /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})|(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/
  );
  if (monthNameMatch) {
    const parsed = new Date(`${monthNameMatch[0]} ${meeting.getFullYear()}`);
    if (!isNaN(parsed.getTime())) return parsed;
  }

  return null;
}

export function isTaskOverdue(
  deadline: string | null,
  meetingDate: string,
  status: string,
  dueDate?: string | null
): boolean {
  if (status === "done") return false;
  // A real resolved due_date (see backend's ai_extractor.py) is authoritative
  // when present — no need for the free-text heuristic below, which exists
  // only because older/manual tasks may not have one.
  if (dueDate) {
    // A bare YYYY-MM-DD is a calendar day; new Date() would read it as UTC
    // midnight, the previous day west of UTC (a task due today: "overdue").
    const [year, month, day] = dueDate.split("-").map(Number);
    const parsed = startOfDay(year && month && day ? new Date(year, month - 1, day) : new Date(dueDate));
    return !isNaN(parsed.getTime()) && parsed.getTime() < startOfDay(new Date()).getTime();
  }
  if (!deadline) return false;
  const parsed = parseRelativeDeadline(deadline, meetingDate);
  if (!parsed) return false;
  return parsed.getTime() < startOfDay(new Date()).getTime();
}
