import json
import os
import time
from html import escape
from collections import defaultdict
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_API = "http://export.arxiv.org/api/query"
CBF_KEYWORDS = (
    "control barrier function",
    "control barrier functions",
    "cbf",
)

TOPIC_RULES = [
    ("biomedical", "Biomedical", ("blood-brain barrier", "epithelial", "podocyte", "microbiota", "duodenum", "barrier permeability")),
    ("robotics", "Robotics", ("robot", "robotic", "manipulator", "drone", "quadruped", "mobile robot", "bipedal", "surface vehicle", "surface vessel", "autonomous")),
    ("mpc", "MPC/Planning", ("model predictive control", "mpc", "trajectory", "planning", "optimization", "obstacle")),
    ("learning", "Learning", ("neural", "fuzzy", "learning", "reinforcement", "adaptive")),
    ("theory", "Theory", ("lyapunov", "stability", "invariance", "robustness", "certificate", "proof")),
]

ARXIV_SUBJECT_LABELS = {
    "cs.AI": "Artificial Intelligence",
    "cs.RO": "Robotics",
    "cs.LG": "Machine Learning",
    "cs.SY": "Systems and Control",
    "cs.CV": "Computer Vision and Pattern Recognition",
    "eess.SY": "Systems and Control",
    "math.OC": "Optimization and Control",
    "math.DS": "Dynamical Systems",
    "stat.ML": "Machine Learning",
}


def infer_topic(title="", abstract=""):
    text = f"{title} {abstract}".lower()
    for key, label, keywords in TOPIC_RULES:
        if any(word in text for word in keywords):
            return key, label
    return "other", "Other"


def _subject_label(subject_code):
    return ARXIV_SUBJECT_LABELS.get(subject_code, subject_code)


def _normalize_arxiv_id(arxiv_id):
    if not arxiv_id:
        return ""
    return arxiv_id.split("v")[0]


def build_keyword_stats(high_citation, latest, top_n=24):
    merged = []
    seen = set()
    for p in latest + high_citation:
        key = p.get("paper_id") or p.get("arxiv_id") or p.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(p)

    stats = defaultdict(lambda: {"count": 0, "papers": []})
    for p in merged:
        labels = {_subject_label(code) for code in (p.get("subjects", []) or [])}
        for label in labels:
            stats[label]["count"] += 1
            stats[label]["papers"].append(p)

    sorted_stats = sorted(stats.items(), key=lambda x: (-x[1]["count"], x[0]))[:top_n]
    return sorted_stats, len(merged)


def _load_previous_high_citation(path="docs/papers_data.json"):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("high_citation", []) or []
    except Exception:
        return []


def _semantic_scholar_get(params, retries=4, timeout=30):
    for attempt in range(retries):
        try:
            resp = requests.get(SEMANTIC_SCHOLAR_API, params=params, timeout=timeout)
        except requests.RequestException:
            resp = None

        if resp is not None and resp.status_code == 200:
            return resp

        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    return None


def _is_cbf_related(title="", abstract=""):
    text = f"{title} {abstract}".lower()
    return any(keyword in text for keyword in CBF_KEYWORDS)


def _paper_from_semantic_scholar(item):
    arxiv_id = (item.get("externalIds") or {}).get("ArXiv")
    paper_id = item.get("paperId")
    if arxiv_id:
        url = f"https://arxiv.org/abs/{arxiv_id}"
    elif paper_id:
        url = f"https://www.semanticscholar.org/paper/{paper_id}"
    else:
        url = ""

    return {
        "title": item.get("title", ""),
        "authors": [a["name"] for a in item.get("authors", [])],
        "year": item.get("year"),
        "date": item.get("publicationDate", "") or (str(item.get("year")) if item.get("year") else ""),
        "citations": item.get("citationCount", 0),
        "arxiv_id": arxiv_id,
        "paper_id": paper_id,
        "url": url,
        "abstract": item.get("abstract") or "",
        "subjects": [],
    }


