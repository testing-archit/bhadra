"""Synthetic demo workspace: Hinglish meetings with tasks, decisions and risks.

Everything here is invented. Used by scripts/seed_demo.py and by the
no-sign-up demo (POST /api/auth/demo), which seeds one per guest."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.database.models import Decision, KhataEntry, Meeting, MeetingAttendee, MeetingTask, Project, Risk, User

SEED_PREFIX = "demo-seed-"


def days(n: int) -> date:
    return date.today() + timedelta(days=n)


# Each task: (owner_key, description, due offset in days or None, priority, status)
# owner_key "me"/"mate" maps to the first/second account; anything else is a name.
MEETINGS = [
    {
        "title": "Weekly product sync",
        "ago": 5, "minutes": 42, "source": "bot", "project": "Wilco app",
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
        "title": "Chennai distributor call (Tanglish)",
        "ago": 1, "minutes": 22, "source": "record", "project": "Kirana voice bookkeeping",
        "transcript": (
            "Karthik (distributor): Archit, indha week order konjam late aagum, truck Tuesday dhaan varum.\n"
            "Archit: Okay Karthik, but Sharma ji's Diwali stock Wednesday-kulla venum. Possible-aa?\n"
            "Karthik: Sugar and oil first truck-la anuppuren, mattha items Friday.\n"
            "Vedant: Payment UPI-la pannalaama? Last time cash-la confusion aachu.\n"
            "Karthik: Seri, UPI fine. Invoice WhatsApp-la anuppuren, Tamil-la.\n"
            "Archit: Super. Naan Tuesday evening confirm panren."
        ),
        "summary": (
            "Karthik's truck arrives Tuesday, so sugar and oil for Sharma ji's Diwali stock go on the first truck and "
            "the rest follows on Friday. Payment moves to UPI after last month's cash confusion, and Karthik will send a "
            "Tamil invoice on WhatsApp. Archit confirms on Tuesday evening."
        ),
        "tasks": [
            ("Karthik", "Send sugar and oil on Tuesday's first truck", 2, "High", "pending"),
            ("Karthik", "Send the invoice in Tamil on WhatsApp", 2, "Medium", "pending"),
            ("me", "Confirm the delivery with Karthik on Tuesday evening", 2, "Medium", "pending"),
            ("mate", "Pay Karthik by UPI once the invoice arrives", 4, "Medium", "pending"),
        ],
        "decisions": [
            ("Pay the distributor by UPI, not cash", "Cash payments caused confusion last month", ["Cash on delivery"], None),
            ("Sugar and oil ship first; other items on Friday", "Sharma ji's Diwali stock is needed by Wednesday", None, None),
        ],
        "risks": [("Only one truck reaches before Wednesday; a delay misses the Diwali rush", "High")],
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
        "ago": 9, "minutes": 33, "source": "extension", "project": "Wilco app",
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
        "ago": 12, "minutes": 25, "source": "paste", "project": "Wilco app",
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
        "ago": 0, "minutes": 18, "source": "record", "project": "Kirana voice bookkeeping",
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
            "Sarpanch: Theek hai. Complaint register bhi voice se bharenge, Wilco se.\n"
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
        "ago": 10, "minutes": 30, "source": "record", "project": "Wilco app",
        "transcript": (
            "Shanti ji (72): Chhote button dikhte nahi. Bas bolne ka button bada ho.\n"
            "Vedant: Aap bolke poochhengi toh Wilco jawab bolke sunayega.\n"
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
    # Sharma ji's voice khata, matching the kirana meetings.
    from sqlalchemy import func as _func
    if not await db.scalar(select(_func.count()).select_from(KhataEntry).where(KhataEntry.user_id == owner.id)):
        for index, (customer, kind, amount, note, said) in enumerate(KHATA):
            db.add(KhataEntry(user_id=owner.id, customer=customer, customer_key=_khata_key(customer), kind=kind,
                              amount=amount, note=note, said=said, created_at=now - timedelta(days=len(KHATA) - index)))
    return counts


KHATA = [
    ("Gupta ji", "credit", 1100, "monthly ration", "Gupta ji ka mahine ka ration, gyarah sau udhaar likh do"),
    ("Meena didi", "credit", 380, "atta, sugar", "Meena didi teen sau assi ka atta cheeni le gayi, baad mein dengi"),
    ("Ramesh bhaiya", "credit", 640, "oil, dal", "Ramesh bhaiya chhe sau chaalees ka tel dal udhaar"),
    ("Meena didi", "payment", 200, None, "Meena didi ne do sau jama kiye"),
    ("Murugan anna", "credit", 450, "rice", "Murugan anna 450 rupees arisi kadan vaangitu ponaar"),
    ("Farida aunty", "credit", 260, "milk, bread", "Farida aunty doodh bread do sau saath udhaar"),
    ("Gupta ji", "payment", 500, None, "Gupta ji paanch sau de gaye"),
]


def _khata_key(name: str) -> str:
    from app.services.khata_service import customer_key
    return customer_key(name)
