import arxiv
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.header import Header
import os

# ====================== 配置区 ======================
FROM_EMAIL = os.getenv("FROM_EMAIL")
TO_EMAIL = os.getenv("TO_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
# SMTP服务器（QQ邮箱固定）
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
# ====================================================

def get_yesterday_arxiv_papers():
    """获取昨天arXiv所有计算机领域新文章"""
    # 计算UTC昨天
    today_utc = datetime.utcnow().date()
    yesterday_utc = today_utc - timedelta(days=1)
    start_str = yesterday_utc.strftime("%Y%m%d")
    end_str = yesterday_utc.strftime("%Y%m%d")

    # 查询：昨天提交 + 计算机领域
    query = f"submittedDate:[{start_str} TO {end_str}] AND cat:cs.*"

    client = arxiv.Client(page_size=200)
    search = arxiv.Search(
        query=query,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending
    )

    papers = []
    for result in client.results(search):
        papers.append({
            "title": result.title,
            "authors": ", ".join(a.name for a in result.authors),
            "url": result.entry_id,
            "categories": ", ".join(result.categories)
        })
    return papers, yesterday_utc

def build_email_content(papers, date):
    """构建邮件正文"""
    if not papers:
        return f"📅 {date} arXiv 暂无新计算机领域文章"
    
    content = f"📅 【{date}】arXiv 昨日新计算机领域论文汇总\n\n"
    for idx, p in enumerate(papers, 1):
        content += f"{idx}. 📄 {p['title']}\n"
        content += f"   👤 作者: {p['authors']}\n"
        content += f"   🏷️ 分类: {p['categories']}\n"
        content += f"   🔗 链接: {p['url']}\n\n"
    return content

def send_email(content, date):
    """发送邮件到指定邮箱"""
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(f"arXiv 每日新文推送 - {date}", "utf-8").encode()
    msg["From"] = Header("arXiv自动推送", "utf-8").encode()
    msg["To"] = TO_EMAIL

    # QQ邮箱SSL发送
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(FROM_EMAIL, EMAIL_PASSWORD)
        server.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())

if __name__ == "__main__":
    papers, date = get_yesterday_arxiv_papers()
    email_text = build_email_content(papers, date)
    send_email(email_text, date)
    print("✅ 邮件发送成功！")