def enrich_arxiv_subjects(papers, batch_size=40):
    arxiv_ids = []
    seen = set()
    for p in papers:
        aid = _normalize_arxiv_id(p.get("arxiv_id"))
        if aid and aid not in seen:
            seen.add(aid)
            arxiv_ids.append(aid)

    if not arxiv_ids:
        return

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    subject_map = {}
    for i in range(0, len(arxiv_ids), batch_size):
        chunk = arxiv_ids[i:i + batch_size]
        params = {
            "id_list": ",".join(chunk),
            "max_results": len(chunk),
        }
        try:
            resp = requests.get(ARXIV_API, params=params, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception:
            continue

        for entry in root.findall("atom:entry", ns):
            pid = _normalize_arxiv_id(entry.find("atom:id", ns).text.split("/abs/")[-1])
            primary = entry.find("arxiv:primary_category", ns)
            primary_term = primary.get("term") if primary is not None else ""
            all_terms = [c.get("term") for c in entry.findall("atom:category", ns) if c.get("term")]
            terms = []
            if primary_term:
                terms.append(primary_term)
            terms.extend([t for t in all_terms if t != primary_term])
            subject_map[pid] = terms
        time.sleep(0.2)

    for p in papers:
        aid = _normalize_arxiv_id(p.get("arxiv_id"))
        if aid:
            p["subjects"] = subject_map.get(aid, p.get("subjects", []))


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

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(resp.content)

    papers = []
    for entry in root.findall("atom:entry", ns):
        arxiv_id = entry.find("atom:id", ns).text.split("/abs/")[-1]
        title = entry.find("atom:title", ns).text.strip()
        abstract = entry.find("atom:summary", ns).text.strip()
        if not _is_cbf_related(title, abstract):
            continue
        primary = entry.find("arxiv:primary_category", ns)
        primary_term = primary.get("term") if primary is not None else ""
        all_terms = [c.get("term") for c in entry.findall("atom:category", ns) if c.get("term")]
        subjects = []
        if primary_term:
            subjects.append(primary_term)
        subjects.extend([t for t in all_terms if t != primary_term])
        papers.append(
            {
                "title": title,
                "authors": [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)],
                "date": entry.find("atom:published", ns).text[:10],
                "arxiv_id": arxiv_id,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "abstract": abstract,
                "subjects": subjects,
            }
        )
    return papers


def fetch_high_citation_papers(min_citations=100, max_results=200):
    papers = []
    seen = set()
    limit = 100
    query_candidates = [
        "control barrier function",
        "control barrier function CBF",
        '"control barrier functions"',
    ]

    for query in query_candidates:
        offset = 0
        while len(papers) < max_results:
            params = {
                "query": query,
                "fields": "paperId,title,authors,year,citationCount,externalIds,publicationDate,abstract",
                "limit": limit,
                "offset": offset,
            }
            resp = _semantic_scholar_get(params)
            if not resp:
                break

            data = resp.json()
            items = data.get("data", [])
            if not items:
                break

            for item in items:
                if item.get("citationCount", 0) < min_citations:
                    continue
                if not _is_cbf_related(item.get("title", ""), item.get("abstract", "")):
                    continue

                paper = _paper_from_semantic_scholar(item)
                key = paper.get("paper_id") or paper.get("arxiv_id") or paper.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                papers.append(paper)

                if len(papers) >= max_results:
                    break

            offset += limit
            if offset >= data.get("total", 0):
                break
            time.sleep(1)

        if len(papers) >= max_results:
            break

    papers.sort(key=lambda x: x.get("date") or str(x.get("year", "")), reverse=True)
    return papers


def fetch_author_papers_split(author_name, max_results=20):
    params = {
        "query": author_name,
        "fields": "paperId,title,authors,year,citationCount,externalIds,publicationDate,abstract",
        "limit": 100,
    }
    resp = _semantic_scholar_get(params)
    if not resp:
        return [], []

    cbf_results = []
    other_results = []
    seen = set()

    for item in resp.json().get("data", []):
        names = [a["name"] for a in item.get("authors", [])]
        if author_name not in names:
            continue

        paper = _paper_from_semantic_scholar(item)
        key = paper.get("paper_id") or paper.get("arxiv_id") or paper.get("title")
        if not key or key in seen:
            continue
        seen.add(key)

        if _is_cbf_related(paper.get("title", ""), paper.get("abstract", "")):
            cbf_results.append(paper)
        else:
            other_results.append(paper)

    cbf_results.sort(key=lambda x: x.get("date") or str(x.get("year", "")), reverse=True)
    other_results.sort(key=lambda x: x.get("date") or str(x.get("year", "")), reverse=True)
    return cbf_results[:max_results], other_results[:max_results]


