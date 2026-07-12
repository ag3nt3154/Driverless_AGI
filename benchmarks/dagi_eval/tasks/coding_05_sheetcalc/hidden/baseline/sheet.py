"""Mini spreadsheet engine. Contract: run(input_dir) -> dict."""
import json
import re
from pathlib import Path

TOKEN_RE = re.compile(
    r"\s*(SUM|IF|[A-Z]+[0-9]+|[0-9]+(?:\.[0-9]+)?|==|[+\-*/(),:<>])")
CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


def tokenize(s):
    tokens = []
    pos = 0
    while pos < len(s):
        m = TOKEN_RE.match(s, pos)
        if m is None:
            raise ValueError(f"bad formula {s!r} at {pos}")
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


class Parser:
    """expr := sum_ (('>'|'<'|'==') sum_)? ; sum_ := term (('+'|'-') term)* ;
    term := factor (('*'|'/') factor)* ;
    factor := NUMBER | CELL | '(' expr ')' | SUM '(' CELL ':' CELL ')'
            | IF '(' expr ',' expr ',' expr ')'
    AST nodes: ("num", v) ("cell", name) ("bin", op, l, r)
               ("cmp", op, l, r) ("sum", c1, c2) ("if", cond, yes, no)"""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected=None):
        tok = self.tokens[self.pos]
        if expected is not None and tok != expected:
            raise ValueError(f"expected {expected}, got {tok}")
        self.pos += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise ValueError("trailing tokens")
        return node

    def expr(self):
        left = self.sum_()
        if self.peek() in (">", "<", "=="):
            return ("cmp", self.take(), left, self.sum_())
        return left

    def sum_(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek() in ("*", "/"):
            op = self.take()
            node = ("bin", op, node, self.factor())
        return node

    def factor(self):
        tok = self.peek()
        if tok == "(":
            self.take()
            node = self.expr()
            self.take(")")
            return node
        if tok == "SUM":
            return self._factor_sum()
        if tok == "IF":
            return self._factor_if()
        self.take()
        if CELL_RE.match(tok):
            return ("cell", tok)
        return ("num", float(tok))

    def _factor_sum(self):
        self.take()
        self.take("(")
        a = self.take()
        self.take(":")
        b = self.take()
        self.take(")")
        return ("sum", a, b)

    def _factor_if(self):
        self.take()
        self.take("(")
        cond = self.expr()
        self.take(",")
        yes = self.expr()
        self.take(",")
        no = self.expr()
        self.take(")")
        return ("if", cond, yes, no)


def _col_num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_letters(n):
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def range_cells(a, b):
    ma, mb = CELL_RE.match(a), CELL_RE.match(b)
    c1, r1 = _col_num(ma.group(1)), int(ma.group(2))
    c2, r2 = _col_num(mb.group(1)), int(mb.group(2))
    return [_col_letters(c) + str(r)
            for c in range(min(c1, c2), max(c1, c2) + 1)
            for r in range(min(r1, r2), max(r1, r2) + 1)]


def _apply_bin_op(op, a, b):
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    return a / b


def _apply_cmp_op(op, a, b):
    if op == ">":
        ok = a > b
    elif op == "<":
        ok = a < b
    else:
        ok = a == b
    return 1.0 if ok else 0.0


def eval_cell(cells, name):
    raw = cells.get(name, "")
    if raw == "":
        return 0.0
    if not raw.startswith("="):
        return float(raw)
    ast = Parser(tokenize(raw[1:])).parse()   # re-parsed on EVERY evaluation
    return eval_ast(cells, ast)


def _eval_if(cells, node):
    cond = eval_ast(cells, node[1])
    return eval_ast(cells, node[2]) if cond != 0.0 else eval_ast(cells, node[3])


def eval_ast(cells, node):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "cell":
        return eval_cell(cells, node[1])       # recursive, uncached
    if kind == "bin":
        return _apply_bin_op(node[1], eval_ast(cells, node[2]), eval_ast(cells, node[3]))
    if kind == "cmp":
        return _apply_cmp_op(node[1], eval_ast(cells, node[2]), eval_ast(cells, node[3]))
    if kind == "sum":
        return sum(eval_cell(cells, c) for c in range_cells(node[1], node[2]))
    if kind == "if":
        return _eval_if(cells, node)
    raise ValueError(kind)


def snapshot(cells):
    return {name: eval_cell(cells, name) for name in cells}


def _load_run_inputs(input_dir):
    cells = json.loads(Path(input_dir, "sheet.json").read_text(encoding="utf-8"))
    updates = [json.loads(line) for line in
               Path(input_dir, "updates.jsonl").read_text(
                   encoding="utf-8").splitlines() if line.strip()]
    probes = json.loads(Path(input_dir, "probes.json").read_text(encoding="utf-8"))
    return cells, updates, probes


def run(input_dir):
    cells, updates, probes = _load_run_inputs(input_dir)
    probe_map = {p["after_event"]: p["cells"] for p in probes}

    out = []
    for i, u in enumerate(updates, start=1):
        cells[u["cell"]] = u["value"]
        values = snapshot(cells)                # FULL recompute after every update
        if i in probe_map:
            out.append({"after_event": i,
                        "values": {c: values.get(c, 0.0)
                                   for c in probe_map[i]}})
    values = snapshot(cells)
    return {"probes": out, "final_checksum": sum(values.values())}
