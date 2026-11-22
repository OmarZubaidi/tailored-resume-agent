from html import escape
from importlib.resources import files
from pathlib import Path

from playwright.sync_api import sync_playwright

from resume_agent.config import Config
from resume_agent.documents import Resume, Section

CSS = files("resume_agent").joinpath("templates/document.css").read_text()
CONTENT_WIDTH_PX = 720
MAX_CONTACT_ROWS = 2
COUNT_CONTACT_ROWS_JS = """
() => new Set(
  [...document.querySelectorAll('.contact span')].map((item) => item.offsetTop)
).size
"""


class RenderError(Exception):
    pass


def contact_items(config: Config) -> list[tuple[str, str | None]]:
    return [
        (config.email, f"mailto:{config.email}"),
        (config.phone, None),
        (config.location, None),
        (config.links.github, f"https://{config.links.github}"),
        (config.links.linkedin, f"https://{config.links.linkedin}"),
    ]


def contact_html(config: Config) -> str:
    spans = []
    for text, href in contact_items(config):
        content = f'<a href="{escape(href)}">{escape(text)}</a>' if href else escape(text)
        spans.append(f"<span>{content}</span>")
    return f'<div class="contact">{"".join(spans)}</div>'


def header_html(config: Config, headline: str = "") -> str:
    parts = [f'<div class="name">{escape(config.name)}</div>', contact_html(config)]
    if headline:
        parts.append(f'<div class="headline">{escape(headline)}</div>')
    return f"<header>{''.join(parts)}</header>"


def labelled_html(text: str) -> str:
    label, separator, rest = text.partition(": ")
    if not separator:
        return escape(text)
    return f'<span class="skill-label">{escape(label)}:</span> {escape(rest)}'


def section_html(section: Section) -> str:
    parts = [f"<h2>{escape(section.title)}</h2>"]
    for role in section.roles:
        bullets = "".join(f"<li>{escape(bullet)}</li>" for bullet in role.bullets)
        parts.append(
            '<div class="role">'
            f'<div class="role-title">{escape(role.title)}</div>'
            f'<div class="role-subtitle">{escape(role.subtitle)}</div>'
            f"{f'<ul>{bullets}</ul>' if bullets else ''}"
            "</div>"
        )
    if section.items:
        rows = "".join(f"<div>{labelled_html(item)}</div>" for item in section.items)
        parts.append(f'<div class="skills">{rows}</div>')
    parts.extend(f'<div class="paragraph">{escape(text)}</div>' for text in section.paragraphs)
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
