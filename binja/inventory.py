"""Text filters and shared page output for view inventories."""
import re

from .analysis import page_rows
from .common import Error


def text_filter(substring, regex=None):
    if regex is not None:
        try:
            expression = re.compile(regex)
        except re.error as exc:
            raise Error(f"Invalid regular expression {regex!r}: {exc}") from None
        return expression.search
    needle = substring.casefold() if substring is not None else ""
    return lambda text: needle in text.casefold()


def inventory_page(request, items, offset, limit, **details):
    rows, page = page_rows(items, offset, limit)
    result = dict(target=request["target_snapshot"]["handle"], **details, rows=rows, page=page)
    print(f"{result['target']}  {request['kind']}")
    for key in ("match", "regex", "sort"):
        if result.get(key) is not None:
            print(f"{key}: {result[key]!r}")
    if "total_available" in result:
        print(f"{page['total']} of {result['total_available']} {request['kind']} match")
    return result
