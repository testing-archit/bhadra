# Wilco signal room

## Audience and job

Wilco is meeting intelligence for software companies. Its demo should make a team's conversation visibly become decisions, owners, follow-ups, and searchable evidence. Use engineering syncs, incident reviews, release planning, and product decisions as examples. Kirana/shopkeeping is no longer the target audience.

## Visual system

The [concept screenshot](design-references/hackathon-signal-room-concept.png) is an art-direction reference, not a literal UI spec: it contains invented names, events, counts, and text. The implementation keeps data-driven states and existing interactions.

| Role | Color | Use |
| --- | --- | --- |
| Midnight | `#090E24` | App frame and hero depth |
| Ink panel | `#111B34` | Navigational and working surfaces |
| Ice | `#F4F8FF` | Primary text |
| Signal cyan | `#53DDEA` | Live capture and source traces |
| Voltage violet | `#9365F6` | Memory and relationship arcs |
| Launch orange | `#FF8A2A` | One primary action per view |

Geist remains the readable product face. Geist Mono and the existing Doto face can label signal time, source references, and large meaningful numbers. Avoid a terminal costume: source and activity metaphors help explain meetings, but tasks and consent stay in plain language.

Desktop structure: narrow navigation rail, precise top command bar, one dramatic two-column hero with a signal visualization, and a grounded work area below for owned actions, live/upcoming meetings, and recent notes. Mobile stacks the hero above the same real actions and retains an obvious capture action. Use contrast, scale, and one luminous visual focal point rather than putting glow on every card.

Motion explains a state or relationship: live listening has a halo, work-page headers carry a short signal trace, and Delivery Radar has a slow scanning sweep. Animations use transforms or opacity and stop for `prefers-reduced-motion`. Keep all actions keyboard reachable and verify at phone and desktop widths.

## Product navigation

The retail Voice khata page has been replaced by **Delivery Radar** at `/delivery`. It summarizes accessible meeting tasks, overdue and high-priority work, decisions, and project activity from existing API data. Old `/khata` bookmarks redirect to the radar. The legacy khata API remains available for existing integrations; it is not part of the software-team navigation or demo.

The Signal Room visual system now covers Meetings, Tasks, Decisions, Projects, Memory, Live, meeting details and setup, settings, admin, voice tools, extension setup, shared links, and account recovery. Route families use scoped semantic colors so the shell and page content meet without a light gutter.

## Reel references

The [shared Instagram reel](https://www.instagram.com/reel/DeiwHSZTwUM/) presents resource libraries for making generated websites feel more premium. It is a list of tools, not a single visual style. Relevant sources checked for this direction:

- [Scrolltide](https://www.scrolltide.co/) for dimensional motion and 3D composition ideas; do not depend on paid templates.
- [Navbar Gallery](https://www.navbar.gallery/) for navigation patterns with clear hierarchy.
- [CTA Gallery](https://www.cta.gallery/) for a strong primary meeting action.
- [Refero Styles](https://styles.refero.design/) for visual-system references and token discipline.
- [Supahero](https://supahero.io/) for first-viewport hierarchy.
- [3dicons](https://3dicons.co/) for optional accents; the existing Lucide icon family stays in product controls.

No third-party site artwork or code is copied into the interface. The waveform and connected meeting points are original product visuals.

## Acceptance

1. The demo Home makes capture, live status, review, and owned action easy to find with real data.
2. The interface feels specific to software-team meetings, including sample content, Delivery Radar, and primary navigation.
3. Desktop and mobile views are visually coherent and functional, with empty/loading/error states.
4. Typecheck and build pass; browser screenshots are reviewed at desktop and mobile widths.
