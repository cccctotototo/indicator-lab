from __future__ import annotations

import ast
import re
from functools import reduce
from pathlib import Path

import numpy as np
import pandas as pd


_ASSIGNMENT = re.compile(
    r"^\s*(?:(?:var|bool|float|int|string)\s+)*(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<expression>.*)$"
)
_CONTINUATION = re.compile(r"(?:\band\b|\bor\b|[+\-*/?:,])\s*$")


def _strip_comment(line: str) -> str:
    in_string: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {'"', "'"}:
            in_string = None if in_string == char else char if in_string is None else in_string
        if char == "/" and index + 1 < len(line) and line[index + 1] == "/" and in_string is None:
            return line[:index]
    return line


def _parenthesis_balance(text: str) -> int:
    balance = 0
    in_string: str | None = None
    escaped = False
    for char in text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {'"', "'"}:
            in_string = None if in_string == char else char if in_string is None else in_string
            continue
        if in_string is None:
            balance += char == "("
            balance -= char == ")"
    return balance


def _is_wrapped_expression(expression: str) -> bool:
    """Return True when one outer parenthesis pair wraps the whole expression."""
    if not (expression.startswith("(") and expression.endswith(")")):
        return False
    depth = 0
    in_string: str | None = None
    escaped = False
    for index, char in enumerate(expression):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {'"', "'"}:
            in_string = None if in_string == char else char if in_string is None else in_string
            continue
        if in_string is not None:
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index != len(expression) - 1:
                return False
    return depth == 0


def _convert_pine_ternary(expression: str) -> str:
    """Translate Pine's ``condition ? yes : no`` into a Python conditional."""
    text = expression.strip()
    if _is_wrapped_expression(text):
        return f"({_convert_pine_ternary(text[1:-1])})"

    depth = 0
    in_string: str | None = None
    escaped = False
    question_index: int | None = None
    nested_ternaries = 0
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in {'"', "'"}:
            in_string = None if in_string == char else char if in_string is None else in_string
            continue
        if in_string is not None:
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}":
            depth -= 1
            continue
        if depth != 0:
            continue
        if char == "?":
            if question_index is None:
                question_index = index
            else:
                nested_ternaries += 1
        elif char == ":" and question_index is not None:
            if nested_ternaries:
                nested_ternaries -= 1
                continue
            condition = text[:question_index]
            when_true = text[question_index + 1 : index]
            when_false = text[index + 1 :]
            return (
                f"({_convert_pine_ternary(when_true)} if "
                f"{_convert_pine_ternary(condition)} else "
                f"{_convert_pine_ternary(when_false)})"
            )
    return text


def extract_assignments(source: str) -> list[tuple[str, str]]:
    """Extract Pine variable assignments, including indented continuation lines."""
    lines = [_strip_comment(line).rstrip() for line in source.splitlines()]
    assignments: list[tuple[str, str]] = []
    current_name: str | None = None
    current_parts: list[str] = []
    ignored_call_balance = 0

    def finish() -> None:
        nonlocal current_name, current_parts
        if current_name is not None:
            expression = " ".join(part.strip() for part in current_parts if part.strip())
            assignments.append((current_name, expression))
        current_name = None
        current_parts = []

    for raw_line in lines:
        line = raw_line.strip()
        if ignored_call_balance > 0:
            ignored_call_balance += _parenthesis_balance(line)
            continue
        if not line:
            if current_name and _parenthesis_balance(" ".join(current_parts)) <= 0:
                finish()
            continue
        match = _ASSIGNMENT.match(raw_line)
        if current_name is not None:
            combined = " ".join(current_parts)
            continuing = _parenthesis_balance(combined) > 0 or bool(_CONTINUATION.search(combined))
            if continuing:
                current_parts.append(line)
                continue
            finish()
        if match and not line.startswith(("if ", "for ", "while ")):
            current_name = match.group("name")
            current_parts = [match.group("expression")]
            combined = " ".join(current_parts)
            if _parenthesis_balance(combined) <= 0 and not _CONTINUATION.search(combined):
                finish()
        elif re.match(r"^(?:indicator|strategy|plotshape|plot|alertcondition|alert|strategy\.\w+)\s*\(", line):
            ignored_call_balance = max(0, _parenthesis_balance(line))
    finish()
    return assignments