def build_authors(high_citation, latest):
    author_cbf = defaultdict(list)
    seen = set()

    # Build author rank from CBF papers, prioritizing latest arXiv feed.
    for p in latest + high_citation:
        if not _is_cbf_related(p.get("title", ""), p.get("abstract", "")):
            continue
        key = p.get("paper_id") or p.get("arxiv_id") or p.get("title")
        if key in seen:
            continue
        seen.add(key)
        for author in p.get("authors", []):
            author_cbf[author].append(p)

    sorted_authors = sorted(author_cbf.items(), key=lambda x: len(x[1]), reverse=True)[:30]

    result = []
    for i, (name, seed_cbf) in enumerate(sorted_authors):
        cbf_from_author, non_cbf = fetch_author_papers_split(name)

        combined = list(seed_cbf)
        known = {p.get("paper_id") or p.get("arxiv_id") or p.get("title") for p in combined}
        for p in cbf_from_author:
            k = p.get("paper_id") or p.get("arxiv_id") or p.get("title")
            if k not in known:
                combined.append(p)
                known.add(k)

        combined.sort(key=lambda x: x.get("date") or str(x.get("year", "")), reverse=True)
        result.append((name, combined, non_cbf))

        if i < len(sorted_authors) - 1:
            time.sleep(0.5)

    return result


def paper_card(p, show_citations=False, show_date=True):
    authors = ", ".join(p["authors"][:5]) + (" et al." if len(p["authors"]) > 5 else "")
    topic_key, topic_label = infer_topic(p.get("title", ""), p.get("abstract", ""))

    badges = [f'<span class="badge topic">{topic_label}</span>']
    if show_citations and "citations" in p:
        badges.append(f'<span class="badge">{p["citations"]} citations</span>')
    if show_date:
        badges.append(f'<span class="badge date">{p.get("date", "")}</span>')
    badge_html = "".join(badges)

    url = p.get("url", "")
    link_text = "arXiv ->" if "arxiv.org" in url else "Paper ->"
    link = f'<a href="{url}" target="_blank" class="arxiv-link">{link_text}</a>' if url else ""

    abstract = p.get("abstract", "")
    abstract_html = f'<p class="abstract">{abstract}</p>' if abstract else ""

    search_text = " ".join(
        [p.get("title", ""), " ".join(p.get("authors", [])), p.get("abstract", ""), topic_label]
    ).lower()
    search_attr = escape(search_text, quote=True)

    return f"""    <div class="card" data-topic="{topic_key}" data-search="{search_attr}">
      <div class="card-header">{badge_html}{link}</div>
      <h3>{p["title"]}</h3>
      <p class="authors">{authors}</p>
      {abstract_html}
    </div>"""


