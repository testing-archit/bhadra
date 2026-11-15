export type StripSegment = { id?: string; start_ms: number | null; end_ms: number | null; text: string };
export type DebriefMark = { id: string; at_ms: number; kind: "decision" | "task" | "risk"; label: string; segmentId: string };

/** Word density from timed transcript data. Silence stays silent. */
export function buildStrip(segments: StripSegment[], marks: DebriefMark[], duration: number, buckets: number) {
  if (!Number.isFinite(duration) || duration <= 0 || !Number.isInteger(buckets) || buckets < 1 || buckets > 240) return null;
  const timed = segments.filter(s => s.start_ms !== null && s.end_ms !== null && Number.isFinite(s.start_ms) && Number.isFinite(s.end_ms) && s.end_ms > s.start_ms && s.end_ms > 0 && s.start_ms < duration && s.text.trim());
  if (!timed.length) return null;
  const weights = Array.from({ length: buckets }, () => 0);
  const width = duration / buckets;
  for (const segment of timed) {
    const start = Math.max(0, segment.start_ms!), end = Math.min(duration, segment.end_ms!);
    const words = segment.text.trim().split(/\s+/).length;
    for (let i = Math.floor(start / width); i < Math.min(buckets, Math.ceil(end / width)); i++) {
      weights[i] += words * Math.max(0, Math.min(end, (i + 1) * width) - Math.max(start, i * width)) / (segment.end_ms! - segment.start_ms!);
    }
  }
  const max = Math.max(...weights);
  return { bars: weights.map(value => max > 0 ? Math.sqrt(value / max) : 0),
    marks: marks.filter(mark => Number.isFinite(mark.at_ms) && mark.at_ms >= 0 && mark.at_ms <= duration)
      .sort((a, b) => a.at_ms - b.at_ms).map(mark => ({ ...mark, position: mark.at_ms / duration * 100 })) };
}

export function formatMoment(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
