import httpx
import re

url = 'https://docs.google.com/spreadsheets/d/1b8uvgk4q7jJPjGvFM2TQs3vMES1o9MiAfbEJ7P1TW9w/edit'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
r = httpx.get(url, headers=headers, follow_redirects=True)

# Test the pattern: \"[GID]\",[{"1":[[0,0,\"[TITLE]\"]
pattern = r'\\"(?P<gid>\d{8,12})\\",\[\{\\"1\\":\[\[0,0,\\"(?P<title>[^"]+)\\"'
matches = re.findall(pattern, r.text)
print("Option D matches:", matches)

# Also test another common format:
# [0,0,"1193311657"
pattern2 = r'\[\d+,\d+,\\"(?P<gid>\d{8,12})\\"'
matches2 = re.findall(pattern2, r.text)
print("Option E matches:", list(set(matches2)))
