from __future__ import annotations

MENU_STYLESHEET = """
        QMenuBar {
            background: #313244; color: #cdd6f4;
            border-bottom: 1px solid #45475a;
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 13px;
            padding: 2px 0px;
        }
        QMenuBar::item {
            padding: 4px 12px;
            border-radius: 4px;
            margin: 2px 2px;
        }
        QMenuBar::item:selected { background: #45475a; }
        QMenu {
            background: #313244; color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 6px;
            padding: 4px;
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 13px;
        }
        QMenu::item {
            padding: 6px 24px 6px 12px;
            border-radius: 4px;
        }
        QMenu::item:selected { background: #45475a; }
    """
