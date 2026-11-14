// Google Sheets export: a formatted Tasks tab and Meetings tab, one row per
// task / meeting, appended when a meeting's notes are ready.
//
// The layout lives here as plain functions (rows + formatting requests) so it
// can be tested without Chrome or Google; background.js does the HTTP.

export const TASK_COLUMNS = [
  { title: "Task", width: 360, wrap: true },
  { title: "Owner", width: 140 },
  { title: "Due", width: 110, date: true },
  { title: "Priority", width: 80 },
  { title: "Status", width: 100 },
  { title: "Project", width: 130 },
  { title: "Meeting", width: 240, wrap: true },
  { title: "Meeting date", width: 110, date: true },
  { title: "Charcha", width: 80 },
  { title: "Jira", width: 90 },
];

export const MEETING_COLUMNS = [
  { title: "Date", width: 110, date: true },
  { title: "Meeting", width: 240, wrap: true },
  { title: "Minutes", width: 75 },
  { title: "Attendees", width: 200, wrap: true },
  { title: "Summary", width: 420, wrap: true },
  { title: "Decisions", width: 320, wrap: true },
  { title: "Tasks", width: 65 },
  { title: "Charcha", width: 80 },
];

const STATUS_LABELS = { pending: "To do", in_progress: "In progress", done: "Done" };

/** Text exactly as written. Cells are sent USER_ENTERED (so dates and links
 * work), which would run anything starting with = + - @ as a formula. */
export function safeText(value) {
  const text = value == null ? "" : String(value);
  return /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
}

function link(url, label) {
  return url ? `=HYPERLINK("${url.replace(/"/g, "%22")}","${label.replace(/"/g, "'")}")` : "";
}

/** "2026-10-07" in India time, which Sheets reads as a real date. */
export function istDate(value) {
  if (!value) return "";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
}

export function taskRows(meeting, { appUrl, jiraSiteUrl } = {}) {
  const meetingLink = appUrl ? `${appUrl}/meetings/${meeting.id}?tab=actions` : "";
  return (meeting.tasks || []).map((task) => [
    safeText(task.description),
    safeText(task.owner || ""),
    task.due_date ? istDate(task.due_date) : safeText(task.deadline || ""),
    safeText(task.priority || ""),
    STATUS_LABELS[task.status] || safeText(task.status || ""),
    safeText(task.project || ""),
    safeText(meeting.title),
    istDate(meeting.date),
    link(meetingLink, "Open"),
    task.jira_issue_key ? link(jiraSiteUrl ? `${jiraSiteUrl}/browse/${task.jira_issue_key}` : "", task.jira_issue_key) || task.jira_issue_key : "",
  ]);
}

export function meetingRow(meeting, { appUrl } = {}) {
  const attendees = (meeting.attendees || []).map((person) => person.name).filter(Boolean);
  const decisions = (meeting.decisions || []).map((d) => `• ${d.decision}`).join("\n");
  return [
    istDate(meeting.date),
    safeText(meeting.title),
    meeting.duration_minutes || "",
    safeText(attendees.join(", ")),
    safeText(meeting.summary || ""),
    safeText(decisions),
    (meeting.tasks || []).length,
    link(appUrl ? `${appUrl}/meetings/${meeting.id}` : "", "Open"),
  ];
}

const HEADER_BACKGROUND = { red: 0.93, green: 0.94, blue: 0.96 };
const STATUS_COLOURS = {
  Done: { red: 0.85, green: 0.94, blue: 0.86 },
  "In progress": { red: 0.86, green: 0.91, blue: 0.99 },
  "To do": { red: 0.99, green: 0.95, blue: 0.84 },
};

/** batchUpdate requests that turn a fresh tab into a formatted table:
 * frozen bold header, widths, wrapping, date formats, filter, and (for
 * tasks) colour-coded status. */
export function formatRequests(sheetId, columns) {
  const requests = [
    {
      updateSheetProperties: {
        properties: { sheetId, gridProperties: { frozenRowCount: 1 } },
        fields: "gridProperties.frozenRowCount",
      },
    },
    {
      repeatCell: {
        range: { sheetId, startRowIndex: 0, endRowIndex: 1 },
        cell: {
          userEnteredFormat: {
            backgroundColor: HEADER_BACKGROUND,
            textFormat: { bold: true },
            verticalAlignment: "MIDDLE",
          },
        },
        fields: "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
      },
    },
    {
      repeatCell: {
        range: { sheetId, startRowIndex: 1 },
        cell: { userEnteredFormat: { verticalAlignment: "TOP" } },
        fields: "userEnteredFormat.verticalAlignment",
      },
    },
    { setBasicFilter: { filter: { range: { sheetId, startRowIndex: 0, startColumnIndex: 0, endColumnIndex: columns.length } } } },
  ];
  columns.forEach((column, index) => {
    const columnRange = { sheetId, startColumnIndex: index, endColumnIndex: index + 1 };
    requests.push({
      updateDimensionProperties: {
        range: { sheetId, dimension: "COLUMNS", startIndex: index, endIndex: index + 1 },
        properties: { pixelSize: column.width },
        fields: "pixelSize",
      },
    });
    if (column.wrap) {
      requests.push({
        repeatCell: {
          range: { ...columnRange, startRowIndex: 1 },
          cell: { userEnteredFormat: { wrapStrategy: "WRAP" } },
          fields: "userEnteredFormat.wrapStrategy",
        },
      });
    }
    if (column.date) {
      requests.push({
        repeatCell: {
          range: { ...columnRange, startRowIndex: 1 },
          cell: { userEnteredFormat: { numberFormat: { type: "DATE", pattern: "dd mmm yyyy" } } },
          fields: "userEnteredFormat.numberFormat",
        },
      });
    }
  });
  const statusIndex = columns.findIndex((column) => column.title === "Status");
  if (statusIndex >= 0) {
    for (const [label, backgroundColor] of Object.entries(STATUS_COLOURS)) {
      requests.push({
        addConditionalFormatRule: {
          rule: {
            ranges: [{ sheetId, startRowIndex: 1, startColumnIndex: statusIndex, endColumnIndex: statusIndex + 1 }],
            booleanRule: {
              condition: { type: "TEXT_EQ", values: [{ userEnteredValue: label }] },
              format: { backgroundColor },
            },
          },
          index: 0,
        },
      });
    }
  }
  return requests;
}

export function headerRow(columns) {
  return columns.map((column) => column.title);
}

/** True when a tab's first row is this layout's header. */
export function hasHeader(firstRow, columns) {
  const expected = headerRow(columns);
  return Array.isArray(firstRow) && expected.every((title, index) => (firstRow[index] || "").trim() === title);
}
