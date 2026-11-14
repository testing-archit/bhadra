# Design skills for Wilco

Three upstream skills are bundled in `.agents/skills/` for project use. Both Codex accounts share this project directory. Claude Code uses links in `.claude/skills/`; existing animation and impeccable skills remain in place.

| Skill | Use in Wilco | Source |
| --- | --- | --- |
| frontend-design | Set a deliberate direction for a new screen; simplify hierarchy and copy | [Anthropic](https://github.com/anthropics/skills/tree/main/skills/frontend-design) |
| shadcn | Compose and maintain our existing Base UI components with Tailwind tokens | [shadcn](https://github.com/shadcn-ui/ui/tree/main/skills/shadcn) |
| ui-ux-pro-max | Search UX, accessibility, responsive, and Next.js implementation guidance | [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/main/.claude/skills/ui-ux-pro-max) |

The first skill includes its Apache 2.0 license; the other bundles retain their upstream MIT licenses. `design-skills-lock.json` records exact upstream revisions and file checksums. All bundled source files were compared with those revisions. Existing `skills-lock.json` belongs to the earlier skill setup and is preserved.

## Activate and verify

The installed skills are available to Codex on the next turn. Start a fresh Claude Code session if its current session does not discover the new links. A link does not imply the running UI session has acknowledged this setup.

From the repository root:

```bash
python3 tools/design-skills.py --link-claude
```

This verifies bundle checksums and creates any missing Claude links. It refuses to overwrite an existing skill. On a teammate's clone, run it once because `.claude/` is ignored by Git.

To exercise the local UX search:

```bash
python3 .agents/skills/ui-ux-pro-max/scripts/search.py 'icon button accessible label' --domain icons
python3 .agents/skills/ui-ux-pro-max/scripts/search.py 'loading error feedback' --stack nextjs
```

From `frontend/`, run `npx --no-install shadcn info --json` to inspect the actual component base. It needs network access to the official registry. Verification detected Next.js 16.3, Tailwind 4, the `base-nova` style, Base UI, Lucide, and the installed component list.

## Working agreement

Read [coordination.md](coordination.md) before editing. Claude currently owns the UI changes.

Use one skill for the immediate job. Keep `DESIGN.md`, the established theme tokens, and our Lucide icon family as the project defaults. Skill searches supply suggestions; check the top result against the requested outcome before using it. Do not import a suggested icon library, replace our palette, or generate a second design system merely because a skill recommends one.

Wilco's agreed flow remains a focused Home action, guided review of tasks/decisions/uncertain speakers, and a clean recap. Preserve visible recording consent and conservative speaker identification. Keep advanced details behind explicit controls.

Example request for the UI owner:

> Use frontend-design for hierarchy and shadcn for implementation. Follow DESIGN.md. Simplify the existing meeting review into one actionable item at a time. Keep consent visible, support keyboard use, and respect reduced motion. Use UI UX Pro Max only for specific accessibility or Next.js questions. Check the result on narrow and desktop screens before handing it back.

gstack review skills were inspected but not installed: their instructions depend on a broader gstack runtime. Animation skills already present can be used when motion explains a user action; no additional motion library was installed.
