"""Docmancer TUI theme: a calm, professional dark palette.

The palette is built on Catppuccin Mocha, a warm low-glare dark base with
muted pastel accents. It intentionally avoids pure-ANSI brights (raw cyan,
magenta, green) so long browsing sessions stay easy on the eyes while status
colors remain legible.
"""
from __future__ import annotations

from textual.theme import Theme

# --- Base surfaces (darkest to lightest) ---
CRUST = "#11111b"
MANTLE = "#181825"
BASE = "#1e1e2e"
SURFACE0 = "#313244"
SURFACE1 = "#45475a"
SURFACE2 = "#585b70"

# --- Text ---
TEXT = "#cdd6f4"
SUBTEXT = "#a6adc8"
OVERLAY = "#7f849c"

# --- Accents (muted pastels) ---
BLUE = "#89b4fa"
LAVENDER = "#b4befe"
MAUVE = "#cba6f7"
SKY = "#89dceb"
TEAL = "#94e2d5"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
PEACH = "#fab387"
RED = "#f38ba8"
MAROON = "#eba0ac"

THEME_NAME = "docmancer-dark"

DOCMANCER_DARK = Theme(
    name=THEME_NAME,
    primary=BLUE,
    secondary=TEAL,
    accent=LAVENDER,
    warning=YELLOW,
    error=RED,
    success=GREEN,
    foreground=TEXT,
    background=MANTLE,
    surface=BASE,
    panel=SURFACE0,
    dark=True,
    variables={
        "text-muted": SUBTEXT,
        "text-disabled": OVERLAY,
        "border": SURFACE1,
        "border-blurred": SURFACE0,
        # Keep the selected row a quiet raised surface rather than a bright fill.
        "block-cursor-background": SURFACE1,
        "block-cursor-foreground": TEXT,
        "block-cursor-text-style": "bold",
        "block-cursor-blurred-background": SURFACE0,
        "block-cursor-blurred-foreground": TEXT,
        "block-hover-background": SURFACE0,
        # Restrained scrollbars.
        "scrollbar": SURFACE0,
        "scrollbar-hover": SURFACE1,
        "scrollbar-active": SURFACE2,
        "scrollbar-background": MANTLE,
        "input-cursor-background": LAVENDER,
        "input-selection-background": f"{BLUE} 35%",
    },
)

# --- Iconography ---------------------------------------------------------
# Kept to widely supported Unicode so it renders in any modern terminal
# (no private-use / Nerd Font glyphs).
GLYPH = {
    "bullet": "·",
    "sep": "•",
    "match": "»",
    "on": "●",
    "off": "○",
    "check": "✓",
    "cross": "✕",
    "warn": "!",
    "swap": "↔",
    "chevron": "›",
    "arrow": "→",
    "gutter": "│",
}

# --- Semantic Rich styles for result cards -------------------------------
# Muted pastels keep the list scannable without the glare of raw terminal colors.
STYLE_TITLE = f"bold {TEXT}"
STYLE_MUTED = f"{SUBTEXT}"
STYLE_FAINT = f"{OVERLAY}"
STYLE_HARNESS = f"{TEAL}"
STYLE_SCOPE = f"{MAUVE}"
STYLE_MATCH = f"bold {GREEN}"
STYLE_ACCENT = f"{SKY}"
STYLE_PENDING = f"bold {PEACH}"
STYLE_ACTIVE = f"{GREEN}"
STYLE_WARNING = f"{YELLOW}"
STYLE_DANGER = f"bold {RED}"
STYLE_CHANGED = f"bold {SKY}"
STYLE_HISTORY = f"bold {MAUVE}"
STYLE_ON = f"bold {GREEN}"
STYLE_OFF = f"bold {PEACH}"

SEVERITY_STYLES = {
    "CRITICAL": f"bold {RED}",
    "HIGH": f"{RED}",
    "MEDIUM": f"{YELLOW}",
    "LOW": f"{SKY}",
}

# --- Badge chips ---------------------------------------------------------
# A badge is a short label painted on a raised surface, the TUI equivalent of
# a pill/tag. `badge_style` pairs a foreground accent with a surface fill so
# the chip reads as one solid token rather than loose colored words.
_BADGE_BG = SURFACE0
_BADGE_BG_STRONG = SURFACE1


def badge_style(fg: str, *, strong: bool = False) -> str:
    """Return a Rich style string for a filled chip in the given accent."""
    return f"bold {fg} on {_BADGE_BG_STRONG if strong else _BADGE_BG}"


def badge_text(label: str) -> str:
    """Pad a label so the surface fill reads as a chip with breathing room."""
    return f" {label} "


BADGE_HARNESS = badge_style(TEAL)
BADGE_SCOPE = badge_style(MAUVE)
BADGE_TYPE = badge_style(LAVENDER)
BADGE_MATCH = badge_style(GREEN, strong=True)
BADGE_PENDING = badge_style(PEACH, strong=True)
BADGE_DANGER = badge_style(RED, strong=True)
BADGE_WARNING = badge_style(YELLOW)
BADGE_INFO = badge_style(SKY)
BADGE_MUTED = f"{SUBTEXT} on {_BADGE_BG}"

SEVERITY_BADGES = {
    "CRITICAL": badge_style(RED, strong=True),
    "HIGH": badge_style(RED),
    "MEDIUM": badge_style(YELLOW),
    "LOW": badge_style(SKY),
}
