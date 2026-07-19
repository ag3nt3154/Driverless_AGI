"""Mini spreadsheet engine. Contract: run(input_dir) -> dict."""
import json
import re
from pathlib import Path

TOKEN_RE = re.compile(
    r"\s*(SUM|IF|[A-Z]+[0-9]+|[0-9]+(?:\.[0-9]+)?|==|[+\-*/(),:<>])")
CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")

_MISSING = object()


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


def _expand_sums(node):
    """Return a copy of the AST with SUM range endpoints pre-expanded into a
    tuple of concrete cell names, so range_cells() never runs at eval time."""
    kind = node[0]
    if kind == "num" or kind == "cell":
        return node
    if kind == "bin":
        return ("bin", node[1], _expand_sums(node[2]), _expand_sums(node[3]))
    if kind == "cmp":
        return ("cmp", node[1], _expand_sums(node[2]), _expand_sums(node[3]))
    if kind == "sum":
        return ("sum", node[1], node[2], tuple(range_cells(node[1], node[2])))
    if kind == "if":
        return ("if", _expand_sums(node[1]), _expand_sums(node[2]), _expand_sums(node[3]))
    raise ValueError(kind)


def _extract_deps(node, acc):
    kind = node[0]
    if kind == "num":
        return
    if kind == "cell":
        acc.add(node[1])
        return
    if kind == "bin" or kind == "cmp":
        _extract_deps(node[2], acc)
        _extract_deps(node[3], acc)
        return
    if kind == "sum":
        acc.update(node[3])
        return
    if kind == "if":
        _extract_deps(node[1], acc)
        _extract_deps(node[2], acc)
        _extract_deps(node[3], acc)
        return
    raise ValueError(kind)


_FORMULA_PARSE_CACHE = {}


def _parse_formula(expr_str):
    """Parse (and cache) a formula body (without leading '='). Returns
    (ast, frozenset(dependency cell names))."""
    cached = _FORMULA_PARSE_CACHE.get(expr_str)
    if cached is not None:
        return cached
    ast = _expand_sums(Parser(tokenize(expr_str)).parse())
    deps = set()
    _extract_deps(ast, deps)
    result = (ast, frozenset(deps))
    _FORMULA_PARSE_CACHE[expr_str] = result
    return result


class SheetState:
    __slots__ = ("cells", "ast_cache", "deps", "dependents", "value_cache")

    def __init__(self):
        self.cells = {}
        self.ast_cache = {}
        self.deps = {}
        self.dependents = {}
        self.value_cache = {}


def eval_cell_cached(state, name):
    v = state.value_cache.get(name, _MISSING)
    if v is not _MISSING:
        return v
    raw = state.cells.get(name, "")
    if raw == "":
        v = 0.0
    elif raw[0] != "=":
        v = float(raw)
    else:
        v = eval_ast_cached(state, state.ast_cache[name])
    state.value_cache[name] = v
    return v


def eval_ast_cached(state, node):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "cell":
        return eval_cell_cached(state, node[1])
    if kind == "bin":
        return _apply_bin_op(node[1], eval_ast_cached(state, node[2]),
                              eval_ast_cached(state, node[3]))
    if kind == "cmp":
        return _apply_cmp_op(node[1], eval_ast_cached(state, node[2]),
                              eval_ast_cached(state, node[3]))
    if kind == "sum":
        return sum(eval_cell_cached(state, c) for c in node[3])
    if kind == "if":
        cond = eval_ast_cached(state, node[1])
        branch = node[2] if cond != 0.0 else node[3]
        return eval_ast_cached(state, branch)
    raise ValueError(kind)


def _invalidate(state, name):
    """Clear the memoized value of `name` and every cell that transitively
    depends on it (its dependents), so later reads recompute correctly."""
    value_cache = state.value_cache
    dependents = state.dependents
    stack = [name]
    visited = set()
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        value_cache.pop(node, None)
        nxt = dependents.get(node)
        if nxt:
            stack.extend(nxt)


def _set_cell(state, name, raw_value):
    old_deps = state.deps.get(name)
    if old_deps:
        dependents = state.dependents
        for d in old_deps:
            s = dependents.get(d)
            if s is not None:
                s.discard(name)

    state.cells[name] = raw_value

    if raw_value != "" and raw_value[0] == "=":
        ast, deps = _parse_formula(raw_value[1:])
        state.ast_cache[name] = ast
        state.deps[name] = deps
    else:
        state.ast_cache[name] = None
        deps = None
        state.deps[name] = None

    if deps:
        dependents = state.dependents
        for d in deps:
            s = dependents.get(d)
            if s is None:
                dependents[d] = {name}
            else:
                s.add(name)

    _invalidate(state, name)


def _load_run_inputs(input_dir):
    cells = json.loads(Path(input_dir, "sheet.json").read_text(encoding="utf-8"))
    updates = [json.loads(line) for line in
               Path(input_dir, "updates.jsonl").read_text(
                   encoding="utf-8").splitlines() if line.strip()]
    probes = json.loads(Path(input_dir, "probes.json").read_text(encoding="utf-8"))
    return cells, updates, probes


def run(input_dir):
    cells_raw, updates, probes = _load_run_inputs(input_dir)
    probe_map = {p["after_event"]: p["cells"] for p in probes}

    state = SheetState()
    for name, raw in cells_raw.items():
        _set_cell(state, name, raw)

    out = []
    for i, u in enumerate(updates, start=1):
        _set_cell(state, u["cell"], u["value"])
        if i in probe_map:
            out.append({"after_event": i,
                        "values": {c: eval_cell_cached(state, c)
                                   for c in probe_map[i]}})

    total = sum(eval_cell_cached(state, name) for name in state.cells)
    return {"probes": out, "final_checksum": total}
