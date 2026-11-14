import { Users } from "lucide-react";

export function MeetingPeople({
  names,
  total = names.length,
}: {
  names: string[];
  total?: number;
}) {
  if (!names.length)
    return (
      <span className="meeting-people-empty">
        <Users className="size-3.5" aria-hidden="true" />
        {total ? `${total} invited` : "Your meeting"}
      </span>
    );
  return (
    <div
      className="meeting-people"
      aria-label={
        names.join(", ") + (total > 3 ? ` and ${total - 3} more` : "")
      }
    >
      {names.slice(0, 3).map((name, index) => (
        <span
          key={`${name}-${index}`}
          className="person-circle"
          data-tone={index % 3}
          title={name}
          aria-hidden="true"
        >
          {name
            .split(/\s+/)
            .filter(Boolean)
            .map((part) => part[0])
            .slice(0, 2)
            .join("")
            .toUpperCase()}
        </span>
      ))}
      {total > 3 && (
        <span className="person-circle person-more" aria-hidden="true">
          +{total - 3}
        </span>
      )}
    </div>
  );
}
