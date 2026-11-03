"""Colours and the application stylesheet (dark only)."""

from PySide6.QtGui import QColor, QPalette

ACCENT = "#5b8def"
ACCENT_DIM = "#3f6fd0"
TEXT = "#e6e9ef"
TEXT_DIM = "#8b93a1"
TEXT_FAINT = "#5f6773"
LINK = "#7fb0ff"
SIDEBAR = "#1a1e26"
CHAT_BG = "#11141a"
HEADER = "#1a1e26"
LINE = "#262b35"
HOVER = "#222732"
SELECTED = "#2e4a78"
BUBBLE_IN = "#20262f"
BUBBLE_OUT = "#2c4870"
BADGE_MUTED = "#4a515d"
ONLINE = "#4fc76a"
DANGER = "#e5534b"

STYLESHEET = f"""
QWidget {{
    color: {TEXT};
}}
QMainWindow, #Sidebar, #FolderBar {{
    background: {SIDEBAR};
}}
#ChatPane, #MessageCanvas, #EmptyState {{
    background: {CHAT_BG};
}}
#ChatHeader, #Composer {{
    background: {HEADER};
    border: none;
}}
#ChatHeader {{ border-bottom: 1px solid {LINE}; }}
#Composer {{ border-top: 1px solid {LINE}; }}
#Sidebar {{ border-right: 1px solid {LINE}; }}
QSplitter::handle {{ background: {LINE}; }}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background: #232833;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 6px 10px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT_DIM}; }}
#ComposerInput {{ background: transparent; border: none; padding: 6px 4px; }}

QPushButton {{
    background: {ACCENT};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ background: #6d9bf3; }}
QPushButton:disabled {{ background: #3a4150; color: {TEXT_DIM}; }}
QPushButton#Flat, QToolButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: none;
    border-radius: 8px;
    padding: 6px;
    font-weight: normal;
}}
QPushButton#Flat:hover, QToolButton:hover {{ background: {HOVER}; color: {TEXT}; }}
QToolButton#JumpDown {{
    background: #2a303c;
    border-radius: 20px;
    color: {TEXT};
    font-size: 14pt;
}}
QToolButton#JumpDown:hover {{ background: #343b49; }}

QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 8px 12px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom-color: {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar QToolButton {{ background: {SIDEBAR}; }}

QListView {{
    background: {SIDEBAR};
    border: none;
    outline: none;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #3a414e;
    border-radius: 3px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #4a5262; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0; background: none;
}}

QMenu {{
    background: #232833;
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {HOVER}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}

QToolTip {{ background: #232833; color: {TEXT}; border: 1px solid {LINE}; padding: 4px; }}

#Muted {{ color: {TEXT_DIM}; }}
#Title {{ font-size: 12pt; font-weight: 600; }}
#BigTitle {{ font-size: 18pt; font-weight: 600; }}
#ErrorText {{ color: {DANGER}; }}
#Toast {{
    background: rgba(35, 40, 51, 235);
    border: 1px solid {LINE};
    border-radius: 10px;
    padding: 8px 14px;
}}
#ReplyBar {{ background: {HEADER}; border-top: 1px solid {LINE}; }}
#ReplyAccent {{ background: {ACCENT}; border-radius: 1px; }}
#ConnBanner {{ background: #3a3020; color: #f0c674; padding: 4px; }}
"""


def apply(app) -> None:
    app.setStyle("Fusion")
    # Font size goes on the application, not the stylesheet: widgets measure text before they are polished.
    font = app.font()
    font.setPointSizeF(10.5)
    app.setFont(font)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(SIDEBAR))
    pal.setColor(QPalette.Base, QColor("#232833"))
    pal.setColor(QPalette.AlternateBase, QColor(HOVER))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor("#232833"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT_DIM))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.Link, QColor(LINK))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_FAINT))
    pal.setColor(QPalette.ToolTipBase, QColor("#232833"))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
