from __future__ import annotations

from pyside_gui.theme import qss

MENU_STYLESHEET = qss("""
        QMenuBar {
            background: @app_bg; color: @fg_secondary;
            border-bottom: 1px solid @border;
            font-family: @font_ui;
            font-size: 13px;
            padding: 2px 0px;
        }
        QMenuBar::item {
            padding: 4px 12px;
            border-radius: 6px;
            margin: 2px 2px;
        }
        QMenuBar::item:selected { background: @hover_bg; color: @fg; }
        QMenu {
            background: @menu_bg; color: @fg;
            border: 1px solid @border;
            border-radius: 10px;
            padding: 5px;
            font-family: @font_ui;
            font-size: 13px;
        }
        QMenu::item {
            padding: 6px 24px 6px 12px;
            border-radius: 6px;
        }
        QMenu::item:selected { background: @active_bg; }
        QMenu::separator { height: 1px; background: @border; margin: 4px 6px; }
        QMenu::indicator { width: 14px; height: 14px; margin-left: 4px; }
    """)
