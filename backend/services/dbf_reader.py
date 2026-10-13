"""Small, dependency-free reader for the character based DBF exports used by QMT."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import struct
from typing import Any


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    length: int
    decimals: int


def _decode(raw: bytes) -> str:
    for encoding in ("gb18030", "utf-8", "latin1"):
        try:
            return raw.decode(encoding).rstrip("\x00 ")
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="replace").rstrip("\x00 ")


def _value(field: Field, raw: bytes) -> Any:
    text = _decode(raw).strip()
    if not text:
        return None
    if field.kind in {"N", "F", "B", "O"}:
        try:
            return int(text) if field.decimals == 0 and "." not in text else float(text)
        except ValueError:
            return text
    if field.kind == "D" and len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
        except ValueError:
            return text
    if field.kind == "L":
        return text[:1].upper() in {"Y", "T"}
    return text


def read_dbf_bytes(data: bytes) -> list[dict[str, Any]]:
    if len(data) < 33:
        raise ValueError("DBF 文件头不完整")
    record_count = struct.unpack_from("<I", data, 4)[0]
    header_length = struct.unpack_from("<H", data, 8)[0]
    record_length = struct.unpack_from("<H", data, 10)[0]
    if header_length < 33 or record_length < 1 or header_length > len(data):
        raise ValueError("DBF 文件头无效")

    fields: list[Field] = []
    cursor = 32
    while cursor + 32 <= header_length and data[cursor] != 0x0D:
        descriptor = data[cursor:cursor + 32]
        name = _decode(descriptor[:11])
        kind = chr(descriptor[11])
        length = int(descriptor[16])
        decimals = int(descriptor[17])
        if not name or length <= 0:
            raise ValueError("DBF 字段定义无效")
        fields.append(Field(name, kind, length, decimals))
        cursor += 32
    if not fields or sum(field.length for field in fields) + 1 != record_length:
        raise ValueError("DBF 记录长度与字段定义不一致")

    expected = header_length + record_count * record_length
    if len(data) < expected:
        raise ValueError("DBF 文件记录不完整，可能仍在写入")
    rows: list[dict[str, Any]] = []
    for index in range(record_count):
        start = header_length + index * record_length
        record = data[start:start + record_length]
        if record[:1] == b"*":
            continue
        offset = 1
        row: dict[str, Any] = {}
        for field in fields:
            row[field.name] = _value(field, record[offset:offset + field.length])
            offset += field.length
        rows.append(row)
    return rows
