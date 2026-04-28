from __future__ import annotations

from rich import box
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme


THEME = Theme(
    {
        "ui.text": "#e2e8f0",
        "ui.dim": "#94a3b8",
        "ui.cyan": "bold #67e8f9",
        "ui.blue": "bold #38bdf8",
        "ui.purple": "bold #c084fc",
        "ui.green": "bold #34d399",
        "ui.yellow": "bold #fbbf24",
        "ui.red": "bold #fb7185",
        "ui.border": "#22d3ee",
        "ui.header": "bold #7dd3fc",
        "ui.title": "bold #e2e8f0",
        "ui.row": "#dbeafe",
        "ui.row_alt": "#cbd5e1",
        "ui.info": "bold #67e8f9",
        "ui.success": "bold #34d399",
        "ui.warning": "bold #fbbf24",
        "ui.error": "bold #fb7185",
    }
)

console = Console(theme=THEME, highlight=False)

_BANNER_COLORS = ("#67e8f9", "#38bdf8", "#818cf8", "#c084fc", "#f472b6")
_TONE_STYLES = {
    "info": "bold #67e8f9",
    "success": "bold #34d399",
    "warning": "bold #fbbf24",
    "error": "bold #fb7185",
}
_TITLE_STYLE = "bold #e2e8f0"
_HEADER_STYLE = "bold #7dd3fc"
_BORDER_STYLE = "#22d3ee"
_ROW_STYLES = ("#dbeafe", "#cbd5e1")
_PANEL_BACKGROUND = "on #06101d"


def brand_text(label: str = "DEVAGENT") -> Text:
    text = Text(justify="center", no_wrap=True)
    for index, character in enumerate(label):
        style = f"bold {_BANNER_COLORS[index % len(_BANNER_COLORS)]}"
        text.append(character, style=style)
    return text


def hero_panel(title: str, subtitle: str) -> Panel:
    heading = Text(title.upper(), justify="center", style="bold #67e8f9")
    detail = Text(subtitle, justify="center", style="#94a3b8")
    body = Group(brand_text(), Text(""), heading, detail)
    return Panel(
        body,
        box=box.DOUBLE,
        border_style=_BORDER_STYLE,
        padding=(1, 2),
        style="on #050816",
    )


def app_panel(
    body: RenderableType,
    title: str,
    *,
    tone: str = "info",
    expand: bool = True,
    padding: tuple[int, int] = (1, 2),
) -> Panel:
    tone_style = _TONE_STYLES.get(tone, _TONE_STYLES["info"])
    title_text = Text(title.upper(), style=tone_style)
    return Panel(
        body,
        title=title_text,
        title_align="left",
        box=box.ROUNDED,
        border_style=tone_style,
        padding=padding,
        style=_PANEL_BACKGROUND,
        expand=expand,
    )


def app_table(title: str) -> Table:
    return Table(
        title=Text(title, style=_TITLE_STYLE),
        title_style=_TITLE_STYLE,
        header_style=_HEADER_STYLE,
        border_style=_BORDER_STYLE,
        box=box.SIMPLE_HEAVY,
        row_styles=_ROW_STYLES,
        expand=True,
        show_lines=False,
    )


def status_badge(label: str, tone: str) -> Text:
    tone_style = _TONE_STYLES.get(tone, _TONE_STYLES["info"])
    return Text(f" {label.upper()} ", style=f"{tone_style} on #08111d")


def styled_path(value: str) -> Text:
    return Text(value, style="bold #38bdf8")


def toned_message(value: str, tone: str) -> Text:
    tone_style = _TONE_STYLES.get(tone, _TONE_STYLES["info"])
    return Text(value, style=tone_style)
