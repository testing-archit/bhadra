import io
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NEEL = colors.HexColor("#2E2A8C")
DARK = colors.HexColor("#1D1A3B")
MUTED = colors.HexColor("#6B6889")
LIGHT = colors.HexColor("#ECEBFA")
BORDER = colors.HexColor("#EBE5DA")
INDIA_TZ = ZoneInfo("Asia/Kolkata")


def _register_fonts() -> tuple[str, str]:
    regular = Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf")
    bold = Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
    devanagari = Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf")
    devanagari_bold = Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf")
    if all(path.exists() for path in (regular, bold, devanagari, devanagari_bold)):
        if "CharchaSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("CharchaSans", str(regular), shapable=True))
            pdfmetrics.registerFont(TTFont("CharchaSans-Bold", str(bold), shapable=True))
            pdfmetrics.registerFont(TTFont("CharchaDevanagari", str(devanagari), shapable=True))
            pdfmetrics.registerFont(TTFont("CharchaDevanagari-Bold", str(devanagari_bold), shapable=True))
            pdfmetrics.registerFontFamily(
                "CharchaSans", normal="CharchaSans", bold="CharchaSans-Bold"
            )
            pdfmetrics.registerFontFamily(
                "CharchaDevanagari",
                normal="CharchaDevanagari",
                bold="CharchaDevanagari-Bold",
            )
        return "CharchaSans", "CharchaSans-Bold"
    return "Helvetica", "Helvetica-Bold"


def _styles():
    regular_font, bold_font = _register_fonts()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Brand", parent=styles["Normal"], fontName=bold_font, fontSize=13, textColor=DARK, leading=16, shaping=1))
    styles.add(ParagraphStyle(name="DocumentTitle", parent=styles["Title"], fontName=bold_font, fontSize=22, leading=27, textColor=DARK, spaceAfter=5, shaping=1))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName=bold_font, fontSize=13, leading=17, textColor=NEEL, spaceBefore=13, spaceAfter=7, shaping=1))
    styles.add(ParagraphStyle(name="Subsection", parent=styles["Heading3"], fontName=bold_font, fontSize=10.5, leading=14, textColor=DARK, spaceBefore=8, spaceAfter=4, shaping=1))
    styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontName=regular_font, fontSize=9.2, leading=14, textColor=DARK, spaceAfter=6, shaping=1))
    styles.add(ParagraphStyle(name="Meta", parent=styles["Normal"], fontName=regular_font, fontSize=8.5, leading=12, textColor=MUTED, shaping=1))
    styles.add(ParagraphStyle(name="BulletSmall", parent=styles["BodyText"], fontName=regular_font, fontSize=9.2, leading=14, leftIndent=12, firstLineIndent=-7, textColor=DARK, bulletIndent=2, spaceAfter=3, shaping=1))
    styles.add(ParagraphStyle(name="Transcript", parent=styles["BodyText"], fontName=regular_font, fontSize=8.3, leading=12.5, textColor=DARK, spaceAfter=4, shaping=1))
    styles.add(ParagraphStyle(name="Footer", parent=styles["Normal"], fontName=regular_font, fontSize=7.5, textColor=MUTED, alignment=TA_CENTER, shaping=1))
    return styles


def _wrap_devanagari(text: str) -> str:
    return re.sub(
        r"[\u0900-\u097F]+(?:[\s.,!?।:;()'\"\-/–—]*[\u0900-\u097F]+)*",
        lambda match: f'<font name="CharchaDevanagari">{match.group(0)}</font>',
        text,
    )


def _text(value) -> str:
    return _wrap_devanagari(escape(str(value or "Not recorded")))


def _inline_markup(value: str) -> str:
    text = escape(value)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    return _wrap_devanagari(text)


def _section(title: str, styles) -> list:
    return [Paragraph(escape(title), styles["Section"])]


def _summary_flowables(summary: str, styles) -> list:
    known_headings = {
        "Executive overview",
        "Discussion details",
        "Decisions and rationale",
        "Commitments",
        "Risks and unresolved questions",
    }
    story = []
    for raw in summary.splitlines():
        line = re.sub(r"^#{1,6}\s*", "", raw.strip())
        plain_line = re.sub(r"^\*\*(.+)\*\*$", r"\1", line)
        if not line:
            story.append(Spacer(1, 2 * mm))
        elif plain_line in known_headings:
            story.append(Paragraph(escape(plain_line), styles["Subsection"]))
        elif line.startswith(("- ", "* ")):
            story.append(Paragraph(_inline_markup(line[2:]), styles["BulletSmall"], bulletText="•"))
        else:
            story.append(Paragraph(_inline_markup(line), styles["BodySmall"]))
    return story


