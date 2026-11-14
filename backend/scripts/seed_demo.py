"""Seed synthetic demo data: Hinglish meetings with tasks, decisions and risks.

Everything here is invented for demos. Meetings are owned by the first email
and shared (granted attendee rows) with every email given, so all of them
see the same workspace. Accounts must already exist (sign up first).

    python scripts/seed_demo.py owner@example.com teammate@example.com
    python scripts/seed_demo.py --reset owner@example.com ...   # replace

Re-running without --reset does nothing if the demo is already there.
"""
import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import async_session  # noqa: E402
from app.database.models import (  # noqa: E402
    Decision,
    Meeting,
    MeetingAttendee,
    MeetingTask,
    Project,
    Risk,
    User,
)

SEED_PREFIX = "demo-seed-"
NOW = datetime.now(timezone.utc)
TODAY = date.today()


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


# Each task: (owner_key, description, due offset in days or None, priority, status)
# owner_key "me"/"mate" maps to the first/second account; anything else is a name.
MEETINGS = [
    {
        "title": "Weekly product sync",
        "ago": 1, "minutes": 42, "source": "bot", "project": "Charcha app",
        "transcript": (
            "Archit: Chalo shuru karte hain. Recorder ka Hindi accuracy ab kaisa hai?\n"
            "Vedant: Pichle hafte se better hai, Hinglish mein 92 percent words sahi aa rahe hain.\n"
            "Priya: Lekin naam galat aa rahe hain, jaise 'Moghe' ko 'Mogey' likh deta hai.\n"
            "Archit: Vocabulary page mein team ke naam daal dete hain. Vedant, Friday tak kar doge?\n"
            "Vedant: Haan, Friday tak ho jayega.\n"
            "Priya: Aur onboarding mein Hindi option pehle dikhana chahiye.\n"
            "Archit: Agreed, Hindi default rahega jab browser language hi ho."
        ),
        "summary": (
            "The team reviewed Hindi/Hinglish transcription quality, which is now around 92% word accuracy. "
            "Name spellings are still the main error, so team names go into the vocabulary list. "
            "Onboarding will default to Hindi when the browser language is Hindi."
        ),
        "tasks": [
            ("mate", "Add every team member's name to the vocabulary list", 2, "High", "in_progress"),
            ("Priya", "Draft Hindi copy for the onboarding screens", 4, "Medium", "pending"),
            ("me", "Measure word accuracy on 20 new Hinglish recordings", 6, "Medium", "pending"),
        ],
        "decisions": [
            ("Onboarding defaults to Hindi when the browser language is Hindi", "Most pilot users read Hindi first; English stays one tap away"),
            ("Ship transcription accuracy fixes before any new feature this sprint", "Wrong words in notes cost more trust than missing features",
             ["Build WhatsApp sharing first", "Split the sprint half and half"], None),
            ("Store recordings for 30 days, then keep only the transcript", "Cuts storage cost and limits how much audio we hold",
             ["Keep audio forever", "Delete audio right after transcription"], None),
        ],
        "risks": [("Name spellings in transcripts erode trust in the notes", "Medium")],
    },
    {
        "title": "Kirana pilot review with Pune shopkeepers",
        "ago": 3, "minutes": 35, "source": "record", "project": "Kirana voice bookkeeping",
        "transcript": (
            "Archit: Sunil ji, aap din mein kitni baar udhaar likhte ho?\n"
            "Sunil (shopkeeper): Bees-pachees baar. Haath gande hote hain, phone touch nahi kar sakte.\n"
            "Vedant: Toh aap bas bolo, 'Ramesh ko do kilo chawal, 120 rupaye udhaar'. App likh lega.\n"
            "Sunil: Marathi mein bolun toh chalega?\n"
            "Archit: Haan, Marathi aur Hindi dono. Mahine ke end mein WhatsApp pe hisaab bhej denge.\n"
            "Sunil: Bas galat amount mat likhna, warna jhagda ho jayega."
        ),
        "summary": (
            "Shopkeepers record 20–25 credit (udhaar) entries a day and cannot touch the phone while serving. "
            "Voice entries in Marathi or Hindi worked in the demo. They want a monthly WhatsApp statement and "
            "are worried about wrong amounts causing disputes with customers."
        ),
        "tasks": [
            ("me", "Add a spoken read-back of every amount before it is saved", 1, "High", "pending"),
            ("mate", "Build the month-end WhatsApp statement for each customer", 8, "Medium", "pending"),
            ("Sunil", "Use the app for one week and keep the paper register in parallel", 7, "Low", "pending"),
        ],
        "decisions": [
            ("Every voice entry is read back aloud before saving", "A wrong udhaar amount causes a dispute with the customer"),
            ("Support Marathi and Hindi in the first pilot", "All five Pune shops speak one or both"),
            ("Pilot with 5 shops in Pune before expanding", "Small enough to visit every shop each week",
             ["Launch in 20 shops across two cities"], None),
            ("Month-end statements go out on WhatsApp, not SMS", "Every shopkeeper and most customers already use WhatsApp daily",
             ["SMS", "Printed slips at the counter"], None),
        ],
        "risks": [
            ("Background noise in the shop lowers transcription accuracy", "High"),
            ("Shopkeepers may stop using it if one amount is wrong", "High"),
        ],
    },
    {
        "title": "Hackathon Round 2 planning",
        "ago": 0, "minutes": 28, "source": "capture", "project": "India Runs on Voice",
        "transcript": (
            "Vedant: Problem statement 27 ko aayega, submission 29 ko. Sirf do din hain.\n"
            "Archit: Isliye abhi se demo flow ready rakhte hain: record, notes, tasks, WhatsApp share.\n"
            "Vedant: Demo video kaun banayega?\n"
            "Archit: Main script likhta hoon, tu screen record kar lena.\n"
            "Vedant: Aur Wispr Flow se hi poora build karna hai, yaad rakhna."
        ),
        "summary": (
            "Round 2 gives two days between the problem statement (27 Nov) and submission (29 Nov), "
            "so the team will keep a ready demo flow: record, notes, tasks, share. Archit writes the demo "
            "script and Vedant records the screen. The build is done hands-free with Wispr Flow."
        ),
        "tasks": [
            ("me", "Write the 2-minute demo video script", 5, "High", "pending"),
            ("mate", "Record the demo screen capture", 9, "Medium", "pending"),
            ("me", "Keep a checklist of the submission requirements once Round 2 opens", 13, "Medium", "pending"),
        ],
        "decisions": [
            ("Keep a ready-to-adapt demo flow before the problem statement drops", "The build window is only two days"),
            ("Submit under the Small business track with the kirana voice ledger", "Strongest pilot evidence and a clear everyday user",
             ["Healthcare track with ASHA intake", "Education track"], None),
            ("Demo video stays under 2 minutes", "Judges watch many entries; the core loop fits in 90 seconds", None,
             "Reverses the 14 Nov idea of a 4-minute walkthrough of every feature"),
        ],
        "risks": [("Two-day window leaves no time for new infrastructure", "High")],
    },
    {
        "title": "ASHA worker symptom-intake interview",
        "ago": 6, "minutes": 51, "source": "record", "project": "Swasthya intake",
        "transcript": (
            "Meera (ASHA worker): Gaon mein har ghar jaake form bharna padta hai, bahut time lagta hai.\n"
            "Archit: Agar aap bolke symptoms likhwa sakein toh?\n"
            "Meera: Haan, lekin network nahi hota kai jagah.\n"
            "Vedant: Offline record karke baad mein upload kar sakte hain.\n"
            "Meera: Bukhar, khansi, kitne din se, yeh sab poochna hota hai. Form wahi rehna chahiye."
        ),
        "summary": (
            "ASHA workers fill paper symptom forms door to door and often have no network. Voice intake that "
            "records offline and uploads later fits their day, as long as the structured form fields stay the same."
        ),
        "tasks": [
            ("mate", "Map the paper intake form to structured fields", -2, "High", "pending"),
            ("me", "Test offline recording on a low-end Android phone", 3, "Medium", "pending"),
        ],
        "decisions": [
            ("Recordings save offline first and upload when the network returns", "Many villages have no coverage"),
            ("Ask for spoken consent at the start of every health recording", "Health data needs explicit consent, and many users cannot sign a form",
             ["Written consent form"], None),
        ],
        "risks": [("Health data needs explicit consent before recording", "High")],
    },
    {
        "title": "Investor prep call",
        "ago": 9, "minutes": 33, "source": "extension", "project": "Charcha app",
        "transcript": (
            "Rohan (mentor): Pitch mein pehle problem dikhao, phir product.\n"
            "Archit: Problem: Indian teams Hinglish mein baat karte hain, aur notes tools English-only hain.\n"
            "Rohan: Numbers chahiye. Kitne meetings record hue pilot mein?\n"
            "Vedant: 140 meetings, 9 teams, average 38 minute.\n"
            "Rohan: Badhiya. Retention ka graph bhi daalo."
        ),
        "summary": (
            "The mentor advised opening with the problem: Indian teams speak Hinglish while note tools assume English. "
            "Pilot numbers so far are 140 meetings across 9 teams, averaging 38 minutes. Add a retention chart."
        ),
        "tasks": [
            ("me", "Add the pilot numbers slide (140 meetings, 9 teams)", -4, "Medium", "done"),
            ("mate", "Make a weekly retention chart for the pilot teams", 2, "Medium", "pending"),
        ],
        "decisions": [
            ("The pitch opens with the Hinglish problem, then the product", "Mentor feedback"),
            ("Free for teams under 10 people during the pilot", "Removes the purchase decision while we prove retention",
             ["₹199 per user per month from day one"], None),
        ],
        "risks": [],
    },
    {
        "title": "Design review: Hindi onboarding",
        "ago": 12, "minutes": 25, "source": "paste", "project": "Charcha app",
        "transcript": (
            "Priya: Pehli screen pe sirf ek bada mic button hai, aur neeche 'Boliye' likha hai.\n"
            "Archit: Accha hai. Marigold colour dikh raha hai, contrast theek hai?\n"
            "Priya: Haan, AA pass karta hai. Font Baloo hai, Devanagari bhi saaf dikhta hai.\n"
            "Vedant: Sign-up form chhota karo, sirf naam aur phone."
        ),
        "summary": (
            "The first onboarding screen is a single large mic button labelled 'Boliye'. The marigold colour passes "
            "AA contrast and Baloo renders Devanagari cleanly. Sign-up shrinks to name and phone number."
        ),
        "tasks": [
            ("Priya", "Shrink the sign-up form to name and phone number", -6, "Low", "done"),
            ("me", "Check every onboarding string in Hindi with two native speakers", 10, "Low", "pending"),
        ],
        "decisions": [
            ("Onboarding starts with one large mic button", "Voice is the main way in for our users"),
            ("Sign-up asks only for name and phone number", "Every extra field lost users in the paper prototype test",
             ["Email and password", "Google sign-in only"], None),
            ("Use Baloo 2 and Mukta for all app text", "Both render Devanagari cleanly and match in weight", None,
             "Replaces the earlier choice of a Latin-only font with a system fallback for Hindi"),
        ],
        "risks": [],
    },
    {
        "title": "Sharma Kirana wholesale order call",
        "ago": 2, "minutes": 18, "source": "record", "project": "Kirana voice bookkeeping",
        "transcript": (
            "Archit: Sharma ji, aapka is mahine ka hisaab dekh lete hain.\n"
            "Sharma ji (shopkeeper): Haan, Ramesh supplier ko 1,240 rupaye dene baaki hain, aur Meena ji ka 380 udhaar hai.\n"
            "Vedant: Aur Sharma ji, aapke apne customers ka total udhaar kitna hai?\n"
            "Sharma ji: 6,750 rupaye, 14 logon ka. Sabse zyada Gupta ji ka, 1,100.\n"
            "Archit: Theek hai, Monday ko sabko WhatsApp pe reminder chala jayega.\n"
            "Sharma ji: Aur Diwali ka maal, 20 kilo cheeni aur 10 litre tel, Wednesday tak chahiye."
        ),
        "summary": (
            "Sharma ji owes the supplier Ramesh Rs 1,240 and Meena ji Rs 380. His own customers owe him Rs 6,750 across "
            "14 people, the largest being Gupta ji at Rs 1,100. WhatsApp reminders go out on Monday, and he needs 20 kg sugar "
            "and 10 litres of oil by Wednesday."
        ),
        "tasks": [
            ("me", "Send WhatsApp udhaar reminders to Sharma ji's 14 customers", 1, "High", "pending"),
            ("Sharma ji", "Pay Ramesh supplier Rs 1,240", 3, "Medium", "pending"),
            ("mate", "Place the order for 20 kg sugar and 10 litres oil", 2, "High", "pending"),
        ],
        "decisions": [
            ("Udhaar reminders go out every Monday on WhatsApp", "Customers pay faster after a polite weekly nudge", ["Daily SMS", "No reminders"], None),
        ],
        "risks": [("Gupta ji's Rs 1,100 udhaar is 45 days old", "Medium")],
    },
    {
        "title": "Gram sabha minutes: Hadapsar ward water supply",
        "ago": 4, "minutes": 64, "source": "record", "project": "Civic voice minutes",
        "transcript": (
            "Sarpanch: Aaj ka mudda paani hai. Ward 7 mein teen din se nal nahi aaya.\n"
            "Resident (Sunita tai): Hamare yahan tanker bhi late aata hai, subah 11 baje.\n"
            "Ward officer: Pipeline repair ka kaam Friday tak khatam hoga, tab tak tanker subah 7 baje aayega.\n"
            "Sarpanch: Theek hai. Complaint register bhi voice se bharenge, Charcha se.\n"
            "Resident: Aur street light ka kya? Gali number 4 mein andhera hai."
        ),
        "summary": (
            "Ward 7 has had no tap water for three days. Pipeline repairs finish by Friday; until then the tanker comes at 7 am "
            "instead of 11 am. Complaints will be logged by voice. Residents also raised the broken street light in lane 4."
        ),
        "tasks": [
            ("Ward officer", "Finish the Ward 7 pipeline repair", 5, "High", "in_progress"),
            ("Ward officer", "Move the water tanker to 7 am until the repair is done", 0, "High", "pending"),
            ("Sarpanch", "Raise the lane 4 street light complaint with the electricity board", 7, "Medium", "pending"),
        ],
        "decisions": [
            ("Complaints at the gram sabha are logged by voice", "Most residents prefer speaking to filling forms", ["Paper complaint register"], None),
            ("Tanker arrives at 7 am until the pipeline is fixed", "Families need water before work and school", ["Keep 11 am"], None),
        ],
        "risks": [("Pipeline repair may slip past Friday if parts are late", "High")],
    },
    {
        "title": "Class 8 PTM: spoken Hindi quiz pilot",
        "ago": 7, "minutes": 40, "source": "bot", "project": "Bolke seekho",
        "transcript": (
            "Teacher (Kavita ma'am): Bacche voice quiz mein 20 mein se average 14 la rahe hain.\n"
            "Parent (Mr Iyer): Mera beta Tamil bolta hai ghar pe, kya quiz Tamil mein ho sakta hai?\n"
            "Archit: Haan, Gnani Tamil support karta hai, next week se Tamil option denge.\n"
            "Teacher: Aur weekly report parents ko WhatsApp pe chahiye.\n"
            "Parent: Quiz raat 9 baje ke baad nahi hona chahiye."
        ),
        "summary": (
            "Class 8 students average 14/20 on the spoken Hindi quiz. Parents asked for a Tamil option, which starts next week, "
            "a weekly WhatsApp report, and no quizzes after 9 pm."
        ),
        "tasks": [
            ("me", "Add the Tamil option to the spoken quiz", 6, "High", "pending"),
            ("Kavita ma'am", "Send the first weekly WhatsApp report to parents", 4, "Medium", "pending"),
        ],
        "decisions": [
            ("No quizzes after 9 pm", "Parents want evenings free for sleep", None, None),
            ("Weekly progress goes to parents on WhatsApp", "Parents check WhatsApp, not email", ["Email report"], None),
        ],
        "risks": [("Tamil accuracy is untested with children's voices", "Medium")],
    },
    {
        "title": "Accessibility review with older users",
        "ago": 10, "minutes": 30, "source": "record", "project": "Charcha app",
        "transcript": (
            "Shanti ji (72): Chhote button dikhte nahi. Bas bolne ka button bada ho.\n"
            "Vedant: Aap bolke poochhengi toh Charcha jawab bolke sunayega.\n"
            "Shanti ji: Haan, yeh accha hai. Awaaz thodi dheemi ho.\n"
            "Archit: Hum speech speed slow kar denge aur text bada.\n"
            "Ramesh ji (68): Mujhe Marathi mein sunna hai."
        ),
        "summary": (
            "Older users want one large speak button, answers read aloud more slowly, bigger text, and Marathi speech."
        ),
        "tasks": [
            ("mate", "Add a slower speech option for spoken answers", 5, "Medium", "pending"),
            ("me", "Test Marathi read-aloud with Ramesh ji", 8, "Low", "pending"),
        ],
        "decisions": [
            ("Spoken answers get a slow speed for older users", "Shanti ji found normal speed too fast", None, None),
        ],
        "risks": [],
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


async def main(emails: list[str], reset: bool) -> None:
    async with async_session() as db:
        users = []
        for email in emails:
            user = await db.scalar(select(User).where(func.lower(User.email) == email.lower()))
            if user is None:
                sys.exit(f"No account for {email}. Sign up first, then re-run.")
            users.append(user)
        owner, mate = users[0], users[1] if len(users) > 1 else users[0]

        existing = (await db.scalars(select(Meeting).where(Meeting.client_meeting_id.like(f"{SEED_PREFIX}%")))).all()
        if existing and not reset:
            # Top up: add demo decisions missing from the seeded meetings,
            # leaving everything people have changed untouched.
            added = 0
            for meeting in existing:
                spec = MEETINGS[int(meeting.client_meeting_id.removeprefix(SEED_PREFIX))]
                have = set((await db.scalars(select(Decision.decision).where(Decision.meeting_id == meeting.id))).all())
                project_id = await db.scalar(select(Project.id).where(Project.name == spec["project"]))
                speakers = {line.split(":", 1)[0].split(" (")[0] for line in spec["transcript"].splitlines()}
                for entry in spec["decisions"]:
                    if entry[0] not in have:
                        db.add(_decision(meeting.id, project_id, entry, speakers))
                        added += 1
            await db.commit()
            print(f"Demo data already present ({len(existing)} meetings); added {added} missing decisions.")
            skip = {int(m.client_meeting_id.removeprefix(SEED_PREFIX)) for m in existing}
            if len(skip) >= len(MEETINGS):
                print("Every demo meeting is present. Use --reset to rebuild it all.")
                return
        else:
            skip = set()
        if existing and reset:
            await db.execute(delete(Meeting).where(Meeting.client_meeting_id.like(f"{SEED_PREFIX}%")))
            await db.flush()

        def who(key: str) -> tuple[str, User | None]:
            if key == "me":
                return owner.name or owner.email.split("@")[0], owner
            if key == "mate":
                return mate.name or mate.email.split("@")[0], mate
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

            when = NOW - timedelta(days=spec["ago"], hours=2 + index)
            meeting = Meeting(
                user_id=owner.id,
                organizer_user_id=owner.id,
                title=spec["title"],
                date=when,
                transcript=spec["transcript"],
                summary=spec["summary"],
                duration_minutes=spec["minutes"],
                source=spec["source"],
                client_meeting_id=f"{SEED_PREFIX}{index}",
            )
            meeting.projects.append(project)
            db.add(meeting)
            await db.flush()
            counts["meetings"] += 1

            for user in {u.id: u for u in users}.values():
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

        await db.commit()
        print("Seeded demo data:", ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    asyncio.run(main(args, reset="--reset" in sys.argv))
