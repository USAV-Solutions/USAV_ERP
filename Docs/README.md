# USAV ERP — Documentation & Confluence Sync Guide

This directory contains official technical documentation and automation tools for syncing system architecture and requirements to Confluence.

> [!IMPORTANT]
> **Branch Rule (`development/documentation`)**:
> - This branch is dedicated strictly to documentation.
> - Do not modify application source code outside of `Docs/` on this branch.
> - All documentation sync scripts live strictly inside `Docs/`.

---

## Environment Setup

Create a `.env` file in `Docs/.env` (or pass environment variables):

```env
CONFLUENCE_URL=https://your-domain.atlassian.net/wiki
CONFLUENCE_USERNAME=your.email@usavsolutions.com
CONFLUENCE_API_TOKEN=your_atlassian_api_token
CONFLUENCE_SPACE_KEY=ERP
CONFLUENCE_PARENT_PAGE_ID=123456789
```

---

## How to Run the Confluence Sync Tool

### 1. Test / Preview (Dry Run)
Verify Markdown-to-XHTML conversion, Confluence Page Properties macro parsing, and Mermaid macro formatting without calling the live API:

```bash
python Docs/sync_to_confluence.py --dry-run
```

To dry-run a specific file:

```bash
python Docs/sync_to_confluence.py --file Docs/ERP_System_Architecture_Diagram.md --dry-run
```

### 2. Live Sync to Confluence
Publish or update all documentation pages in your Confluence space:

```bash
python Docs/sync_to_confluence.py
```

---

## Documentation Formatting Standard

All new markdown documents created in `Docs/` must start with the standard IEEE Document Control table:

```markdown
# [Document Title]

| Field | Detail |
|---|---|
| **Document ID** | USAV-SRS-001 |
| **Version** | 2.0.0 |
| **Status** | Draft – Pending Review |
| **Date** | 2026-07-28 |
| **Prepared by** | USAV Solutions IT / Development Team |
| **Reviewed by** | @usav.hongquang |
| **Approved by** | @usav.hongquang |

---

### Revision History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0.0 | 2026-07-21 | IT Team | Initial draft |
| 2.0.0 | 2026-07-28 | IT Team | Full rewrite with 3-column Mermaid architecture |

---
```

When synced, `Docs/sync_to_confluence.py` converts this header into native Confluence **Page Properties** (`<ac:structured-macro ac:name="details">`) and colored **Status Badges** (`<ac:structured-macro ac:name="status">`).
