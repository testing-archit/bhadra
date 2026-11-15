"""Wilco's email look: one branded layout, rendered to HTML + plain text.

Email clients ignore CSS variables and most <style> rules, so everything is
inline, table-based and in the app's brand colours (the hex equivalents of
the theme's oklch tokens). Clients that honour prefers-color-scheme (Apple
Mail, iOS, Outlook.com) get the dark palette from the <style> block.
"""

import html
import re

from app.config import settings

BRAND = {
    "primary": "#2E2A8C",
    "primary_text": "#ffffff",
    "text": "#1D1A3B",
    "muted": "#6B6889",
    "bg": "#FAF7F1",
    "card": "#ffffff",
    "border": "#EBE5DA",
    "soft": "#ECEBFA",
    "warning": "#b45309",
}
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
AVATAR_TONES = ["#2E2A8C", "#2f5d8a", "#7a4e9c", "#a14d3a", "#4f6b2a", "#8a6a14"]


def app_url(path: str = "/") -> str:
    base = (settings.public_app_url or "https://charcha.example.com").rstrip("/")
    return f"{base}{path}"


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def initials(name: str | None, email: str | None = None) -> str:
    words = [w for w in re.split(r"[\s._-]+", (name or "").strip()) if w]
    if not words and email:
        words = [email.split("@")[0]]
    letters = "".join(w[0] for w in words[:2]).upper()
    return letters or "?"


def avatar(name: str | None, email: str | None = None, size: int = 28) -> str:
    """A coloured initials circle — the same avatar the app shows for people."""
    key = (email or name or "?").lower()
    tone = AVATAR_TONES[sum(map(ord, key)) % len(AVATAR_TONES)]
    return (
        f'<span title="{esc(name or email)}" style="display:inline-block;width:{size}px;height:{size}px;'
        f"border-radius:50%;background:{tone};color:#ffffff;font:600 {round(size * 0.4)}px {FONT};line-height:{size}px;text-align:center;"
        f'margin-right:4px;vertical-align:middle;">{esc(initials(name, email))}</span>'
    )


def button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0 8px;"><tr>'
        f'<td class="btn" style="background:{BRAND["primary"]};border-radius:8px;">'
        f'<a href="{esc(url)}" style="display:inline-block;padding:12px 22px;font:600 15px {FONT};'
        f'color:{BRAND["primary_text"]};text-decoration:none;border-radius:8px;">{esc(label)}</a></td></tr></table>'
    )


def paragraph(text: str, *, muted: bool = False, size: int = 15) -> str:
    color = BRAND["muted"] if muted else BRAND["text"]
    cls = ' class="muted"' if muted else ""
    return f'<p{cls} style="margin:0 0 14px;font:{size}px/1.55 {FONT};color:{color};">{text}</p>'


def heading(text: str, size: int = 15) -> str:
    return f'<p style="margin:22px 0 8px;font:600 {size}px/1.4 {FONT};color:{BRAND["text"]};">{esc(text)}</p>'


def bullet_list(items: list[str]) -> str:
    """Items are already-escaped HTML."""
    rows = "".join(
        f'<tr><td style="padding:0 8px 8px 0;vertical-align:top;color:{BRAND["primary"]};font:15px/1.55 {FONT};">•</td>'
        f'<td style="padding:0 0 8px;font:15px/1.55 {FONT};color:{BRAND["text"]};">{item}</td></tr>'
        for item in items
    )
    return f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 6px;">{rows}</table>'


def callout(inner: str, tone: str = "soft") -> str:
    border = BRAND["warning"] if tone == "warning" else BRAND["border"]
    bg = "#fff7ed" if tone == "warning" else BRAND["soft"]
    return (
        f'<div class="callout" style="margin:16px 0;padding:14px 16px;border:1px solid {border};border-radius:10px;'
        f'background:{bg};">{inner}</div>'
    )


def small(text: str) -> str:
    return f'<span class="muted" style="font:13px {FONT};color:{BRAND["muted"]};">{text}</span>'


_BOLD = re.compile(r"\*\*(.+?)\*\*")


