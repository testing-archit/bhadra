# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Engineering teams at Indian software companies: product managers, engineering leads and developers. They run standups, sprint planning, design reviews and client calls on Google Meet or Teams, or in person, often switching between English and Hindi mid-sentence. Their job after a meeting is to know who owns what, by when, and why the team decided something, without anyone writing minutes.

## Product Purpose

Wilco joins the meeting (a notetaker bot, the Chrome extension, an upload or the in-person recorder), hears it with Gnani Prisma, and turns it into owners, tasks, decisions and searchable memory. People can ask it questions during the call ("Wilco, what did we decide on caching?") and get answers read aloud with Gnani Timbre, and ask the company memory afterwards. Success: tasks land with the right owner (and in Jira) without anyone taking notes, and "why did we do X?" has an answer months later.

## Positioning

The name is aviation radio for "will comply": heard it, will do it. Unlike English-only notetakers, Wilco understands Hinglish and Indian languages natively through Gnani's models, and it is built around decisions and accountability (owners, reasons, reversals, Jira two-way sync), not just transcripts.

## Operating Context

- Built for the Gnani AI internship challenge; judges see a live demo. Requirement: a working app built on Gnani models (Prisma v3 speech-to-text, Timbre v2.5 text-to-speech).
- Daily use sits between calls: open Home, see what's due, check a meeting's notes, push tasks to Jira, ask memory.
- Privacy is product truth: invite-based meeting visibility, held tasks, confidential meetings.

## Capabilities and Constraints

- Next.js 16 / React 19 / Tailwind 4 frontend; FastAPI backend; Postgres (Neon); Pinecone memory; Gemini for notes.
- Light and dark themes, both first-class; theme choice persists.
- Infrastructure identifiers keep the old internal name `charcha` (database, deploy secrets, storage keys, Jira label, MCP scopes); never show it to users.

## Brand Commitments

- Name: **Wilco**. Tagline: "Heard. Will comply." Radio vocabulary may appear lightly: Debrief (post-meeting notes), Logbook (memory), Tower (admin).
- Wake word in calls: "Wilco, ...". Leave phrase: "Wilco, please leave".
- Bot personality: the team's calm co-pilot; precise, warm, brief.
- Logo and bot avatar are being made separately (navy and aviation-amber direction); current marks are placeholders.
- UI copy is plain English, sentence case. Hindi and Hinglish are welcome in what users say and in example prompts, not in the interface chrome.

## Evidence on Hand

- Demo data: seeded Hinglish meetings, tasks and decisions (`backend/scripts`).
- Product screenshots in `docs/screenshots/` show the previous look.
- No customers, testimonials or metrics exist; never fabricate them.

## Product Principles

1. Accountability over transcripts: owners, dates and reasons come first.
2. Voice is a first-class way in, but never the only way.
3. Calm in the work: dense, scannable working screens; personality lives at the edges.
4. Trust is visible: show where an answer came from, who can see a meeting, and what the AI did.

## Accessibility & Inclusion

WCAG AA contrast in both themes; full keyboard use; reduced-motion respected; content in Indian scripts must render in the same type system.
