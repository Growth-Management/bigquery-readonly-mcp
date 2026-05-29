import re

FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "CREATE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "EXPORT",
    "LOAD",
    "GRANT",
    "REVOKE",
    "CALL",
}


class SqlValidationError(ValueError):
    pass


def _mask_literals_identifiers_and_comments(sql: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ""

        if char == "-" and next_char == "-":
            j = sql.find("\n", i + 2)
            i = len(sql) if j == -1 else j
            result.append(" ")
            continue

        if char == "/" and next_char == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                raise SqlValidationError("Unclosed block comment")
            i = j + 2
            result.append(" ")
            continue

        if char in {"'", '"', "`"}:
            quote = char
            i += 1
            while i < len(sql):
                if sql[i] == "\\":
                    i += 2
                    continue
                if sql[i] == quote:
                    if quote in {"'", '"'} and i + 1 < len(sql) and sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            else:
                raise SqlValidationError("Unclosed quoted value or identifier")
            result.append(" ")
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _split_statements(sql: str) -> list[str]:
    masked = _mask_literals_identifiers_and_comments(sql)
    parts: list[str] = []
    start = 0
    for index, char in enumerate(masked):
        if char == ";":
            parts.append(sql[start:index].strip())
            start = index + 1
    tail = sql[start:].strip()
    if tail:
        parts.append(tail)
    return [part for part in parts if part]


def validate_readonly_sql(sql: str) -> None:
    normalized = sql.strip()
    if not normalized:
        raise SqlValidationError("SQL is empty")

    statements = _split_statements(normalized)
    if len(statements) != 1:
        raise SqlValidationError("Only one SQL statement is allowed")

    masked = _mask_literals_identifiers_and_comments(statements[0])
    first_keyword = re.search(r"\b([A-Za-z_]+)\b", masked)
    if not first_keyword or first_keyword.group(1).upper() not in {"SELECT", "WITH"}:
        raise SqlValidationError("Only SELECT or WITH queries are allowed")

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", masked, flags=re.IGNORECASE):
            raise SqlValidationError(f"Forbidden SQL keyword: {keyword}")
