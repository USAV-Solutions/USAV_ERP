#!/usr/bin/env python3
"""
Confluence Markdown & Mermaid Documentation Sync Tool
Location: Docs/sync_to_confluence.py
Branch Target: development/documentation

Converts Markdown documentation files (with standard IEEE metadata headers and Mermaid diagrams)
into Confluence Storage Format XHTML and syncs them to Confluence space via REST API.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple


def load_env_file(env_path: str) -> None:
    """Load simple .env file if present."""
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def parse_metadata_header(md_text: str) -> Tuple[Dict[str, str], str]:
    """
    Parses Document ID, Version, Status, Date, Prepared by, etc. from initial Markdown table.
    Returns (metadata_dict, remaining_md_text).
    """
    metadata = {}
    table_match = re.search(r"\|\s*Field\s*\|\s*Detail\s*\|[\s\S]*?\n\n", md_text, re.IGNORECASE)
    if table_match:
        table_text = table_match.group(0)
        lines = table_text.strip().split("\n")
        for line in lines[2:]:
            if "|" in line:
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 2:
                    key = re.sub(r"[*_]", "", parts[0]).strip()
                    val = parts[1].strip()
                    metadata[key] = val
        # Remove metadata table from body
        md_text = md_text.replace(table_text, "", 1)
    return metadata, md_text


def format_status_badge(status_text: str) -> str:
    """Convert status string to Confluence colored lozenge macro."""
    status_upper = status_text.upper()
    color = "Grey"
    if "APPROVED" in status_upper or "READY" in status_upper:
        color = "Green"
    elif "DRAFT" in status_upper or "PENDING" in status_upper or "REVISION" in status_upper:
        color = "Yellow"
    elif "IN PROGRESS" in status_upper or "REVIEW" in status_upper:
        color = "Blue"

    return f"""<ac:structured-macro ac:name="status">
  <ac:parameter ac:name="title">{status_text}</ac:parameter>
  <ac:parameter ac:name="colour">{color}</ac:parameter>
</ac:structured-macro>"""


def build_page_properties_macro(metadata: Dict[str, str]) -> str:
    """Build Confluence Page Properties macro (<ac:structured-macro ac:name="details">)."""
    if not metadata:
        return ""

    rows_html = []
    for key, val in metadata.items():
        if key.lower() == "status":
            val_html = format_status_badge(val)
        else:
            val_html = val

        rows_html.append(f"<tr><th>{key}</th><td>{val_html}</td></tr>")

    table_rows = "".join(rows_html)
    return f"""<ac:structured-macro ac:name="details">
  <ac:rich-text-body>
    <table>
      <tbody>
        {table_rows}
      </tbody>
    </table>
  </ac:rich-text-body>
