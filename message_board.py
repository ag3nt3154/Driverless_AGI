"""Run or stop the standalone message board: python message_board.py [serve|stop] [options].

Thin entry point for ``services.message_board``. Defaults come from ``services.message_board``
in .dagi/config.yaml (``url`` gives the port, ``bind`` the listen address); flags override them.
"""
from services.message_board.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
