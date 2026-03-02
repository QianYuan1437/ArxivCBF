import requests
import json
import time
import os
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_API = "http://export.arxiv.org/api/query"


def fetch_high_citation_papers(min_citations=100, max_results=200):
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
                    "abstract": (item.get("abstract") or "")[:300],
                })
        offset += limit
        if offset >= data.get("total", 0):
            break
        time.sleep(1)
    papers.sort(key=lambda x: x.get("date") or str(x.get("year", "")), reverse=True)
    return papers


def fetch_latest_papers(max_results=50):
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
            "abstract": entry.find("atom:summary", ns).text.strip()[:300],
        })
    return papers


def paper_card(p, show_citations=False):
    authors = ", ".join(p["authors"][:5]) + (" et al." if len(p["authors"]) > 5 else "")
    badge = (f'<span class="badge">🔥 {p["citations"]} citations</span>'
             if show_citations else f'<span class="badge date">{p.get("date","")}</span>')
    url = p.get("url", "")
    link = f'<a href="{url}" target="_blank" class="arxiv-link">arXiv →</a>' if url else ""
    abstract = p.get("abstract", "")
    abstract_html = (f'<p class="abstract">{abstract}{"..." if len(abstract)==300 else ""}</p>'
                     if abstract else "")
    return f"""    <div class="card">
      <div class="card-header">{badge}{link}</div>
      <h3>{p["title"]}</h3>
      <p class="authors">{authors}</p>
      {abstract_html}
    </div>"""


def generate_html(high_citation, latest):
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hc_cards = "\n".join(paper_card(p, show_citations=True) for p in high_citation)
    lt_cards = "\n".join(paper_card(p, show_citations=False) for p in latest)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CBF Papers Tracker</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f7fa;color:#333}}
  header{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:2rem;text-align:center}}
  header h1{{font-size:2rem;margin-bottom:.5rem}}
  header p{{opacity:.7;font-size:.9rem}}
  .tabs{{display:flex;justify-content:center;gap:1rem;padding:1.5rem;background:white;border-bottom:1px solid #e0e0e0;position:sticky;top:0;z-index:10}}
  .tab{{padding:.6rem 1.5rem;border-radius:2rem;cursor:pointer;border:2px solid #1a1a2e;background:white;font-weight:600;transition:all .2s}}
  .tab.active,.tab:hover{{background:#1a1a2e;color:white}}
  .section{{display:none;max-width:900px;margin:2rem auto;padding:0 1rem}}
  .section.active{{display:block}}
  .card{{background:white;border-radius:12px;padding:1.2rem 1.5rem;margin-bottom:1rem;box-shadow:0 2px 8px rgba(0,0,0,.06);transition:box-shadow .2s}}
  .card:hover{{box-shadow:0 4px 16px rgba(0,0,0,.12)}}
  .card-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem}}
  .badge{{font-size:.8rem;padding:.2rem .7rem;border-radius:1rem;background:#fff3e0;color:#e65100;font-weight:600}}
  .badge.date{{background:#e8f5e9;color:#2e7d32}}
  .arxiv-link{{font-size:.85rem;color:#1565c0;text-decoration:none;font-weight:600}}
  .arxiv-link:hover{{text-decoration:underline}}
  h3{{font-size:1rem;line-height:1.5;margin-bottom:.4rem}}
  .authors{{font-size:.85rem;color:#666;margin-bottom:.5rem}}
  .abstract{{font-size:.85rem;color:#555;line-height:1.6;border-top:1px solid #f0f0f0;padding-top:.5rem;margin-top:.5rem}}
  footer{{text-align:center;padding:2rem;color:#999;font-size:.85rem}}
</style>
</head>
<body>
<header>
  <h1>📄 CBF Papers Tracker</h1>
  <p>Control Barrier Function papers on arXiv &nbsp;|&nbsp; Updated: {updated}</p>
</header>
<div class="tabs">
  <button class="tab active" onclick="show('high')">📊 High Citation (≥100)</button>
  <button class="tab" onclick="show('latest')">🆕 Latest Papers</button>
</div>
<div id="high" class="section active">{hc_cards}</div>
<div id="latest" class="section">{lt_cards}</div>
<footer>Auto-updated by GitHub Actions · <a href="https://github.com/QianYuan1437/ArxivCBF">Source</a></footer>
<script>
  function show(id){{
    document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    event.target.classList.add('active');
  }}
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("Fetching high-citation papers...")
    high_citation = fetch_high_citation_papers()
    print(f"Found {len(high_citation)} high-citation papers")

    print("Fetching latest papers...")
    latest = fetch_latest_papers()
    print(f"Found {len(latest)} latest papers")

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(generate_html(high_citation, latest))
    with open("docs/papers_data.json", "w", encoding="utf-8") as f:
        json.dump({"high_citation": high_citation, "latest": latest}, f, ensure_ascii=False, indent=2)

    print("Done! docs/index.html updated.")