def markdown_lite(text: str, tag_titles: dict[str, str] | None = None) -> str:
    """The subset of markdown the AI briefs use: #/##/### headings, - or *
    bullets, **bold**, and [M1]-style citations (shown as small tags)."""
    tag_titles = tag_titles or {}

    def inline(line: str) -> str:
        out = _BOLD.sub(r"<strong>\1</strong>", esc(line))
        return re.sub(
            r"\[(M\d+)\]",
            lambda m: (
                f'<span class="muted" title="{esc(tag_titles.get(m.group(1), ""))}" style="font:11px {FONT};color:{BRAND["muted"]};'
                f'border:1px solid {BRAND["border"]};border-radius:4px;padding:0 4px;margin-left:2px;">{m.group(1)}</span>'
            ),
            out,
        )

    blocks: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            blocks.append(bullet_list(list(bullets)))
            bullets.clear()

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            flush()
            blocks.append(heading(line.lstrip("#").strip()))
        elif line[:2] in {"- ", "* "}:
            bullets.append(inline(line[2:]))
        else:
            flush()
            blocks.append(paragraph(inline(line)))
    flush()
    return "".join(blocks)


def html_to_text(fragment: str) -> str:
    text = re.sub(r"<(br|/p|/tr|/h\d|/div)[^>]*>", "\n", fragment)
    text = re.sub(r"<td[^>]*>•</td>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def layout(
    *,
    title: str,
    body: str,
    preheader: str = "",
    cta: tuple[str, str] | None = None,
    footer_reason: str = "",
    unsubscribe_url: str | None = None,
    manage_url: str | None = None,
) -> tuple[str, str]:
    """(html, text) for one email."""
    logo = app_url("/wilco-apple-touch-icon.png")
    cta_html = button(*cta) if cta else ""
    links = []
    if manage_url:
        links.append(f'<a href="{esc(manage_url)}" style="color:{BRAND["muted"]};">Email preferences</a>')
    if unsubscribe_url:
        links.append(f'<a href="{esc(unsubscribe_url)}" style="color:{BRAND["muted"]};">Unsubscribe from these</a>')
    footer = (
        f'<p class="muted" style="margin:0 0 6px;font:12px/1.5 {FONT};color:{BRAND["muted"]};">{esc(footer_reason)}</p>' if footer_reason else ""
    ) + (
        f'<p class="muted" style="margin:0;font:12px/1.5 {FONT};color:{BRAND["muted"]};">{" · ".join(links)}</p>' if links else ""
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>{esc(title)}</title>
<style>
@media (prefers-color-scheme: dark) {{
  .bg {{ background:#0e0f11 !important; }}
  .card {{ background:#16181b !important; border-color:#2a2e33 !important; }}
  .card p, .card td, .card strong, .card h1 {{ color:#eaebed !important; }}
  .muted, .card .muted {{ color:#a3a9b0 !important; }}
  .callout {{ background:#1d2125 !important; border-color:#2a2e33 !important; }}
  .btn {{ background:#A7A3FF !important; }}
  .btn a {{ color:#0e0f11 !important; }}
}}
@media (max-width:620px) {{ .card {{ padding:24px 20px !important; }} }}
</style></head>
<body style="margin:0;padding:0;background:{BRAND["bg"]};" class="bg">
<span style="display:none;max-height:0;overflow:hidden;opacity:0;">{esc(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="bg" style="background:{BRAND["bg"]};">
<tr><td align="center" style="padding:28px 12px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;">
    <tr><td style="padding:0 4px 16px;">
      <a href="{esc(app_url("/dashboard"))}" style="text-decoration:none;">
        <img src="{esc(logo)}" width="32" height="32" alt="" style="vertical-align:middle;border-radius:8px;border:0;">
        <span style="vertical-align:middle;margin-left:8px;font:600 18px {FONT};color:{BRAND["text"]};" class="muted">Wilco</span>
      </a>
    </td></tr>
    <tr><td class="card" style="background:{BRAND["card"]};border:1px solid {BRAND["border"]};border-radius:14px;padding:32px 32px 26px;">
      <h1 style="margin:0 0 16px;font:600 21px/1.35 {FONT};color:{BRAND["text"]};">{esc(title)}</h1>
      {body}
      {cta_html}
    </td></tr>
    <tr><td style="padding:18px 6px 0;">
      {footer}
      <p class="muted" style="margin:10px 0 0;font:12px/1.5 {FONT};color:{BRAND["muted"]};">Wilco by Bhadra · your team's meeting memory</p>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""
    text_parts = [title, "", html_to_text(body)]
    if cta:
        text_parts += ["", f"{cta[0]}: {cta[1]}"]
    if footer_reason:
        text_parts += ["", footer_reason]
    if manage_url:
        text_parts += [f"Email preferences: {manage_url}"]
    if unsubscribe_url:
        text_parts += [f"Unsubscribe: {unsubscribe_url}"]
    text_parts += ["", "Wilco by Bhadra"]
    return document, "\n".join(text_parts).strip() + "\n"
