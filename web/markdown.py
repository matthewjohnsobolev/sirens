"""
Markdown content negotiation and representations for AI agents.
Conforms to the agent readiness markdown-negotiation skill and Cloudflare Markdown for Agents standard.
"""

from __future__ import annotations

import json
from typing import Any

from flask import Response


def wants_markdown(accept_header: str | None) -> bool:
    """
    Determines whether the client prefers text/markdown over HTML.

    Follows HTTP content negotiation rules:
    - Only explicit text/markdown requests trigger markdown responses.
    - Browsers sending text/html or wildcards (*/*, text/*) default to HTML.
    - Quality weights (q=...) are respected.
    - Media-type parameters (e.g., charset=utf-8) are stripped during media-type comparison.
    """
    if not accept_header:
        return False

    items: list[tuple[str, float]] = []
    for part in accept_header.split(","):
        part = part.strip()
        if not part:
            continue
        subparts = [p.strip() for p in part.split(";")]
        media_type = subparts[0].lower()
        q = 1.0
        for param in subparts[1:]:
            if param.lower().startswith("q="):
                try:
                    q = float(param[2:].strip())
                except ValueError:
                    pass
        items.append((media_type, q))

    markdown_q = max([q for mt, q in items if mt == "text/markdown"] or [0.0])
    if markdown_q <= 0.0:
        return False

    html_q = max([q for mt, q in items if mt == "text/html"] or [0.0])
    wildcard_q = max([q for mt, q in items if mt in ("*/*", "text/*")] or [0.0])

    if html_q > 0.0 and markdown_q <= html_q:
        return False

    return markdown_q >= wildcard_q


def estimate_tokens(text: str) -> int:
    """
    Estimates token count using the standard character-based heuristic (~4 characters/token).
    """
    return max(1, round(len(text) / 4))


def _yaml_escape(val: str) -> str:
    if any(c in val for c in ("\\", ":", "\n", '"', "'", "#", "{", "}", "[", "]")):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return val


def format_frontmatter(
    title: str | None = None,
    description: str | None = None,
    image: str | None = None,
) -> str:
    """
    Builds YAML frontmatter extracted from meta tags, per Cloudflare specification.
    Only emitted if at least one field has a value.
    """
    lines: list[str] = []
    if title:
        lines.append(f"title: {_yaml_escape(title)}")
    if description:
        lines.append(f"description: {_yaml_escape(description)}")
    if image:
        lines.append(f"image: {_yaml_escape(image)}")
    if not lines:
        return ""
    return "---\n" + "\n".join(lines) + "\n---"


def format_json_ld(data: dict[str, Any] | list[Any] | str | None) -> str:
    """
    Appends JSON-LD structured data in a fenced json code block, per Cloudflare specification.
    """
    if not data:
        return ""
    if isinstance(data, (dict, list)):
        payload = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        payload = data.strip()
    return f"```json\n{payload}\n```"


def render_index_markdown(site_url: str) -> str:
    """
    Builds clean Markdown representation of the Sirens homepage for AI agents.
    """
    frontmatter = format_frontmatter(
        title="Сирени",
        description="Мапа повітряних тривог України в реальному часі: тривоги, загрози обстрілу та вибухи по областях і районах за даними офіційних Telegram-каналів.",
        image=f"{site_url}/static/img/og-banner.png",
    )

    body = (
        "# Сирени\n\n"
        "Мапа повітряних тривог України в реальному часі: тривоги, загрози обстрілу та вибухи по областях і районах за даними офіційних Telegram-каналів.\n\n"
        "## Можливості та розділи\n\n"
        "- **Мапа тривог:** Інтерактивна мапа України зі статусом повітряних тривог, артилерійських обстрілів та загроз у реальному часі.\n"
        f"- **API загроз:** [{site_url}/api]({site_url}/api) — актуальний стан тривог, вибухів та артобстрілів (JSON).\n"
        f"- **Повідомити про збій:** [{site_url}/issue]({site_url}/issue) — форма зворотного зв'язку про помилки у сповіщеннях чи мапі.\n"
        "- **Стан системи:** [https://status.sirens.live](https://status.sirens.live) — моніторинг доступності компонентів сервісу.\n\n"
        "## Джерела даних\n\n"
        "Дані агрегуються з офіційних каналів цивільного захисту та ОВА в Telegram. "
        "Сервіс є незалежним джерелом і не замінює офіційну систему оповіщення цивільного захисту."
    )

    json_ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{site_url}/#organization",
                "name": "Сирени",
                "url": f"{site_url}/",
                "logo": f"{site_url}/static/img/logo.svg",
            },
            {
                "@type": "WebSite",
                "@id": f"{site_url}/#website",
                "name": "Сирени",
                "url": f"{site_url}/",
                "inLanguage": "uk-UA",
                "publisher": {"@id": f"{site_url}/#organization"},
            },
            {
                "@type": "WebApplication",
                "name": "Сирени — мапа повітряних тривог",
                "url": f"{site_url}/",
                "applicationCategory": "https://schema.org/UtilitiesApplication",
                "operatingSystem": "Any",
                "browserRequirements": "JavaScript",
                "inLanguage": "uk-UA",
                "isAccessibleForFree": True,
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "UAH"},
                "publisher": {"@id": f"{site_url}/#organization"},
            },
        ],
    }

    parts = [frontmatter, body, format_json_ld(json_ld)]
    return "\n\n".join(p for p in parts if p) + "\n"


