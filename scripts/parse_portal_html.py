"""Разбор сохранённой HTML-страницы Products портала UN Comtrade."""
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
html = path.read_text(encoding="utf-8", errors="replace")

print("=== все href:")
for href in sorted({m.group(1) for m in re.finditer(r'href="([^"]{3,120})"', html)}):
    print(" ", href)

print("\n=== фрагменты вокруг ключевых слов:")
seen = set()
for kw in ("product", "comtrade", "public", "subscri", "sign", "APIs",
           "free", "tool"):
    for m in re.finditer(rf"(?i).{{60}}{kw}.{{90}}", html):
        frag = re.sub(r"\s+", " ", m.group(0)).strip()
        if frag not in seen:
            seen.add(frag)
            print(" ", frag[:170])
            if len(seen) > 30:
                break
