/** How each meeting got into Charcha, in the words people use. */
export const SOURCE_LABELS: Record<string, string> = {
  bot: "Calendar notetaker",
  capture: "Notetaker (meeting link)",
  extension: "Chrome extension",
  record: "In-person recording",
  upload: "Uploaded file",
  paste: "Pasted transcript",
  call: "Phone call recap",
  voice_note: "WhatsApp voice note",
};

export const STATUS_LABELS: Record<string, string> = {
  pending: "To do",
  in_progress: "In progress",
  done: "Done",
};