def render_issue_markdown(site_url: str, success: bool = False) -> str:
    """
    Builds clean Markdown representation of the issue report page for AI agents.
    """
    if success:
        return (
            "# Повідомлення надіслано\n\n"
            "Дякуємо, повідомлення отримали. Розберемось.\n\n"
            f"- [Мапа тривог]({site_url}/)\n"
            f"- [Надіслати ще одне повідомлення]({site_url}/issue)\n"
        )

    frontmatter = format_frontmatter(
        title="Повідомити про збій | Сирени",
        description="Повідомити про помилку або збій у роботі «Сирен»: сповіщення не прийшло, мапа показує не те, форма чи API не працюють. Опишіть проблему — розберемось.",
        image=f"{site_url}/static/img/og-banner.png",
    )

    body = (
        "# Повідомити про збій\n\n"
        "Якщо ви помітили неточність у роботі мапи, затримку сповіщення або проблему з сайтом чи API, надішліть звіт про помилку.\n\n"
        "## Категорії збоїв\n\n"
        "- **Сповіщення:** Проблеми зі сповіщеннями (тривогу не оголосили або не відбійнули, хибна тривога тощо; обов'язково вказати місто та час).\n"
        "- **Мапа тривог:** Проблеми з відображенням на мапі (область або район не зафарбувались тощо; обов'язково вказати район або місто та час).\n"
        "- **Інше:** Пропозиції або зауваження до роботи сайту чи API (обов'язково додати текстовий опис).\n\n"
        "## Як надіслати звіт через API\n\n"
        f"Надішліть HTTP POST-запит на `{site_url}/issue` з полями форми (`application/x-www-form-urlencoded`):\n"
        "- `category`: Категорія («Сповіщення», «Мапа тривог», «Інше»)\n"
        "- `sub_option`: Уточнення проблеми для обраної категорії\n"
        "- `city`: Місто (обов'язково для категорії «Сповіщення»)\n"
        "- `district`: Район (для категорії «Мапа тривог»)\n"
        "- `time`: Час інциденту (наприклад, «Щойно», «5 хв тому» або конкретні дата/час)\n"
        "- `message`: Довільний коментар (до 1000 символів)\n"
        "- `contact`: Контакт у Telegram (наприклад, `@username`, необов'язково)\n\n"
        "## Посилання\n\n"
        f"- [Мапа тривог]({site_url}/)\n"
        "- [Стан системи](https://status.sirens.live)\n\n"
        "> «Сирени» — незалежний сервіс агрегації повітряних тривог. Це не заміна офіційної системи оповіщення."
    )

    json_ld = {
        "@context": "https://schema.org",
        "@type": "ContactPage",
        "name": "Повідомити про збій | Сирени",
        "url": f"{site_url}/issue",
        "inLanguage": "uk-UA",
        "isPartOf": {"@type": "WebSite", "@id": f"{site_url}/#website"},
    }

    parts = [frontmatter, body, format_json_ld(json_ld)]
    return "\n\n".join(p for p in parts if p) + "\n"


def render_error_markdown(error_code: int, error_message: str, site_url: str) -> str:
    """
    Builds clean Markdown representation for HTTP error responses.
    """
    frontmatter = format_frontmatter(
        title=f"{error_message} | Сирени",
        description=f"Помилка {error_code} — {error_message}",
    )

    body = (
        f"# {error_code} — {error_message}\n\n"
        f"- [Головна сторінка]({site_url}/)\n"
        f"- [Повідомити про збій]({site_url}/issue)\n"
        "- [Стан системи](https://status.sirens.live)\n"
    )

    parts = [frontmatter, body]
    return "\n\n".join(p for p in parts if p) + "\n"


def markdown_response(
    body: str,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    """
    Creates a Flask Response with proper Markdown for Agents headers.
    """
    tokens = estimate_tokens(body)
    resp = Response(body, status=status_code, mimetype="text/markdown")
    resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
    resp.headers["x-markdown-tokens"] = str(tokens)
    resp.headers["Content-Signal"] = "ai-train=yes, search=yes, ai-input=yes"
    resp.headers["Vary"] = "Accept"
    if headers:
        for k, v in headers.items():
            resp.headers[k] = v
    return resp
