"""平台指标表达式求值（只支持四则运算与少量函数，避免 eval 任意执行）。

支持的变量：基础聚合量（orders / intake / shipment / ...）、其他指标编码（PLT-xx）、
税率等常量；支持的函数：``abs`` / ``round`` / ``min`` / ``max`` / ``if``。

表达式示例::

    PLT-11 = cancelled_amount + refund
    PLT-12 = shipment + PLT-11
    PLT-13 = PLT-12 * settlement_rate
    PLT-37 = abs(PLT-11) / if(PLT-12 > 0, PLT-12, PLT-09)
    PLT-38 = PLT-08 / if(PLT-04 - PLT-06 > 0, PLT-04 - PLT-06, 1)
"""

from __future__ import annotations

import ast
import re
from typing import Any

MAX_EXPRESSION_LENGTH = 1000

# 指标编码形如 PLT-08，Python 会解析成减法（且 08 是非法八进制），这里统一换成下划线形式
_CODE_PATTERN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]+)-(\d+)(?![0-9])")


def normalize_code(text: str) -> str:
    """``PLT-08`` → ``PLT_08``；用于变量名与表达式。"""
    return _CODE_PATTERN.sub(r"\1_\2", text)


class ExpressionError(ValueError):
    """表达式非法或求值失败。"""


def _eval_node(node: ast.AST, variables: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, variables)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError("只允许数字常量")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ExpressionError(f"未知变量：{node.id}")
        return float(variables[node.id] or 0)
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand, variables)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ExpressionError("不支持的一元运算")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right if right else 0.0
        if isinstance(node.op, ast.Pow):
            raise ExpressionError("不支持幂运算")
        raise ExpressionError("不支持的二元运算")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, variables)
        right = _eval_node(node.comparators[0], variables)
        op = node.ops[0]
        if isinstance(op, ast.Gt):
            return 1.0 if left > right else 0.0
        if isinstance(op, ast.GtE):
            return 1.0 if left >= right else 0.0
        if isinstance(op, ast.Lt):
            return 1.0 if left < right else 0.0
        if isinstance(op, ast.LtE):
            return 1.0 if left <= right else 0.0
        if isinstance(op, ast.Eq):
            return 1.0 if left == right else 0.0
        raise ExpressionError("不支持的比较运算")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("不支持的函数调用")
        name = node.func.id
        args = [_eval_node(arg, variables) for arg in node.args]
        if name == "abs" and len(args) == 1:
            return abs(args[0])
        if name == "round" and len(args) in {1, 2}:
            return round(args[0], int(args[1]) if len(args) == 2 else 2)
        if name == "min" and args:
            return min(args)
        if name == "max" and args:
            return max(args)
        if name in {"choose", "iif"} and len(args) == 3:
            return args[1] if args[0] else args[2]
        raise ExpressionError(f"不支持的函数：{name}")
    raise ExpressionError(f"不支持的语法：{type(node).__name__}")


def evaluate(expression: str, variables: dict[str, Any]) -> float:
    """计算表达式；除零返回 0，非法表达式抛 :class:`ExpressionError`。"""
    text = normalize_code((expression or "").strip())
    if not text:
        raise ExpressionError("表达式为空")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"表达式过长（>{MAX_EXPRESSION_LENGTH}）")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"表达式语法错误：{exc.msg}") from exc
    safe_vars = {normalize_code(str(key)): value for key, value in variables.items()}
    try:
        return float(_eval_node(tree, safe_vars))
    except ZeroDivisionError:
        return 0.0
