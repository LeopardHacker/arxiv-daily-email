# arxiv-daily-email

Send a daily arXiv digest email via GitHub Actions (default: yesterday''s `cs.*` submissions, UTC).

## Run locally

```bash
pip install -r requirements.txt
python arxiv_daily.py
```

Required environment variables:

- `FROM_EMAIL`: sender email (e.g. your QQ Mail address)
- `EMAIL_PASSWORD`: SMTP/app password
- `TO_EMAIL`: recipient email(s), comma-separated

Optional:

- `FROM_NAME`: display name used in the `From:` header
- `DRY_RUN=1`: print email content instead of sending
- `ARXIV_PAGE_SIZE`: arXiv API page size (1..2000)
- `MAX_EMAIL_CHARS`: split into multiple emails when content is large

## GitHub Actions

Set repository secrets:

- `FROM_EMAIL`
- `EMAIL_PASSWORD`
- `TO_EMAIL`