def _footer(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setStrokeColor(BORDER)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont(_register_fonts()[0], 7.5)
    canvas.drawString(18 * mm, 9 * mm, "WILCO  |  Built by team Bhadra")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_meeting_pdf(meeting, insight, recording) -> bytes:
    buffer = io.BytesIO()
    styles = _styles()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
        title=meeting.title,
        author="Wilco by team Bhadra",
        subject="Meeting intelligence report",
    )
    story = []

    logo_path = Path(__file__).resolve().parents[1] / "assets" / "wilco-logo.png"
    logo = Image(str(logo_path), width=12 * mm, height=12 * mm) if logo_path.exists() else Spacer(12 * mm, 12 * mm)
    brand = Paragraph("WILCO<br/><font size='8' color='#6B6889'>BUILT BY TEAM BHADRA</font>", styles["Brand"])
    brand_row = Table([[logo, brand]], colWidths=[15 * mm, 60 * mm], hAlign="LEFT")
    brand_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story.extend([brand_row, Spacer(1, 8 * mm), Paragraph(_text(meeting.title), styles["DocumentTitle"]), Paragraph("Meeting intelligence report", styles["Meta"]), Spacer(1, 6 * mm)])

    participants = ", ".join(recording.participants or []) if recording else "Not recorded"
    active_projects = [project for project in meeting.projects if project.deleted_at is None]
    projects = ", ".join(project.name for project in active_projects) or "Unassigned"
    meeting_date = meeting.date.astimezone(INDIA_TZ)
    meta = [
        [Paragraph("DATE", styles["Meta"]), Paragraph("DURATION", styles["Meta"]), Paragraph("FORMAT", styles["Meta"])],
        [Paragraph(_text(meeting_date.strftime("%d %B %Y, %I:%M %p IST")), styles["BodySmall"]), Paragraph(_text(f"{meeting.duration_minutes} minutes"), styles["BodySmall"]), Paragraph(_text(recording.meeting_type.title() if recording else "Imported"), styles["BodySmall"])],
        [Paragraph("PARTICIPANTS", styles["Meta"]), Paragraph("PROJECTS", styles["Meta"]), ""],
        [Paragraph(_text(participants), styles["BodySmall"]), Paragraph(_text(projects), styles["BodySmall"]), ""],
    ]
    meta_table = Table(meta, colWidths=[62 * mm, 62 * mm, 35 * mm])
    meta_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("SPAN", (1, 2), (2, 2)), ("SPAN", (1, 3), (2, 3)), ("BOX", (0, 0), (-1, -1), 0.5, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.extend([meta_table, Spacer(1, 5 * mm)])

    story += _section("Detailed summary", styles)
    story += _summary_flowables(meeting.summary or "No summary is available.", styles)

    active_tasks = [task for task in meeting.tasks if task.deleted_at is None]
    if insight:
        for heading, values in (
            ("Key topics", insight.key_topics or []),
            ("Highlights", insight.highlights or []),
            ("Open questions", insight.open_questions or []),
            # The AI's next steps restate the tasks in text that task edits
            # never reach; the tasks table below is the list once there is one.
            ("Next steps", [] if active_tasks else insight.next_steps or []),
        ):
            if values:
                story += _section(heading, styles)
                story += [Paragraph(_text(value), styles["BulletSmall"], bulletText="•") for value in values]

    story += _section("Tasks and commitments", styles)
    if active_tasks:
        task_rows = [[Paragraph("STATUS", styles["Meta"]), Paragraph("TASK", styles["Meta"]), Paragraph("OWNER / DUE", styles["Meta"])]]
        for task in active_tasks:
            owner_due = " · ".join(value for value in (task.owner, task.deadline, task.priority) if value) or "Not assigned"
            task_rows.append([Paragraph(_text(task.status.title()), styles["BodySmall"]), Paragraph(_text(task.description), styles["BodySmall"]), Paragraph(_text(owner_due), styles["BodySmall"])])
        task_table = Table(task_rows, colWidths=[24 * mm, 89 * mm, 46 * mm], repeatRows=1)
        task_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), DARK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.35, BORDER), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story.append(task_table)
    else:
        story.append(Paragraph("No tasks were recorded.", styles["BodySmall"]))

    story += _section("Decisions", styles)
    active_decisions = [decision for decision in meeting.decisions if decision.deleted_at is None]
    if active_decisions:
        for index, decision in enumerate(active_decisions, 1):
            details = [Paragraph(f"{index}. {_text(decision.decision)}", styles["Subsection"])]
            if decision.reason:
                details.append(Paragraph(f"<b>Rationale:</b> {_text(decision.reason)}", styles["BodySmall"]))
            if decision.alternatives:
                details.append(Paragraph(f"<b>Alternatives considered:</b> {_text(', '.join(decision.alternatives))}", styles["BodySmall"]))
            if decision.conflict_note:
                details.append(Paragraph(f"<b>Historical conflict:</b> {_text(decision.conflict_note)}", styles["BodySmall"]))
            story.append(KeepTogether(details))
    else:
        story.append(Paragraph("No decisions were recorded.", styles["BodySmall"]))

    story += _section("Risks", styles)
    active_risks = [risk for risk in meeting.risks if risk.deleted_at is None]
    if active_risks:
        story += [Paragraph(f"{_text(risk.description)} ({_text(risk.severity or 'Unrated')})", styles["BulletSmall"], bulletText="•") for risk in active_risks]
    else:
        story.append(Paragraph("No risks were recorded.", styles["BodySmall"]))

    if insight and insight.speaker_activity:
        story += _section("Speaker participation", styles)
        for speaker in insight.speaker_activity:
            share = round(float(speaker.get("share", 0)) * 100)
            story.append(Paragraph(f"{_text(speaker.get('speaker'))}: {share}% ({int(speaker.get('words', 0))} words)", styles["BulletSmall"], bulletText="•"))

    if meeting.transcript:
        story.extend([CondPageBreak(55 * mm), Paragraph("Full transcript", styles["Section"]), Paragraph("Speaker labels reflect the latest saved diarization corrections.", styles["Meta"]), Spacer(1, 3 * mm)])
        for line in meeting.transcript.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^([^:]{1,80}):\s*(.*)$", line)
            content = f"<b>{_text(match.group(1))}:</b> {_text(match.group(2))}" if match else _text(line)
            story.append(Paragraph(content, styles["Transcript"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