</ac:structured-macro><hr />"""


def convert_mermaid_blocks(md_text: str) -> str:
    """Convert ```mermaid blocks into Confluence Mermaid macros."""
    def _replace_mermaid(match):
        code = match.group(1).strip()
        escaped_code = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"""<ac:structured-macro ac:name="mermaid">
  <ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>
</ac:structured-macro>"""

    return re.sub(r"```mermaid\s*\n([\s\S]*?)\n```", _replace_mermaid, md_text)


def markdown_to_xhtml(md_text: str) -> Tuple[str, Dict[str, str]]:
    """Simple Markdown to Confluence Storage Format XHTML converter."""
    metadata, body = parse_metadata_header(md_text)

    # 1. Process Page Properties Macro from Metadata
    header_xhtml = build_page_properties_macro(metadata)

    # 2. Convert Mermaid blocks
    body = convert_mermaid_blocks(body)

    # 3. Simple Markdown elements to XHTML
    lines = body.split("\n")
    xhtml_lines = []
    in_table = False
    table_lines = []

    def flush_table(t_lines):
        if not t_lines:
            return ""
        out = ["<table><tbody>"]
        for idx, line in enumerate(t_lines):
            if idx == 1 and "---" in line:
                continue  # skip separator line
            cols = [c.strip() for c in line.split("|")[1:-1]]
            tag = "th" if idx == 0 else "td"
            cells = "".join([f"<{tag}>{c}</{tag}>" for c in cols])
            out.append(f"<tr>{cells}</tr>")
        out.append("</tbody></table>")
        return "".join(out)

    for line in lines:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            in_table = True
            table_lines.append(line.strip())
            continue
        elif in_table:
            in_table = False
            xhtml_lines.append(flush_table(table_lines))
            table_lines = []

        # Headings
        if line.startswith("# "):
            xhtml_lines.append(f"<h1>{line[2:].strip()}</h1>")
        elif line.startswith("## "):
            xhtml_lines.append(f"<h2>{line[3:].strip()}</h2>")
        elif line.startswith("### "):
            xhtml_lines.append(f"<h3>{line[4:].strip()}</h3>")
        elif line.startswith("#### "):
            xhtml_lines.append(f"<h4>{line[5:].strip()}</h4>")
        elif line.strip() == "---":
            xhtml_lines.append("<hr />")
        elif line.startswith("<ac:structured-macro"):
            xhtml_lines.append(line)
        elif line.strip():
            # Paragraph or list item
            if line.strip().startswith("* ") or line.strip().startswith("- "):
                xhtml_lines.append(f"<ul><li>{line.strip()[2:]}</li></ul>")
            else:
                xhtml_lines.append(f"<p>{line}</p>")

    if in_table:
        xhtml_lines.append(flush_table(table_lines))

    full_xhtml = header_xhtml + "\n".join(xhtml_lines)
    return full_xhtml, metadata


class ConfluenceClient:
    """Client for Confluence Cloud / Server REST API."""
    def __init__(self, url: str, username: str, api_token: str, space_key: str):
        self.url = url.rstrip("/")
        self.username = username
        self.api_token = api_token
        self.space_key = space_key
        auth_str = f"{username}:{api_token}"
        self.auth_header = "Basic " + base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

    def _request(self, method: str, endpoint: str, payload: Optional[dict] = None) -> dict:
        req_url = f"{self.url}/rest/api/content{endpoint}"
        headers = {
            "Authorization": self.auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        data = json.dumps(payload).encode("utf-8") if payload else None
        req = urllib.request.Request(req_url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req) as resp:
                res_body = resp.read().decode("utf-8")
                return json.loads(res_body) if res_body else {}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            print(f"[ERROR] API Request failed ({e.code}): {err_msg}", file=sys.stderr)
            raise

    def get_page_by_title(self, title: str) -> Optional[dict]:
        endpoint = f"?title={urllib.parse.quote(title)}&spaceKey={self.space_key}&expand=version"
        res = self._request("GET", endpoint)
        results = res.get("results", [])
        return results[0] if results else None

    def upsert_page(self, title: str, xhtml_content: str, parent_id: Optional[str] = None) -> dict:
        existing = self.get_page_by_title(title)
        if existing:
            page_id = existing["id"]
            current_version = existing["version"]["number"]
            payload = {
                "id": page_id,
                "type": "page",
                "title": title,
                "space": {"key": self.space_key},
                "body": {
                    "storage": {
                        "value": xhtml_content,
                        "representation": "storage"
                    }
                },
                "version": {"number": current_version + 1}
            }
            print(f"[INFO] Updating existing page '{title}' (ID: {page_id}, Ver: {current_version + 1})...")
            return self._request("PUT", f"/{page_id}", payload)
        else:
            payload = {
                "type": "page",
                "title": title,
                "space": {"key": self.space_key},
                "body": {
                    "storage": {
                        "value": xhtml_content,
                        "representation": "storage"
                    }
                }
            }
            if parent_id:
                payload["ancestors"] = [{"id": parent_id}]
            print(f"[INFO] Creating new page '{title}' in space '{self.space_key}'...")
            return self._request("POST", "", payload)


def main():
    parser = argparse.ArgumentParser(description="Sync Docs/*.md to Confluence")
    parser.add_argument("--file", help="Specific markdown file to sync (default: all in Docs/)")
    parser.add_argument("--dry-run", action="store_true", help="Perform XHTML conversion without calling API")
    args = parser.parse_args()

    # Load environment variables
    docs_dir = os.path.dirname(os.path.abspath(__file__))
    load_env_file(os.path.join(docs_dir, ".env"))

    confluence_url = os.getenv("CONFLUENCE_URL")
    confluence_user = os.getenv("CONFLUENCE_USERNAME")
    confluence_token = os.getenv("CONFLUENCE_API_TOKEN")
    confluence_space = os.getenv("CONFLUENCE_SPACE_KEY")
    confluence_parent = os.getenv("CONFLUENCE_PARENT_PAGE_ID")

    files_to_sync = []
    if args.file:
        files_to_sync.append(args.file)
    else:
        for fname in os.listdir(docs_dir):
            if fname.endswith(".md") and fname != "README.md":
                files_to_sync.append(os.path.join(docs_dir, fname))

    print(f"=== Confluence Documentation Sync Tool ===")
    print(f"Target Branch: development/documentation")
    print(f"Found {len(files_to_sync)} file(s) to process.")

    for fpath in files_to_sync:
        print(f"\nProcessing file: {fpath}")
        with open(fpath, "r", encoding="utf-8") as f:
            md_content = f.read()

        # Extract title from first H1 line or filename
        title_match = re.search(r"^#\s+(.*)$", md_content, re.MULTILINE)
        page_title = title_match.group(1).strip() if title_match else os.path.basename(fpath).replace(".md", "")

        xhtml_content, metadata = markdown_to_xhtml(md_content)

        print(f"Page Title: {page_title}")
        print(f"Extracted Metadata: {metadata}")

        if args.dry_run:
            print(f"\n--- DRY RUN OUTPUT FOR: {page_title} ---")
            print(xhtml_content[:800] + "\n... [truncated] ...")
            print("--- END DRY RUN ---\n")
            continue

        if not all([confluence_url, confluence_user, confluence_token, confluence_space]):
            print("[WARNING] Confluence credentials missing in environment variables. Skipping live API call.", file=sys.stderr)
            print("Please set CONFLUENCE_URL, CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN, CONFLUENCE_SPACE_KEY in Docs/.env", file=sys.stderr)
            sys.exit(1)

        client = ConfluenceClient(confluence_url, confluence_user, confluence_token, confluence_space)
        res = client.upsert_page(page_title, xhtml_content, confluence_parent)
        print(f"[SUCCESS] Page synced successfully! Confluence ID: {res.get('id')}")


if __name__ == "__main__":
    main()
