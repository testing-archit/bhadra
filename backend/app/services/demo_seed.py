"""Synthetic demo workspace: Hinglish meetings with tasks, decisions and risks.

Everything here is invented. Used by scripts/seed_demo.py and by the
no-sign-up demo (POST /api/auth/demo), which seeds one per guest."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.database.models import Decision, Meeting, MeetingAttendee, MeetingTask, Project, Risk, User

SEED_PREFIX = "demo-seed-"


def days(n: int) -> date:
    return date.today() + timedelta(days=n)


# Each task: (owner_key, description, due offset in days or None, priority, status)
# owner_key "me"/"mate" maps to the first/second account; anything else is a name.
MEETINGS = [
    {
        "title": "API incident review",
        "ago": 0, "minutes": 31, "source": "bot", "project": "API platform",
        "transcript": (
            "Archit: Kal raat auth requests mein 5xx spike kyun aaya?\n"
            "Vedant: Token cache deploy ke baad stale keys read kar raha tha. Rollback 21:40 pe kiya.\n"
            "Priya: Customer logins 18 minutes impact hue. Enterprise tenant sabse zyada affected tha.\n"
            "Archit: Root cause likho, cache invalidation test add karo, aur staged rollout ke bina redeploy mat karna.\n"
            "Vedant: Haan, main Friday tak regression test aur postmortem dono kar dunga.\n"
            "Priya: Status page pe impact window clearly publish karna hai."
        ),
        "summary": (
            "A stale token cache caused an 18-minute authentication outage after deployment. "
            "The team rolled back at 21:40 and agreed to require a cache invalidation test and staged rollout "
            "before redeploying. Customer impact and a postmortem still need publication."
        ),
        "tasks": [
            ("mate", "Add a regression test for token-cache invalidation", 2, "High", "in_progress"),
            ("mate", "Publish the authentication incident postmortem", 2, "High", "pending"),
            ("Priya", "Publish the 18-minute customer impact window on the status page", 1, "High", "pending"),
        ],
        "decisions": [
            ("Roll back the authentication deployment", "Stale cache keys caused a spike in 5xx responses", ["Patch the cache in production"], None),
            ("Redeploy authentication behind a staged rollout", "A small tenant cohort limits the blast radius", ["Roll out to all tenants at once"], None),
        ],
        "risks": [("A second cache invalidation bug could block enterprise logins", "High")],
    },
    {
        "title": "Release readiness: team workspace",
        "ago": 1, "minutes": 38, "source": "bot", "project": "Wilco app",
        "transcript": (
            "Archit: Thursday launch ke blockers kya hain?\n"
            "Vedant: SSO callback ka redirect loop fix ho gaya, lekin mobile Safari test pending hai.\n"
            "Priya: Invite email copy ready hai. QA sign-off Wednesday tak chahiye.\n"
            "Archit: Enterprise tenants ko pehle feature flag se enable karenge. Agar error rate badha toh flag off.\n"
            "Vedant: Main Safari aur SSO smoke test kal tak complete karunga."
        ),
        "summary": (
            "The team is preparing the team workspace launch for Thursday. SSO redirect fixes are in, "
            "but mobile Safari and QA sign-off remain blockers. Enterprise tenants will receive the feature "
            "through a reversible flag first."
        ),
        "tasks": [
            ("mate", "Complete mobile Safari and SSO smoke tests", 1, "High", "pending"),
            ("Priya", "Get QA sign-off for workspace invites", 2, "High", "pending"),
            ("me", "Prepare the enterprise feature-flag rollout checklist", 2, "Medium", "pending"),
        ],
        "decisions": [
            ("Launch team workspaces to enterprise tenants behind a feature flag", "The flag allows a quick rollback if errors rise", ["Enable the feature for every tenant"], None),
            ("Hold the launch if SSO or mobile Safari smoke tests fail", "Both are primary paths for customer access"),
        ],
        "risks": [("Mobile Safari sign-in may delay Thursday's launch", "Medium")],
    },
    {
        "title": "Engineering sync: multilingual meeting notes",
        "ago": 3, "minutes": 42, "source": "extension", "project": "Wilco app",
        "transcript": (
            "Archit: Hinglish transcripts mein speaker names ab kaise aa rahe hain?\n"
            "Vedant: Word accuracy improve hui hai, par 'Moghe' kabhi 'Mogey' aa raha hai.\n"
            "Priya: Tamil customer call mein action items sahi the, but summary English mein hi chahiye.\n"
            "Archit: Vocabulary mein team names add karo. Original-language transcript bhi preserve karenge.\n"
            "Vedant: Main 20 mixed-language calls par benchmark run karunga."
        ),
        "summary": (
            "Hinglish transcription improved, but proper names still need correction. The team will add "
            "names to vocabulary and benchmark 20 multilingual calls. Summaries can be in English while the "
            "original-language transcript remains available."
        ),
        "tasks": [
            ("mate", "Add team names and product terms to the transcription vocabulary", 2, "High", "in_progress"),
            ("mate", "Benchmark 20 Hindi, English, and Tamil customer calls", 5, "Medium", "pending"),
            ("Priya", "Review English summaries against the original Tamil transcript", 4, "Medium", "pending"),
        ],
        "decisions": [
            ("Preserve original-language transcripts alongside English summaries", "Engineers need to verify names and technical terms in context"),
            ("Prioritize speaker and product-name accuracy this sprint", "Wrong names weaken trust in generated follow-ups", ["Add another export format first"], None),
        ],
        "risks": [("Misheard speaker names may assign work to the wrong engineer", "High")],
    },
    {
        "title": "Architecture review: search at scale",
        "ago": 5, "minutes": 47, "source": "record", "project": "API platform",
        "transcript": (
            "Archit: Memory search latency p95 ab 1.8 seconds hai. Enterprise target one second hai.\n"
            "Vedant: Pinecone query fast hai; metadata filtering aur Postgres join slow hai.\n"
            "Priya: Tenant isolation ko compromise nahi kar sakte.\n"
            "Archit: Pehle query plan measure karo, phir meeting metadata denormalize karenge. Cache only after profiling.\n"
            "Vedant: Main benchmark dashboard aur query plan Thursday tak bhejta hoon."
        ),
        "summary": (
            "Memory search p95 latency is 1.8 seconds against a one-second enterprise target. The team "
            "will profile the Postgres metadata join before changing the data model, while preserving tenant "
            "isolation. Caching remains an option after measurement."
        ),
        "tasks": [
            ("mate", "Capture query plans for slow memory searches", 2, "High", "pending"),
            ("mate", "Build a p95 search latency dashboard by tenant size", 3, "Medium", "pending"),
            ("me", "Review tenant isolation tests before any search schema change", 4, "High", "pending"),
        ],
        "decisions": [
            ("Profile the metadata join before denormalizing search records", "The vector query is already fast; the database join is the likely bottleneck", ["Add a cache immediately", "Change vector providers"], None),
            ("Keep tenant isolation checks on every search path", "Latency work must not expose another team's meetings"),
        ],
        "risks": [("Search optimization could accidentally bypass tenant visibility rules", "High")],
    },
    {
        "title": "Design review: developer onboarding",
        "ago": 7, "minutes": 29, "source": "paste", "project": "Wilco app",
        "transcript": (
            "Priya: Pehli screen pe meeting URL aur sample question saath dikh rahe hain; users confused hain.\n"
            "Archit: Let's separate connecting a meeting from exploring sample data.\n"
            "Vedant: OAuth scopes ko just-in-time explain karna hoga, especially calendar access.\n"
            "Priya: Keyboard flow and contrast checks Friday tak kar lungi.\n"
            "Archit: Demo workspace sign-up ke bina open hona chahiye."
        ),
        "summary": (
            "Developer onboarding mixed meeting setup with sample exploration. The team will give these "
            "paths distinct entry points, explain OAuth scopes when requested, and keep the demo available "
            "without sign-up. Keyboard and contrast reviews are pending."
        ),
        "tasks": [
            ("Priya", "Prototype separate connect-meeting and explore-demo entry points", 2, "Medium", "in_progress"),
            ("Priya", "Run keyboard navigation and contrast checks", 3, "Medium", "pending"),
            ("mate", "Add a just-in-time explanation for calendar OAuth scopes", 4, "Medium", "pending"),
        ],
        "decisions": [
            ("Separate live meeting setup from sample workspace exploration", "The combined first screen confused first-time users", ["Keep both actions in one form"], None),
            ("Keep the demo available without sign-up", "Developers can verify the value before connecting accounts"),
        ],
        "risks": [("Unclear OAuth permissions may reduce setup completion", "Medium")],
    },
    {
        "title": "Code review: webhook retry policy",
        "ago": 9, "minutes": 26, "source": "bot", "project": "API platform",
        "transcript": (
            "Vedant: PR 284 exponential backoff add karta hai, but same event do baar deliver ho sakta hai.\n"
            "Archit: Idempotency key ke bina merge mat karo. Retries five attempts tak cap karo.\n"
            "Priya: Customer-facing delivery log mein last failure reason visible hona chahiye.\n"
            "Vedant: Theek hai, main integration test add karke PR update karta hoon."
        ),
        "summary": (
            "The team reviewed webhook retry behavior in PR 284. They will cap retries at five attempts "
            "and require an idempotency key before merging. Customer-facing logs should show the last "
            "failure reason."
        ),
        "tasks": [
            ("mate", "Add idempotency-key validation and duplicate-delivery tests to PR 284", -2, "High", "done"),
            ("mate", "Cap webhook retries at five attempts", 1, "Medium", "pending"),
            ("Priya", "Design the delivery log failure-state copy", 3, "Low", "pending"),
        ],
        "decisions": [
            ("Block the webhook retry merge until idempotency tests pass", "Backoff alone can still deliver the same event twice", ["Merge and monitor duplicates"], None),
            ("Cap delivery retries at five attempts", "Unbounded retries amplify incidents and cost"),
        ],
        "risks": [("Duplicate webhooks could trigger customer workflows twice", "High")],
    },
    {
        "title": "Roadmap planning: enterprise controls",
        "ago": 12, "minutes": 36, "source": "record", "project": "Enterprise readiness",
        "transcript": (
            "Archit: Next quarter mein SSO, audit log aur retention controls mein priority kya hai?\n"
            "Priya: Customer interviews mein SSO sabse bada blocker hai. Audit export second.\n"
            "Vedant: Retention policy backend already supports 30 days; UI missing hai.\n"
            "Archit: SSO first, audit export second. Retention UI can follow after security review.\n"
            "Priya: Main three design partners se priority validate karungi."
        ),
        "summary": (
            "Enterprise customers identify SSO as the largest adoption blocker, followed by audit export. "
            "The roadmap prioritizes SSO, then audit export; retention controls follow security review. "
            "The ordering will be validated with three design partners."
        ),
        "tasks": [
            ("me", "Write the SSO milestone and acceptance criteria", -4, "High", "done"),
            ("Priya", "Validate enterprise priorities with three design partners", 4, "Medium", "pending"),
            ("mate", "Scope the audit export API", 7, "Medium", "pending"),
        ],
        "decisions": [
            ("Prioritize enterprise SSO before audit export", "SSO is the largest adoption blocker in customer interviews", ["Build audit export first"], None),
            ("Ship retention controls after a security review", "The backend supports the policy but the user-facing controls need validation"),
        ],
        "risks": [("Enterprise pilots may slip if SSO misses the quarter", "Medium")],
    },
    {
        "title": "Customer engineering: SSO rollout",
        "ago": 2, "minutes": 34, "source": "bot", "project": "Enterprise readiness",
        "transcript": (
            "Priya: Acme's security team needs a SAML metadata URL before their pilot.\n"
            "Vedant: Staging setup works, but cert rotation needs a test.\n"
            "Archit: We should document the rollback and have support join the cutover.\n"
            "Priya: I will confirm the pilot window with Acme by Friday."
        ),
        "summary": "Acme's SSO pilot needs SAML metadata, certificate rotation coverage, and a support-backed cutover plan. Priya will confirm the pilot window.",
        "tasks": [
            ("mate", "Test SAML certificate rotation in staging", 2, "High", "pending"),
            ("Priya", "Confirm Acme's SSO pilot window", 2, "Medium", "pending"),
        ],
        "decisions": [("Run the SSO cutover with support on call", "Acme needs a clear rollback path during the pilot")],
        "risks": [("Certificate rotation could interrupt enterprise sign-in", "High")],
    },
    {
        "title": "Sprint planning: analytics dashboard",
        "ago": 6, "minutes": 39, "source": "extension", "project": "Wilco app",
        "transcript": (
            "Archit: Usage dashboard ka first version kya show karega?\n"
            "Priya: Meeting volume, active teams, and AI spend. No vanity chart.\n"
            "Vedant: Events already exist, but per-tenant aggregation needs an index.\n"
            "Archit: Let's ship a read-only beta and review numbers with design partners."
        ),
        "summary": "The analytics dashboard beta will show meeting volume, active teams, and AI spend. It will be read-only while the team validates metrics with design partners.",
        "tasks": [
            ("mate", "Add an index for per-tenant usage aggregation", 3, "Medium", "pending"),
            ("Priya", "Review dashboard metrics with two design partners", 6, "Medium", "pending"),
        ],
        "decisions": [("Launch analytics as a read-only beta", "Metric definitions need customer validation before adding controls", ["Ship billing controls in the first release"], None)],
        "risks": [("Slow aggregation queries could affect dashboard load time", "Medium")],
    },
    {
        "title": "Security review: meeting access",
        "ago": 11, "minutes": 45, "source": "record", "project": "Enterprise readiness",
        "transcript": (
            "Archit: Shared meetings mein admin access ka behavior clear hona chahiye.\n"
            "Vedant: Admin list is separate; normal Home only shows invited meetings.\n"
            "Priya: Speaker names alone cannot grant access. Reviewers need explicit invites.\n"
            "Archit: Add a test for pending attendees before release."
        ),
        "summary": "The security review confirmed invite-based meeting access. Admin browsing remains separate, and speakers do not gain access without an explicit invite. A pending-attendee regression test is required.",
        "tasks": [
            ("mate", "Add a pending-attendee visibility regression test", -3, "High", "done"),
            ("me", "Document the meeting sharing model for enterprise reviewers", 5, "Medium", "pending"),
        ],
        "decisions": [("Keep meeting access invite-based", "A speaker name alone does not prove account ownership", ["Grant access to every recognized speaker"], None)],
        "risks": [("Accidental access grants could expose private meeting notes", "High")],
    },
]

def _decision(meeting_id, project_id, entry, speakers) -> Decision:
    """entry: (text, reason) or (text, reason, alternatives, conflict_note).
    A conflict_note marks a decision that reverses an earlier one."""
    text, reason, *rest = entry
    alternatives = (rest[0] if rest else None) or []
    conflict_note = rest[1] if len(rest) > 1 else None
    return Decision(
        meeting_id=meeting_id, project_id=project_id, decision=text, reason=reason,
        alternatives=alternatives, conflict_note=conflict_note, participants=sorted(speakers),
    )




async def seed_workspace(db, owner: User, mate: User | None = None, skip: set[int] | None = None,
                         mate_name: str = "Vedant Moghe") -> dict:
    """Adds the demo meetings to `owner`'s workspace (and `mate`'s, if given).
    Without a `mate` account, their tasks are owned by `mate_name` text."""
    skip = skip or set()
    now = datetime.now(timezone.utc)
    users = [owner] + ([mate] if mate is not None and mate.id != owner.id else [])

    def who(key: str) -> tuple[str, User | None]:
        if key == "me":
            return owner.name or owner.email.split("@")[0], owner
        if key == "mate":
            return (mate.name or mate.email.split("@")[0], mate) if mate is not None else (mate_name, None)
        return key, None

    projects: dict[str, Project] = {}
    counts = {"meetings": 0, "tasks": 0, "decisions": 0, "risks": 0}
    for index, spec in enumerate(MEETINGS):
        if index in skip:
            continue
        name = spec["project"]
        if name not in projects:
            project = await db.scalar(select(Project).where(Project.name == name))
            if project is None:
                project = Project(name=name)
                db.add(project)
                await db.flush()
            projects[name] = project
        project = projects[name]

        when = now - timedelta(days=spec["ago"], hours=2 + index)
        meeting = Meeting(
            user_id=owner.id, organizer_user_id=owner.id, title=spec["title"], date=when,
            transcript=spec["transcript"], summary=spec["summary"], duration_minutes=spec["minutes"],
            source=spec["source"], client_meeting_id=f"{SEED_PREFIX}{index}",
        )
        meeting.projects.append(project)
        db.add(meeting)
        await db.flush()
        counts["meetings"] += 1

        for user in users:
            db.add(MeetingAttendee(
                meeting_id=meeting.id, user_id=user.id, email=user.email,
                display_name=user.name or user.email.split("@")[0],
                kind="internal", source="manual", access="granted",
            ))
        speakers = {line.split(":", 1)[0].split(" (")[0] for line in spec["transcript"].splitlines()}
        for speaker in sorted(speakers - {"Archit", "Vedant"}):
            db.add(MeetingAttendee(meeting_id=meeting.id, display_name=speaker, kind="external", source="manual"))

        for owner_key, text, due, priority, status in spec["tasks"]:
            owner_name, owner_user = who(owner_key)
            db.add(MeetingTask(
                meeting_id=meeting.id, project_id=project.id, owner=owner_name,
                owner_user_id=owner_user.id if owner_user else None,
                description=text, due_date=days(due) if due is not None else None,
                deadline=days(due).strftime("%d %b") if due is not None else None,
                priority=priority, status=status, origin="ai",
            ))
            counts["tasks"] += 1
        for entry in spec["decisions"]:
            db.add(_decision(meeting.id, project.id, entry, speakers))
            counts["decisions"] += 1
        for text, severity in spec["risks"]:
            db.add(Risk(meeting_id=meeting.id, project_id=project.id, description=text, severity=severity))
            counts["risks"] += 1
    return counts