def _infer_mintick(frame: pd.DataFrame) -> float:
    values = pd.concat(
        [pd.to_numeric(frame[column], errors="coerce") for column in ("open", "high", "low", "close")],
        ignore_index=True,
    ).dropna()
    if values.empty:
        return 1e-8
    unique = np.unique(np.round(values.to_numpy(dtype=float), 10))
    differences = np.diff(unique)
    positive = differences[differences > 1e-10]
    return float(positive.min()) if positive.size else 1e-8


def _as_series(value, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.reindex(index)
    return pd.Series(value, index=index)


def _pairwise(values: list, index: pd.Index, operation: str):
    if not any(isinstance(value, pd.Series) for value in values):
        return min(values) if operation == "min" else max(values)
    table = pd.concat([_as_series(value, index) for value in values], axis=1)
    return table.min(axis=1) if operation == "min" else table.max(axis=1)


def _rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    relative_strength = gains / losses.replace(0, np.nan)
    return (100 - 100 / (1 + relative_strength)).fillna(100).where(gains.ne(0), 0)


class _Evaluator:
    def __init__(self, frame: pd.DataFrame, environment: dict[str, object]):
        self.frame = frame
        self.index = frame.index
        self.environment = environment

    def evaluate(self, expression: str):
        expression = _convert_pine_ternary(expression).replace("^", "**")
        try:
            node = ast.parse(expression, mode="eval").body
        except SyntaxError as exc:
            raise ValueError(f"不支援的 Pine 運算式：{expression}") from exc
        return self._node(node)

    def _node(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            aliases = {"true": True, "false": False, "na": np.nan}
            if node.id in aliases:
                return aliases[node.id]
            if node.id in self.environment:
                return self.environment[node.id]
            raise ValueError(f"尚未支援或尚未定義的 Pine 變數：{node.id}")
        if isinstance(node, ast.Attribute):
            dotted = self._dotted_name(node)
            special = {
                "barstate.isconfirmed": True,
                "syminfo.mintick": self.environment["__mintick__"],
            }
            if dotted in special:
                return special[dotted]
            raise ValueError(f"尚未支援的 Pine 屬性：{dotted}")
        if isinstance(node, ast.Subscript):
            value = self._node(node.value)
            period = self._node(node.slice)
            if not isinstance(value, pd.Series) or not isinstance(period, (int, np.integer)):
                raise ValueError("Pine 歷史索引只支援序列與整數，例如 close[1]")
            return value.shift(int(period))
        if isinstance(node, ast.UnaryOp):
            value = self._node(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, (ast.Not, ast.Invert)):
                return ~_as_series(value, self.index) if isinstance(value, pd.Series) else not value
        if isinstance(node, ast.BinOp):
            left, right = self._node(node.left), self._node(node.right)
            operations = {
                ast.Add: lambda a, b: a + b,
                ast.Sub: lambda a, b: a - b,
                ast.Mult: lambda a, b: a * b,
                ast.Div: lambda a, b: a / b,
                ast.Mod: lambda a, b: a % b,
                ast.Pow: lambda a, b: a**b,
                ast.BitAnd: lambda a, b: a & b,
                ast.BitOr: lambda a, b: a | b,
            }
            for kind, operation in operations.items():
                if isinstance(node.op, kind):
                    return operation(left, right)
        if isinstance(node, ast.BoolOp):
            values = [self._node(value) for value in node.values]
            if isinstance(node.op, ast.And):
                return reduce(lambda a, b: _as_series(a, self.index).fillna(False).astype(bool) & _as_series(b, self.index).fillna(False).astype(bool), values)
            return reduce(lambda a, b: _as_series(a, self.index).fillna(False).astype(bool) | _as_series(b, self.index).fillna(False).astype(bool), values)
        if isinstance(node, ast.Compare):
            left = self._node(node.left)
            masks = []
            operations = {
                ast.Eq: lambda a, b: a == b,
                ast.NotEq: lambda a, b: a != b,
                ast.Lt: lambda a, b: a < b,
                ast.LtE: lambda a, b: a <= b,
                ast.Gt: lambda a, b: a > b,
                ast.GtE: lambda a, b: a >= b,
            }
            for operator, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._node(comparator)
                masks.append(next(operation(left, right) for kind, operation in operations.items() if isinstance(operator, kind)))
                left = right
            return reduce(lambda a, b: _as_series(a, self.index) & _as_series(b, self.index), masks)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.IfExp):
            condition = _as_series(self._node(node.test), self.index).fillna(False).astype(bool)
            yes = _as_series(self._node(node.body), self.index)
            no = _as_series(self._node(node.orelse), self.index)
            return yes.where(condition, no)
        raise ValueError(f"尚未支援的 Pine 語法：{type(node).__name__}")

    def _dotted_name(self, node) -> str:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    def _call(self, node: ast.Call):
        name = self._dotted_name(node.func)
        arguments = [self._node(argument) for argument in node.args]
        if name.startswith("input."):
            return arguments[0] if arguments else None
        if name in {"math.abs", "abs"}:
            value = arguments[0]
            return value.abs() if isinstance(value, pd.Series) else abs(value)
        if name in {"math.min", "min", "math.max", "max"}:
            return _pairwise(arguments, self.index, "min" if name.endswith("min") else "max")
        if name in {"nz"}:
            replacement = arguments[1] if len(arguments) > 1 else 0
            return arguments[0].fillna(replacement) if isinstance(arguments[0], pd.Series) else arguments[0]
        if name == "ta.sma":
            return _as_series(arguments[0], self.index).rolling(int(arguments[1]), min_periods=int(arguments[1])).mean()
        if name == "ta.ema":
            return _as_series(arguments[0], self.index).ewm(span=int(arguments[1]), adjust=False, min_periods=int(arguments[1])).mean()
        if name == "ta.rsi":
            return _rsi(_as_series(arguments[0], self.index), int(arguments[1]))
        if name == "ta.stdev":
            ddof = 0 if len(arguments) > 2 and bool(arguments[2]) else 1
            return _as_series(arguments[0], self.index).rolling(int(arguments[1]), min_periods=int(arguments[1])).std(ddof=ddof)
        if name == "ta.highest":
            return _as_series(arguments[0], self.index).rolling(int(arguments[1]), min_periods=int(arguments[1])).max()
        if name == "ta.lowest":
            return _as_series(arguments[0], self.index).rolling(int(arguments[1]), min_periods=int(arguments[1])).min()
        if name in {"ta.crossover", "ta.crossunder"}:
            left, right = (_as_series(value, self.index) for value in arguments[:2])
            return (left.gt(right) & left.shift(1).le(right.shift(1))) if name.endswith("crossover") else (left.lt(right) & left.shift(1).ge(right.shift(1)))
        raise ValueError(f"尚未支援的 Pine 函式：{name}")


def compute_pine_signals(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    """Evaluate the common indicator subset used by imported V1 Pine scripts."""
    if ":=" in source:
        raise ValueError("目前不支援 Pine 的 := 狀態變數；請改用訊號 CSV 匯入。")
    environment: dict[str, object] = {
        column: pd.to_numeric(frame[column], errors="coerce")
        for column in ("open", "high", "low", "close", "volume")
    }
    environment["__mintick__"] = _infer_mintick(frame)
    evaluator = _Evaluator(frame, environment)
    for name, expression in extract_assignments(source):
        environment[name] = evaluator.evaluate(expression)
    missing = [name for name in ("longSignal", "shortSignal") if name not in environment]
    if missing:
        raise ValueError("Pine 必須定義 longSignal 與 shortSignal，才能自動建立多空訊號。")
    long_signal = _as_series(environment["longSignal"], frame.index)
    short_signal = _as_series(environment["shortSignal"], frame.index)
    if "showLong" in environment:
        long_signal &= _as_series(environment["showLong"], frame.index).astype(bool)
    if "showShort" in environment:
        short_signal &= _as_series(environment["showShort"], frame.index).astype(bool)
    return pd.DataFrame(
        {
            "long_signal": long_signal.fillna(False).astype(bool),
            "short_signal": short_signal.fillna(False).astype(bool),
        },
        index=frame.index,
    )


def write_pine_adapter(source: str, target: str | Path) -> Path:
    target = Path(target)
    code = (
        '"""Web-imported Pine V1 adapter. Generated by Indicator Lab."""\n'
        "from __future__ import annotations\n\n"
        "import pandas as pd\n"
        "from quant_labeler.pine_runtime import compute_pine_signals\n\n"
        f"PINE_SOURCE = {source!r}\n\n"
        "def compute_signals(df: pd.DataFrame) -> pd.DataFrame:\n"
        "    return compute_pine_signals(df, PINE_SOURCE)\n"
    )
    target.write_text(code, encoding="utf-8")
    return target
