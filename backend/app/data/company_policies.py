# Sample team handbook used by the policy assistant ("Ask Policy").
#
# This is illustrative demo content written for the hackathon build. It is
# not any real company's policy. Replace it with your own organisation's
# handbook, then re-run scripts/ingest_policies.py. Upserts are keyed by id,
# so re-running overwrites chunks in place.
#
# Keep numbers explicit. The assistant is told to quote exact figures and
# never infer them, so every fact it should answer must be written out here.

HANDBOOK = "Sample Team Handbook"
HOLIDAY_CALENDAR = "Holiday Calendar (FY 2026-27)"

POLICY_CHUNKS = [
    {
        "id": "handbook_about",
        "document": HANDBOOK,
        "section": "About this Handbook",
        "text": (
            "This sample handbook shows how Wilco answers questions about team "
            "policies. It is demo content, not an employment contract. Teams using "
            "Wilco should replace it with their own policies."
        ),
    },
    {
        "id": "handbook_working_hours",
        "document": HANDBOOK,
        "section": "Attendance Policy — Working Hours",
        "text": (
            "Standard working hours are 10:00 AM to 6:30 PM, Monday to Friday, "
            "including a 30-minute lunch break. Saturday and Sunday are weekly offs."
        ),
    },
    {
        "id": "handbook_remote_work",
        "document": HANDBOOK,
        "section": "Remote Work Policy",
        "text": (
            "Team members may work remotely up to 2 days per week, with their "
            "manager's approval. Remote days must be logged on the team calendar a "
            "day in advance."
        ),
    },
    {
        "id": "handbook_casual_sick_leave",
        "document": HANDBOOK,
        "section": "Leave Policy — Casual Leave (CL) & Sick Leave (SL)",
        "text": (
            "Each team member receives 6 Casual Leave days and 6 Sick Leave days per "
            "financial year. Casual Leave should be applied for at least 1 day in "
            "advance. Sick Leave longer than 2 consecutive days needs a medical "
            "certificate. Unused Casual and Sick Leave do not carry forward."
        ),
    },
    {
        "id": "handbook_earned_leave",
        "document": HANDBOOK,
        "section": "Leave Policy — Earned Leave (EL)",
        "text": (
            "Team members earn 12 Earned Leave days per financial year, accrued at 1 "
            "day per completed month. Up to 6 unused Earned Leave days carry forward "
            "to the next year."
        ),
    },
    {
        "id": "handbook_paid_holidays",
        "document": HANDBOOK,
        "section": "Leave Policy — Paid Holidays",
        "text": (
            "Every team member gets the Fixed Holidays in the Holiday Calendar, plus "
            "2 Floating Holidays of their choice from the Floating Holiday list."
        ),
    },
    {
        "id": "handbook_probation",
        "document": HANDBOOK,
        "section": "Probation & Notice Period Policy — Probation",
        "text": (
            "New team members serve a probation period of 3 months. During "
            "probation, either side may end employment with 7 days' notice."
        ),
    },
    {
        "id": "handbook_notice_period",
        "document": HANDBOOK,
        "section": "Probation & Notice Period Policy — Notice Period",
        "text": (
            "After probation, the standard notice period for resignation is 30 days. "
            "Earned Leave cannot be used to shorten the notice period."
        ),
    },
    {
        "id": "handbook_it_assets",
        "document": HANDBOOK,
        "section": "IT Assets Policy",
        "text": (
            "Laptops and accessories issued to team members remain team property and "
            "must be returned on the last working day. Report loss or theft to the "
            "admin within 24 hours."
        ),
    },
    {
        "id": "handbook_code_of_conduct",
        "document": HANDBOOK,
        "section": "Code of Conduct Policy",
        "text": (
            "Treat everyone with respect, keep customer and meeting data confidential, "
            "and raise concerns with your manager or the admin. Harassment and "
            "discrimination of any kind are not tolerated."
        ),
    },
    {
        "id": "holiday_calendar_fy2026_27",
        "document": HOLIDAY_CALENDAR,
        "section": "Holiday Calendar — April 2026 to March 2027",
        "text": (
            "There are two kinds of holidays. Do not mix the two lists and do not "
            "recount them; copy the counts and names exactly as given here.\n\n"
            "FIXED HOLIDAYS — exactly 6, given to every team member:\n"
            "1. Independence Day — Saturday, 15-Aug-2026\n"
            "2. Gandhi Jayanti — Friday, 2-Oct-2026\n"
            "3. Dussehra — Tuesday, 20-Oct-2026\n"
            "4. Christmas — Friday, 25-Dec-2026\n"
            "5. Republic Day — Tuesday, 26-Jan-2027\n"
            "6. Holi — Wednesday, 24-Mar-2027\n\n"
            "FLOATING HOLIDAYS — exactly 4 on the list, of which each team member may "
            "choose 2 per year:\n"
            "1. Raksha Bandhan — Friday, 28-Aug-2026\n"
            "2. Guru Nanak Jayanti — Tuesday, 24-Nov-2026\n"
            "3. Pongal / Makar Sankranti — Thursday, 14-Jan-2027\n"
            "4. Eid-ul-Fitr — Wednesday, 10-Mar-2027\n\n"
            "OTHER: Diwali — Sunday, 8-Nov-2026 — falls on a weekly off, so it is not "
            "counted as a separate paid holiday."
        ),
    },
]
