import requests
import json
import time
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_API = "http://export.arxiv.org/api/query"

def fetch_high_citation_papers(min_citations=100, max_results=200):
    """从 Semantic Scholar 获取引用量>=100 的 CBF 论文"""
    papers = []
    offset = 0
    limit = 100
    
    while len(papers) < max_results:
        params = {
            "query": "Control Barrier Function CBF",
            "fields": "title,authors,year,citationCount,externalIds,publicationDate,abstract",
            "limit": limit,
            "offset": offset,
        }
        resp = requests.get(SEMANTIC_SCHOLAR_API, params=params, timeout=30)
        if resp.status_code != 200:
            break
        data = resp.json()
        items = data.get("data", [])
        if not items:
            break
        for item in items:
            if item.get("citationCount", 0) >= min_citations:
                arxiv_id = (item.get("externalIds") or {}).get("ArXiv")
                papers.append({
                    "title": item.get("title", ""),
                    "authors": [a["name"] for a in item.get("authors", [])],
                    "year": item.get("year"),
                    "date": item.get("publicationDate", ""),
                    "citations": item.get("citationCount", 0),
                    "arxiv_id": arxiv_id,
                    "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                    "abstract": item.get("abstract", ""),
                })
        offset += limit
        if offset >= data.get("total", 0):
            break
        time.sleep(1)
    
    # 按时间从新到旧排序
    papers.sort(key=lambda x: x.get("date") or str(x.get("year", "")), reverse=True)
    return papers


def fetch_latest_papers(max_results=50):
    """从 arXiv 获取最新 CBF 论文"""
    params = {
        "search_query": 'all:"control barrier function"',
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = requests.get(ARXIV_API, params=params, timeout=30)
    resp.raise_for_status()
    
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.content)
    papers = []
    for entry in root.findall("atom:entry", ns):
        arxiv_id = entry.find("atom:id", ns).text.split("/abs/")[-1]
        papers.append({
            "title": entry.find("atom:title", ns).text.strip(),
            "authors": [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)],
            "date": entry.find("atom:published", ns).text[:10],
            "arxiv_id": arxiv_id,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
            "abstract": entry.find("atom:summary", ns).text.strip(),
        })
    return papers


def generate_readme(high_citation, latest):
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    lines = [
        "# CBF (Control Barrier Function) Papers on arXiv",
        "",
        f"> 自动更新时间: {updated}",
        "",
        "---",
        "",
        "## 📊 高引用论文（引用量 ≥ 100，按时间从新到旧）",
        "",
        "| 年份 | 标题 | 作者 | 引用量 | 链接 |",
        "|------|------|------|--------|------|",
    ]
    for p in high_citation:
        authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
        title = p["title"].replace("|", "\\|")
        year = p.get("date", "")[:4] or str(p.get("year", ""))
        url = p.get("url", "")
        link = f"[arXiv]({url})" if url else "N/A"
        lines.append(f"| {year} | {title} | {authors} | {p['citations']} | {link} |")
    
    lines += [
        "",
        "---",
        "",
        "## 🆕 最新发表论文",
        "",
        "| 日期 | 标题 | 作者 | 链接 |",
        "|------|------|------|------|",
    ]
    for p in latest:
        authors = ", ".join(p["authors"][:3]) + (" et al." if len(p["authors"]) > 3 else "")
        title = p["title"].replace("|", "\\|")
        lines.append(f"| {p['date']} | {title} | {authors} | [arXiv]({p['url']}) |")
    
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print("Fetching high-citation papers...")
    high_citation = fetch_high_citation_papers()
    print(f"Found {len(high_citation)} high-citation papers")
    
    print("Fetching latest papers...")
    latest = fetch_latest_papers()
    print(f"Found {len(latest)} latest papers")
    
    readme = generate_readme(high_citation, latest)
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)
    
    with open("papers_data.json", "w", encoding="utf-8") as f:
        json.dump({"high_citation": high_citation, "latest": latest}, f, ensure_ascii=False, indent=2)
    
    print("Done! README.md updated.")
