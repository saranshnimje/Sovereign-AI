"""
calculator tool — safe mathematical expression evaluator (LOW risk).
Uses ast.literal_eval approach restricted to numeric operations.
The LLM cannot inject arbitrary code through this tool.
"""
from __future__ import annotations
import ast
import math
import operator
from pydantic import BaseModel, field_validator


# Whitelist of safe operators
_SAFE_OPS: dict = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Whitelist of safe math functions
_SAFE_FUNCS: dict = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil,
    "log": math.log, "log10": math.log10, "exp": math.exp,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "pi": math.pi, "e": math.e,
}


def _safe_eval(node: ast.AST) -> float | int:
    """Recursively evaluate an AST node using only whitelisted operations."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")
    elif isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    elif isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary operator")
        return op(_safe_eval(node.operand))
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        fn = _SAFE_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"Unknown function: {node.func.id}")
        args = [_safe_eval(a) for a in node.args]
        return fn(*args)
    elif isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCS:
            val = _SAFE_FUNCS[node.id]
            if isinstance(val, (int, float)):
                return val
        raise ValueError(f"Unknown name: {node.id}")
    else:
        raise ValueError(f"Unsupported AST node: {type(node).__name__}")


class CalculatorInput(BaseModel):
    expression: str

    @field_validator("expression")
    @classmethod
    def validate_expr(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Expression cannot be empty")
        if len(v) > 500:
            raise ValueError("Expression too long")
        # Reject any import / exec / eval keywords
        forbidden = ["import", "exec", "eval", "__", "open", "os", "sys"]
        low = v.lower()
        for kw in forbidden:
            if kw in low:
                raise ValueError(f"Forbidden keyword: {kw}")
        return v


class CalculatorOutput(BaseModel):
    result: float
    expression: str


async def execute(inp: CalculatorInput, context: dict) -> dict:
    try:
        tree = ast.parse(inp.expression, mode="eval")
        result = _safe_eval(tree.body)
        return CalculatorOutput(
            result=float(result), expression=inp.expression
        ).model_dump()
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"Calculation error: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc
