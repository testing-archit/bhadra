// Unit tests for the Google Sheets export layout (src/sheets.js).
import assert from "node:assert/strict";
import {
  MEETING_COLUMNS, TASK_COLUMNS, formatRequests, hasHeader, headerRow, istDate, meetingRow, safeText, taskRows,
} from "../src/sheets.js";

// Text that would run as a formula is written as text.
assert.equal(safeText("=IMPORTXML(\"http://evil\")"), "'=IMPORTXML(\"http://evil\")");
assert.equal(safeText("- decided X"), "'- decided X");
assert.equal(safeText("+91 number"), "'+91 number");
assert.equal(safeText("@mention"), "'@mention");
assert.equal(safeText("Plain task"), "Plain task");
assert.equal(safeText(null), "");

// Dates land as India-time calendar dates Sheets parses.
assert.equal(istDate("2026-10-07T20:00:00+00:00"), "2026-10-08"); // 01:30 IST next day
assert.equal(istDate("2026-10-10"), "2026-10-10");
assert.equal(istDate(""), "");
assert.equal(istDate("not a date"), "");

const meeting = {
  id: "m1",
  title: "=Weekly sync",
  date: "2026-10-07T06:33:30.998294+00:00",
  duration_minutes: 22,
  summary: "We reviewed Charcha.",
  attendees: [{ name: "Archit Gupta" }, { name: "Astha Sethi" }],
  decisions: [{ decision: "Use Pinecone" }, { decision: "Ship Jira sync" }],
  tasks: [
    { description: "Check SIP AUM", owner: "Archit", due_date: "2026-10-10", deadline: "Friday", priority: "High", status: "in_progress", project: "MIS", jira_issue_key: "MT-1" },
    { description: "Write the doc", owner: null, due_date: null, deadline: "next week", priority: null, status: "pending", project: null },
  ],
};
const context = { appUrl: "https://charcha.example.com", jiraSiteUrl: "https://acme.atlassian.net" };
const [first, second] = taskRows(meeting, context);
assert.equal(first.length, TASK_COLUMNS.length);
assert.deepEqual(first.slice(0, 8), ["Check SIP AUM", "Archit", "2026-10-10", "High", "In progress", "MIS", "'=Weekly sync", "2026-10-07"]);
assert.equal(first[8], '=HYPERLINK("https://charcha.example.com/meetings/m1?tab=actions","Open")');
assert.equal(first[9], '=HYPERLINK("https://acme.atlassian.net/browse/MT-1","MT-1")');
assert.equal(second[2], "next week"); // no real date: the phrase as said
assert.equal(second[4], "To do");
assert.equal(second[9], "");
// Without a Jira site the key still shows.
assert.equal(taskRows(meeting, { appUrl: context.appUrl })[0][9], "MT-1");

const row = meetingRow(meeting, context);
assert.equal(row.length, MEETING_COLUMNS.length);
assert.deepEqual(row.slice(0, 7), ["2026-10-07", "'=Weekly sync", 22, "Archit Gupta, Astha Sethi", "We reviewed Charcha.", "• Use Pinecone\n• Ship Jira sync", 2]);

// Header detection: only an exact header counts.
assert.ok(hasHeader(headerRow(TASK_COLUMNS), TASK_COLUMNS));
assert.ok(!hasHeader(["Check SIP AUM", "Archit", "Friday", "High", "Weekly"], TASK_COLUMNS)); // old export row
assert.ok(!hasHeader(undefined, TASK_COLUMNS));

// Formatting: frozen header, a width per column, wrap/date formats, status colours.
const requests = formatRequests(7, TASK_COLUMNS);
assert.equal(requests[0].updateSheetProperties.properties.gridProperties.frozenRowCount, 1);
assert.equal(requests.filter((r) => r.updateDimensionProperties).length, TASK_COLUMNS.length);
assert.equal(requests.filter((r) => r.addConditionalFormatRule).length, 3);
assert.ok(requests.every((r) => JSON.stringify(r).includes('"sheetId":7')));
assert.equal(formatRequests(3, MEETING_COLUMNS).filter((r) => r.addConditionalFormatRule).length, 0);

console.log("Sheets export layout checks passed.");
