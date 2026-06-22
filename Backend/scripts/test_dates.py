import re
from dateutil import parser
from datetime import date, datetime

DATE_PATTERN = re.compile(
    r'\b(?:'
    r'\d{4}-\d{1,2}-\d{1,2}|'
    r'\d{1,2}/\d{1,2}(?:/\d{2,4})?|'
    r'\d{1,2}[,\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[,\s]+\d{4}|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[,\s]+\d{1,2}[,\s]+\d{2,4}|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[,\s]+\d{1,2}'
    r')\b',
    re.IGNORECASE
)

def extract_dates_from_text(text: str, order_date: date) -> list[date]:
    if not text:
        return []
    matches = DATE_PATTERN.findall(text)
    print(f"Matches for {text!r}: {matches}")
    extracted = []
    for m in matches:
        try:
            d = parser.parse(m, default=datetime(order_date.year, order_date.month, order_date.day))
            extracted.append(d.date())
        except Exception as e:
            print(f"Failed to parse {m}: {e}")
    return extracted

texts = [
    "KAI 3/17 1:57",
    "KAI 3/31 12:05",
    "cuong, 4/8/26, 15;00"
]
order_date = date(2026, 3, 25)

for t in texts:
    possible = extract_dates_from_text(t, order_date)
    print(f"Parsed: {possible}")
    valid = [d for d in possible if d >= order_date]
    print(f"Valid (>= {order_date}): {valid}")

