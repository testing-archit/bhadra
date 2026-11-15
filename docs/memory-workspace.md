# Streamlined Memory workspace

The user’s screenshot showed a permanent history/source sidebar, duplicated titles and a question box far from the starting prompts. The new Memory page uses one canvas with a prominent composer, three concise topic buttons and three actual recent meetings. The approved mascot adds personality without animation or extra explanatory text.

History and meeting selection open only when requested. Source selection supports up to ten meetings; selections remain a draft until Apply. Escape cancels changes, unchanged selections keep the current conversation, and source changes preserve the typed question while starting a fresh conversation. A recent meeting is a direct way to set scope. Topic buttons fill an editable question rather than submitting immediately.

Existing answer/citation components, source links, voice input, follow-up history and the URL question handoff are preserved. History restores its saved scope and supports a separate deletion button with confirmation/cancel. Failed deletes or answer requests report errors. Chat and scope switching are disabled while an answer is pending. The old nested delete control is removed.

Validation: production build and TypeScript pass. Local browser checks use demo meeting reads and intercepted chat/deletion requests; they do not bill AI or delete saved chats. Checked initial state, editable prompts, cancel/apply sources, multi-meeting API payloads, pending controls, source links, unchanged-scope preservation, retry, history restoration, delete confirmation/cancel, 320/390px layouts and dialogs, mobile composer placement, and one-shot URL handoff. Screenshots show the actual build with fixture answers. Live voice recording and model answer quality were not exercised. ESLint retains the previously documented TypeScript/parser incompatibility.

Preview: http://localhost:3200/memory. Screenshots: `screenshots/wilco-memory-desktop.png`, `wilco-memory-mobile.png`, `wilco-memory-dark.png`, `wilco-memory-conversation.png`, and `wilco-memory-mobile-conversation.png`. This is a UI topic-branch checkpoint, not a production release.
