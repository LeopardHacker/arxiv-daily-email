import os
import smtplib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import Header
from email.mime.text import MIMEText
from typing import Iterable

import arxiv

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


@dataclass(frozen=True)
class EmailConfig:
    from_email: str
    to_emails: list[str]
    password: str
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465


def _split_emails(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def load_email_config() -> EmailConfig:
    if load_dotenv is not None:
        load_dotenv()

    from_email = (os.getenv("FROM_EMAIL") or "").strip()
    to_email_raw = (os.getenv("TO_EMAIL") or "").strip()
    password = (os.getenv("EMAIL_PASSWORD") or "").strip()

    missing: list[str] = []
    if not from_email:
        missing.append("FROM_EMAIL")
    if not to_email_raw:
        missing.append("TO_EMAIL")
    if not password:
        missing.append("EMAIL_PASSWORD")
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            f"Missing required environment variables: {joined}. "
            "Set them in GitHub Secrets or a local .env file."
        )

    to_emails = _split_emails(to_email_raw)
    if not to_emails:
        raise SystemExit("TO_EMAIL is empty after parsing.")

    return EmailConfig(from_email=from_email, to_emails=to_emails, password=password)


def is_dry_run() -> bool:
    return (os.getenv("DRY_RUN") or "").strip().lower() in {"1", "true", "yes"}


def yesterday_utc() -> date:
    return datetime.utcnow().date() - timedelta(days=1)


def build_query(target_date: date) -> str:
    """
    arXiv API query string.
    - Default: all cs.* papers submitted on target_date (UTC).
    - Override: set ARXIV_QUERY to a full query string.
    """
    custom = (os.getenv("ARXIV_QUERY") or "").strip()
    if custom:
        return custom

    ymd = target_date.strftime("%Y%m%d")
    return f"submittedDate:[{ymd}0000 TO {ymd}2359] AND cat:cs.*"


def fetch_arxiv_papers(query: str) -> list[dict[str, str]]:
    client = arxiv.Client(page_size=200)
    search = arxiv.Search(
        query=query,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: list[dict[str, str]] = []
    for result in client.results(search):
        papers.append(
            {
                "title": (result.title or "").replace("\n", " ").strip(),
                "authors": ", ".join(a.name for a in (result.authors or [])),
                "url": result.entry_id,
                "categories": ", ".join(result.categories or []),
            }
        )
    return papers


def build_email_content(papers: Iterable[dict[str, str]], target_date: date) -> str:
    papers_list = list(papers)
    if not papers_list:
        return f"[arXiv] No matching papers for {target_date} (UTC)."

    lines: list[str] = []
    lines.append(f"[arXiv] Daily digest for {target_date} (UTC)")
    lines.append("")

    for idx, paper in enumerate(papers_list, 1):
        lines.append(f"{idx}. {paper.get('title', '').strip()}")
        authors = paper.get("authors", "").strip()
        if authors:
            lines.append(f"   Authors: {authors}")
        categories = paper.get("categories", "").strip()
        if categories:
            lines.append(f"   Categories: {categories}")
        url = paper.get("url", "").strip()
        if url:
            lines.append(f"   Link: {url}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def send_email(config: EmailConfig, content: str, target_date: date) -> None:
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(f"arXiv Daily - {target_date}", "utf-8").encode()
    msg["From"] = Header("arXiv Daily Bot", "utf-8").encode()
    msg["To"] = ", ".join(config.to_emails)

    with smtplib.SMTP_SSL(config.smtp_server, config.smtp_port) as server:
        server.login(config.from_email, config.password)
        server.sendmail(config.from_email, config.to_emails, msg.as_string())


def main() -> int:
    target = yesterday_utc()
    query = build_query(target)

    papers = fetch_arxiv_papers(query)
    content = build_email_content(papers, target)

    if is_dry_run():
        print(content)
        return 0

    config = load_email_config()
    send_email(config, content, target)
    print(f"Sent digest for {target} to {', '.join(config.to_emails)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