def generate_html(high_citation, latest, authors):
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hc_cards = "\n".join(paper_card(p, show_citations=True, show_date=True) for p in high_citation)
    lt_cards = "\n".join(paper_card(p, show_citations=False, show_date=True) for p in latest)
    keyword_stats, keyword_total_papers = build_keyword_stats(high_citation, latest)

    author_list_html = "\n".join(
        f'<li class="author-item" onclick="showAuthor({i})">'
        f'<span class="author-name">{name}</span>'
        f'<span class="author-count">{len(cbf_ps)}</span></li>'
        for i, (name, cbf_ps, _) in enumerate(authors)
    )

    author_panels_html = ""
    for i, (name, cbf_ps, other_ps) in enumerate(authors):
        cbf_section = "\n".join(paper_card(p, show_citations=False, show_date=True) for p in cbf_ps)
        other_section = "\n".join(paper_card(p, show_citations=False, show_date=True) for p in other_ps)
        other_block = f'<div class="section-divider">Non-CBF Papers</div>{other_section}' if other_ps else ""
        author_panels_html += (
            f'<div class="author-panel" id="author-panel-{i}">'
            f'<div class="section-divider">CBF Related Papers</div>{cbf_section}{other_block}</div>\n'
        )

    keyword_list_html = "\n".join(
        f'<li class="keyword-item" onclick="showKeyword({i})">'
        f'<span class="keyword-name">{escape(label)}</span>'
        f'<span class="keyword-count">{meta["count"]}</span></li>'
        for i, (label, meta) in enumerate(keyword_stats)
    )

    keyword_panels_html = ""
    for i, (label, meta) in enumerate(keyword_stats):
        coverage = (meta["count"] / keyword_total_papers * 100) if keyword_total_papers else 0.0
        cards = "\n".join(paper_card(p, show_citations=False, show_date=True) for p in meta["papers"])
        keyword_panels_html += (
            f'<div class="keyword-panel" id="keyword-panel-{i}">'
            f'<div class="section-divider">{escape(label)} | {meta["count"]} papers | {coverage:.1f}% coverage</div>'
            f"{cards}</div>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CBF Papers Tracker</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  :root{{--content-width:min(85vw,1500px)}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f7fa;color:#333}}
  header{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:2rem;text-align:center}}
  header h1{{font-size:2rem;margin-bottom:.5rem}}
  header p{{opacity:.8;font-size:.9rem}}
  .tabs{{display:flex;justify-content:center;gap:1rem;padding:1.5rem;background:white;border-bottom:1px solid #e0e0e0;position:sticky;top:0;z-index:10}}
  .tab{{padding:.6rem 1.5rem;border-radius:2rem;cursor:pointer;border:2px solid #1a1a2e;background:white;font-weight:600;transition:all .2s}}
  .tab.active,.tab:hover{{background:#1a1a2e;color:white}}
  .section{{display:none;width:var(--content-width);margin:2rem auto;padding:0}}
  .section.active{{display:block}}
  .card{{background:white;border-radius:12px;padding:1.2rem 1.5rem;margin-bottom:1rem;box-shadow:0 2px 8px rgba(0,0,0,.06);transition:box-shadow .2s}}
  .card:hover{{box-shadow:0 4px 16px rgba(0,0,0,.12)}}
  .card-header{{display:flex;justify-content:space-between;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.5rem}}
  .badge{{font-size:.8rem;padding:.2rem .7rem;border-radius:1rem;background:#fff3e0;color:#e65100;font-weight:600}}
  .badge.topic{{background:#e3f2fd;color:#0d47a1}}
  .badge.date{{background:#e8f5e9;color:#2e7d32}}
  .arxiv-link{{font-size:.85rem;color:#1565c0;text-decoration:none;font-weight:600}}
  .arxiv-link:hover{{text-decoration:underline}}
  h3{{font-size:1rem;line-height:1.5;margin-bottom:.4rem}}
  .authors{{font-size:.85rem;color:#666;margin-bottom:.5rem}}
  .abstract{{font-size:.85rem;color:#555;line-height:1.6;border-top:1px solid #f0f0f0;padding-top:.5rem;margin-top:.5rem}}
  footer{{text-align:center;padding:2rem;color:#999;font-size:.85rem}}
  .author-layout,.keyword-layout{{display:flex;width:100%;margin:0;gap:1.5rem}}
  .author-list,.keyword-list{{width:220px;flex-shrink:0;background:white;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.06);align-self:flex-start;position:sticky;top:80px;max-height:80vh;overflow-y:auto}}
  .author-list,.keyword-list{{scrollbar-width:thin;scrollbar-color:#b7bfce #f1f3f7}}
  .author-list::-webkit-scrollbar,.keyword-list::-webkit-scrollbar{{width:10px}}
  .author-list::-webkit-scrollbar-track,.keyword-list::-webkit-scrollbar-track{{background:#f1f3f7;border-radius:999px}}
  .author-list::-webkit-scrollbar-thumb,.keyword-list::-webkit-scrollbar-thumb{{background:#b7bfce;border-radius:999px;border:2px solid #f1f3f7}}
  .author-list ul,.keyword-list ul{{list-style:none}}
  .author-item{{display:flex;justify-content:space-between;align-items:center;padding:.7rem 1rem;cursor:pointer;border-bottom:1px solid #f0f0f0;transition:background .15s}}
  .author-item:hover,.author-item.active{{background:#e8eaf6}}
  .author-name{{font-size:.85rem;font-weight:500}}
  .author-count{{font-size:.75rem;background:#1a1a2e;color:white;border-radius:1rem;padding:.1rem .5rem;flex-shrink:0}}
  .author-panels{{flex:1;min-width:0}}
  .author-panel{{display:none}}
  .author-panel.active{{display:block}}
  .keyword-item{{display:flex;justify-content:space-between;align-items:center;padding:.7rem 1rem;cursor:pointer;border-bottom:1px solid #f0f0f0;transition:background .15s}}
  .keyword-item:hover,.keyword-item.active{{background:#e8eaf6}}
  .keyword-name{{font-size:.85rem;font-weight:500}}
  .keyword-count{{font-size:.75rem;background:#1a1a2e;color:white;border-radius:1rem;padding:.1rem .5rem;flex-shrink:0}}
  .keyword-panels{{flex:1;min-width:0}}
  .keyword-panel{{display:none}}
  .keyword-panel.active{{display:block}}
  .section-divider{{font-size:.8rem;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.05em;padding:.5rem 0;margin-bottom:.5rem;border-bottom:2px solid #e0e0e0}}
  .controls{{width:var(--content-width);margin:1.2rem auto 0;padding:0;display:flex;flex-direction:column;gap:.8rem}}
  .search-input{{width:100%;padding:.75rem .95rem;border:1px solid #ccd4df;border-radius:10px;font-size:.95rem;outline:none;background:white}}
  .search-input:focus{{border-color:#1a1a2e;box-shadow:0 0 0 3px rgba(26,26,46,.1)}}
  .topics{{display:flex;flex-wrap:wrap;gap:.5rem}}
  .topic-chip{{padding:.35rem .8rem;border:1px solid #c8d0df;background:white;color:#263044;border-radius:999px;cursor:pointer;font-size:.82rem;font-weight:600}}
  .topic-chip.active,.topic-chip:hover{{background:#1a1a2e;color:white;border-color:#1a1a2e}}
  .filter-empty{{display:none;width:var(--content-width);margin:1rem auto 0;padding:0;color:#666;font-size:.9rem}}
  @media (max-width: 860px) {{
    .author-layout,.keyword-layout{{flex-direction:column}}
    .author-list,.keyword-list{{position:static;width:100%;max-height:none}}
    .section,.controls,.filter-empty{{width:92vw}}
  }}
</style>
</head>
<body>
<header>
  <h1>CBF Papers Tracker</h1>
  <p>Control Barrier Function papers | Updated: {updated}</p>
</header>
<div class="tabs">
  <button class="tab active" onclick="show('high',this)">High Citation (>=100)</button>
  <button class="tab" onclick="show('latest',this)">Latest Papers</button>
  <button class="tab" onclick="show('authors',this)">Top Authors</button>
  <button class="tab" onclick="show('keywords',this)">Key Words</button>
</div>
<div class="controls">
  <input id="searchInput" class="search-input" type="text" placeholder="Search title / authors / abstract" oninput="applyFilters()" />
  <div class="topics" id="topicChips">
    <button class="topic-chip active" type="button" onclick="setTopic('all',this)">All</button>
    <button class="topic-chip" type="button" onclick="setTopic('theory',this)">Theory</button>
    <button class="topic-chip" type="button" onclick="setTopic('robotics',this)">Robotics</button>
    <button class="topic-chip" type="button" onclick="setTopic('mpc',this)">MPC/Planning</button>
    <button class="topic-chip" type="button" onclick="setTopic('learning',this)">Learning</button>
    <button class="topic-chip" type="button" onclick="setTopic('biomedical',this)">Biomedical</button>
    <button class="topic-chip" type="button" onclick="setTopic('other',this)">Other</button>
  </div>
</div>
<p id="filterEmpty" class="filter-empty">No papers match current filters.</p>
<div id="high" class="section active">{hc_cards}</div>
<div id="latest" class="section">{lt_cards}</div>
<div id="authors" class="section">
  <div class="author-layout">
    <div class="author-list"><ul>{author_list_html}</ul></div>
    <div class="author-panels">{author_panels_html}</div>
  </div>
</div>
<div id="keywords" class="section">
  <div class="keyword-layout">
    <div class="keyword-list"><ul>{keyword_list_html}</ul></div>
    <div class="keyword-panels">{keyword_panels_html}</div>
  </div>
</div>
<footer>Auto-updated by GitHub Actions | <a href="https://github.com/QianYuan1437/ArxivCBF">Source</a></footer>
<script>
  let activeTopic = 'all';

  function applyFilters(){{
    const q = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
    const current = document.querySelector('.section.active');
    if (!current) return;

    const cards = current.querySelectorAll('.card');
    const empty = document.getElementById('filterEmpty');
    if (!cards.length) {{
      if (empty) empty.style.display = 'none';
      return;
    }}
    let visible = 0;
    cards.forEach(card => {{
      const text = (card.dataset.search || '').toLowerCase();
      const topic = card.dataset.topic || 'other';
      const okQuery = !q || text.includes(q);
      const okTopic = activeTopic === 'all' || topic === activeTopic;
      const show = okQuery && okTopic;
      card.style.display = show ? '' : 'none';
      if (show) visible += 1;
    }});

    if (empty) empty.style.display = visible ? 'none' : 'block';
  }}

  function setTopic(topic, btn){{
    activeTopic = topic;
    document.querySelectorAll('.topic-chip').forEach(chip => chip.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  }}

  function show(id,btn){{
    document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    btn.classList.add('active');
    applyFilters();
  }}
  function showAuthor(i){{
    document.querySelectorAll('.author-panel').forEach(p=>p.classList.remove('active'));
    document.querySelectorAll('.author-item').forEach(a=>a.classList.remove('active'));
    document.getElementById('author-panel-'+i).classList.add('active');
    document.querySelectorAll('.author-item')[i].classList.add('active');
    applyFilters();
  }}
  function showKeyword(i){{
    document.querySelectorAll('.keyword-panel').forEach(p=>p.classList.remove('active'));
    document.querySelectorAll('.keyword-item').forEach(a=>a.classList.remove('active'));
    document.getElementById('keyword-panel-'+i).classList.add('active');
    document.querySelectorAll('.keyword-item')[i].classList.add('active');
    applyFilters();
  }}
  if(document.querySelector('.author-item')) showAuthor(0);
  if(document.querySelector('.keyword-item')) showKeyword(0);
  applyFilters();
</script>
</body>
</html>"""


if __name__ == "__main__":
    prev_high_citation = _load_previous_high_citation()

    print("Fetching latest CBF papers from arXiv...")
    latest = fetch_latest_papers()
    print(f"Found {len(latest)} latest papers")

    print("Fetching high-citation CBF papers...")
    high_citation = fetch_high_citation_papers()
    if not high_citation and prev_high_citation:
        print("Warning: high-citation fetch returned empty; reusing previous high-citation data.")
        high_citation = prev_high_citation
    print(f"Found {len(high_citation)} high-citation papers")

    print("Enriching arXiv subject categories...")
    enrich_arxiv_subjects(latest)
    enrich_arxiv_subjects(high_citation)

    print("Building author data...")
    authors = build_authors(high_citation, latest)
    print(f"Built {len(authors)} authors")

    os.makedirs("docs", exist_ok=True)
    open("docs/.nojekyll", "w").close()
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(generate_html(high_citation, latest, authors))
    with open("docs/papers_data.json", "w", encoding="utf-8") as f:
        json.dump({
            "high_citation": high_citation,
            "latest": latest,
            "authors": [(n, c, o) for n, c, o in authors],
        }, f, ensure_ascii=False, indent=2)

    print("Done! docs/index.html updated.")
