from html import escape
from importlib.resources import files
from pathlib import Path

from playwright.sync_api import sync_playwright

from resume_agent.config import Config
from resume_agent.documents import CoverLetter, Resume, Role, Section

CSS = files("resume_agent").joinpath("templates/document.css").read_text()
CONTENT_WIDTH_PX = 720
MAX_CONTACT_ROWS = 2
COUNT_CONTACT_ROWS_JS = """
() => new Set(
  [...document.querySelectorAll('.contact > .item')].map((item) => item.offsetTop)
).size
"""
REGULAR_SPACE = '<span class="space"> </span>'
CONTACT_SEPARATOR_TEXT = "|"
CONTACT_SEPARATOR = f" {CONTACT_SEPARATOR_TEXT} "
ROLE_SEPARATOR = " @ "


class RenderError(Exception):
    pass


def text_html(text: str) -> str:
    # Helvetica Neue Bold and Italic spaces lack a ToUnicode entry, so extractors split words.
    return REGULAR_SPACE.join(escape(part) for part in text.split(" "))


def contact_items(config: Config) -> list[tuple[str, str | None]]:
    return [
        (config.email, f"mailto:{config.email}"),
        (config.phone, None),
        (config.location, None),
        (config.links.github, f"https://{config.links.github}"),
        (config.links.linkedin, f"https://{config.links.linkedin}"),
    ]


def contact_item_html(text: str, href: str | None) -> str:
    return f'<a href="{escape(href)}">{text_html(text)}</a>' if href else text_html(text)


def contact_html(config: Config) -> str:
    spans = CONTACT_SEPARATOR.join(
        f'<span class="item">{contact_item_html(*item)}</span>' for item in contact_items(config)
    )
    return f'<div class="contact">{spans}</div>'


def header_html(config: Config, headline: str = "") -> str:
    parts = [f'<div class="name">{text_html(config.name)}</div>', contact_html(config)]
    if headline:
        parts.append(f'<div class="headline">{text_html(headline)}</div>')
    return f"<header>{''.join(parts)}</header>"


def labelled_html(text: str) -> str:
    label, separator, rest = text.partition(": ")
    if not separator:
        return text_html(text)
    return f'<span class="skill-label">{text_html(label)}:</span> {text_html(rest)}'


def role_heading_html(heading: str) -> str:
    title, separator, rest = heading.partition(ROLE_SEPARATOR)
    title_html = f'<span class="role-title">{text_html(title)}</span>'
    if not separator:
        return title_html
    return f'{title_html}{text_html(separator)}<span class="role-subtitle">{text_html(rest)}</span>'


def role_html(role: Role) -> str:
    bullets = "".join(f"<li>{text_html(bullet)}</li>" for bullet in role.bullets)
    subtitle = (
        f'<div class="role-subtitle">{text_html(role.subtitle)}</div>' if role.subtitle else ""
    )
    return (
        f'<div class="role{"" if bullets else " compact"}">'
        f'<div class="role-heading">{role_heading_html(role.title)}</div>'
        f"{subtitle}"
        f"{f'<ul>{bullets}</ul>' if bullets else ''}"
        "</div>"
    )


def section_html(section: Section) -> str:
    parts = [f"<h2>{text_html(section.title)}</h2>"]
    parts.extend(role_html(role) for role in section.roles)
    if section.items:
        rows = "".join(f"<div>{labelled_html(item)}</div>" for item in section.items)
        parts.append(f'<div class="skills">{rows}</div>')
    parts.extend(f'<div class="paragraph">{text_html(text)}</div>' for text in section.paragraphs)
    return f"<section>{''.join(parts)}</section>"


def page_html(title: str, body: str) -> str:
    return (
        "<!doctype html>"
        f'<html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>'
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )


def resume_html(resume: Resume, config: Config) -> str:
    sections = "".join(section_html(section) for section in resume.sections)
    return page_html(f"{config.name} Resume", header_html(config, resume.headline) + sections)


def cover_letter_html(letter: CoverLetter, config: Config) -> str:
    paragraphs = "".join(f"<p>{text_html(text)}</p>" for text in letter.paragraphs)
    signature_lines = [
        text_html(letter.closing),
        text_html(config.name),
        *(contact_item_html(*item) for item in contact_items(config)),
    ]
    signature = f"<p>{'<br>'.join(signature_lines)}</p>"
    body = (
        header_html(config)
        + f"<h2>{text_html(letter.title)}</h2>"
        + f'<div class="letter">{paragraphs}{signature}</div>'
    )
    return page_html(f"{config.name} {letter.title}", body)


def render_pdf(html: str, output: Path) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(
                viewport={
                    "width": CONTENT_WIDTH_PX,
                    "height": 1000,
                }
            )
            page.set_content(html, wait_until="load")
            rows = page.evaluate(COUNT_CONTACT_ROWS_JS)
            if rows > MAX_CONTACT_ROWS:
                raise RenderError(
                    f"Contact line needs {rows} rows; shorten it to fit {MAX_CONTACT_ROWS}."
                )
            page.pdf(path=str(output), prefer_css_page_size=True, print_background=True)
        finally:
            browser.close()
