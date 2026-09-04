"""
Unit tests for web/markdown.py
"""

from web.markdown import (
    _yaml_escape,
    estimate_tokens,
    format_frontmatter,
    format_json_ld,
    markdown_response,
    render_error_markdown,
    render_index_markdown,
    render_issue_markdown,
    wants_markdown,
)


def test_wants_markdown_explicit():
    assert wants_markdown("text/markdown") is True
    assert wants_markdown("text/markdown; charset=utf-8") is True
    assert wants_markdown("text/markdown;q=1.0") is True


def test_wants_markdown_quality_preference():
    assert wants_markdown("text/markdown;q=0.9, text/html;q=0.8") is True
    assert wants_markdown("text/markdown;q=0.8, text/html;q=0.9") is False
    assert wants_markdown("text/html, text/markdown") is False
    assert wants_markdown("text/plain, text/markdown;q=0.5") is True


def test_wants_markdown_browser_and_wildcard_defaults():
    assert (
        wants_markdown("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8") is False
    )
    assert wants_markdown("*/*") is False
    assert wants_markdown("text/*") is False
    assert wants_markdown("") is False
    assert wants_markdown(None) is False
    assert wants_markdown("text/markdown, */*") is True


def test_wants_markdown_malformed_q():
    assert wants_markdown("text/markdown;q=not-a-number") is True
    assert wants_markdown("   ") is False


def test_estimate_tokens():
    assert estimate_tokens("") == 1
    assert estimate_tokens("hello world") == max(1, round(len("hello world") / 4))
    long_text = "a" * 1000
    assert estimate_tokens(long_text) == 250


def test_yaml_escape():
    assert _yaml_escape("Simple") == "Simple"
    assert _yaml_escape("Title: Subtitle") == '"Title: Subtitle"'
    assert _yaml_escape('Contains "quotes"') == '"Contains \\"quotes\\""'
    assert _yaml_escape("Backslash \\ test") == '"Backslash \\\\ test"'


def test_format_frontmatter():
    assert format_frontmatter() == ""
    fm = format_frontmatter(
        title="Test Page", description="A description", image="https://example.com/img.png"
    )
    assert fm.startswith("---\n")
    assert fm.endswith("\n---")
    assert "title: Test Page" in fm
    assert "description: A description" in fm
    assert 'image: "https://example.com/img.png"' in fm


def test_format_json_ld():
    assert format_json_ld(None) == ""
    assert format_json_ld("") == ""

    dict_ld = format_json_ld({"@context": "https://schema.org", "name": "Test"})
    assert dict_ld.startswith("```json\n")
    assert dict_ld.endswith("\n```")
    assert '"name": "Test"' in dict_ld

    str_ld = format_json_ld('{"@context": "https://schema.org"}')
    assert str_ld.startswith("```json\n")
    assert str_ld.endswith("\n```")


def test_render_index_markdown():
    md = render_index_markdown("https://sirens.live")
    assert md.startswith("---\n")
    assert "title: Сирени" in md
    assert "# Сирени" in md
    assert "https://sirens.live/api" in md
    assert "https://sirens.live/issue" in md
    assert "https://status.sirens.live" in md
    assert "```json" in md
    assert "WebApplication" in md
    assert "AI & Data Attribution" in md
    assert "посилання на **Sirens** (https://sirens.live) є обов'язковим" in md


def test_render_issue_markdown():
    md = render_issue_markdown("https://sirens.live")
    assert md.startswith("---\n")
    assert "Повідомити про збій" in md
    assert "Сповіщення" in md
    assert "Мапа тривог" in md
    assert "https://sirens.live/issue" in md
    assert "```json" in md
    assert "ContactPage" in md


def test_render_issue_markdown_success():
    md = render_issue_markdown("https://sirens.live", success=True)
    assert "Повідомлення надіслано" in md
    assert "Дякуємо, повідомлення отримали. Розберемось." in md
    assert "https://sirens.live/" in md


def test_render_error_markdown():
    md = render_error_markdown(404, "Сторінку не знайдено", "https://sirens.live")
    assert "404 — Сторінку не знайдено" in md
    assert "https://sirens.live/" in md
    assert "https://sirens.live/issue" in md


def test_markdown_response(app):
    with app.test_request_context():
        resp = markdown_response("# Hello", status_code=200, headers={"X-Custom": "test"})
        assert resp.status_code == 200
        assert resp.mimetype == "text/markdown"
        assert resp.headers["Content-Type"] == "text/markdown; charset=utf-8"
        assert resp.headers["x-markdown-tokens"] == "2"
        assert resp.headers["Content-Signal"] == "ai-train=yes, search=yes, ai-input=yes"
        assert resp.headers["Vary"] == "Accept"
        assert resp.headers["X-Custom"] == "test"
        assert resp.get_data(as_text=True) == "# Hello"
