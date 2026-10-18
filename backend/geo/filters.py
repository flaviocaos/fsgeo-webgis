"""Filtros de atributos estruturados → SQL parametrizado.

O usuário nunca envia SQL: envia condições {campo, operador, valor}. Campos são
traduzidos para colunas físicas e valores sempre vão como parâmetros.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from psycopg import sql

OPS = {"=", "!=", ">", ">=", "<", "<=", "contem", "comeca", "nulo", "nao_nulo", "em"}
_CMP = {"=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<="}


class FilterError(ValueError):
    pass


def coerce(value: Any, ftype: str) -> Any:
    if value is None:
        return None
    try:
        if ftype == "integer":
            if isinstance(value, bool):
                raise ValueError
            f = float(value)
            if not f.is_integer():
                raise ValueError
            return int(f)
        if ftype == "real":
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if ftype == "boolean":
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ("true", "1", "sim", "s", "verdadeiro"):
                return True
            if s in ("false", "0", "nao", "não", "n", "falso"):
                return False
            raise ValueError
        if ftype == "date":
            return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])
        if ftype == "datetime":
            d = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        return str(value)
    except (ValueError, TypeError):
        raise FilterError(f"Valor '{value}' incompatível com o tipo {ftype}.")


def build_where(conditions: list[dict], match: str, fields: dict[str, dict]) -> tuple[sql.Composable, list]:
    if not conditions:
        return sql.SQL("TRUE"), []
    parts: list[sql.Composable] = []
    params: list[Any] = []
    for c in conditions:
        name, op, value = c.get("campo"), c.get("operador"), c.get("valor")
        if name == "fid":
            f = {"column_name": "fid", "type": "integer"}
        elif name in fields:
            f = fields[name]
        else:
            raise FilterError(f"Campo '{name}' não existe.")
        if op not in OPS:
            raise FilterError(f"Operador '{op}' inválido.")
        col = sql.Identifier(f["column_name"])
        if op == "nulo":
            parts.append(sql.SQL("{} IS NULL").format(col))
        elif op == "nao_nulo":
            parts.append(sql.SQL("{} IS NOT NULL").format(col))
        elif op in ("contem", "comeca"):
            text = str(value or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parts.append(sql.SQL("{}::text ILIKE %s").format(col))
            params.append(f"%{text}%" if op == "contem" else f"{text}%")
        elif op == "em":
            if not isinstance(value, list) or not value:
                raise FilterError("O operador 'em' exige uma lista de valores.")
            parts.append(sql.SQL("{} = ANY(%s)").format(col))
            params.append([coerce(v, f["type"]) for v in value])
        else:
            parts.append(sql.SQL("{} {} %s").format(col, sql.SQL(_CMP[op])))
            params.append(coerce(value, f["type"]))
    joiner = sql.SQL(" OR ") if match == "qualquer" else sql.SQL(" AND ")
    return sql.SQL("(") + joiner.join(parts) + sql.SQL(")"), params
