import re
from collections import Counter, defaultdict


TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
STOP_WORDS = {
    "the", "and", "for", "with", "from", "into", "this", "that", "void", "const",
    "class", "struct", "public", "private", "protected", "include", "return", "true",
    "false", "nullptr", "auto", "static", "virtual", "override", "using", "namespace",
}


def build_search_index(files):
    postings = defaultdict(set)
    file_term_counts = {}
    symbol_index = defaultdict(set)

    for index, file_record in enumerate(files):
        tokens = tokenize_for_index(file_record.get("content", ""))
        name_tokens = tokenize_for_index(file_record.get("name", ""))
        combined = tokens + name_tokens * 2
        counts = Counter(combined)
        file_term_counts[index] = counts

        for term in counts:
            postings[term].add(index)

        analysis = file_record.get("analysis", {})
        for symbol in analysis.get("all_symbol_names", []):
            symbol_index[symbol.lower()].add(index)

    return {
        "postings": {term: sorted(ids) for term, ids in postings.items()},
        "file_term_counts": file_term_counts,
        "symbol_index": {term: sorted(ids) for term, ids in symbol_index.items()},
    }


def tokenize_for_index(text):
    return [
        token.lower()
        for token in TOKEN_PATTERN.findall(text)
        if len(token) > 1 and token.lower() not in STOP_WORDS
    ]


def search_indexed_files(files, index_data, query, max_results=8):
    query = query.strip()
    if not query:
        return []

    terms = tokenize_for_index(query)
    if not terms:
        terms = [query.lower()]

    candidate_scores = Counter()
    postings = index_data.get("postings", {})
    term_counts = index_data.get("file_term_counts", {})
    symbol_index = index_data.get("symbol_index", {})

    for term in terms:
        for file_id in postings.get(term, []):
            candidate_scores[file_id] += 3 + term_counts.get(file_id, {}).get(term, 0)

        for symbol, file_ids in symbol_index.items():
            if term in symbol:
                for file_id in file_ids:
                    candidate_scores[file_id] += 6

    query_lower = query.lower()
    for file_id, file_record in enumerate(files):
        if query_lower in file_record.get("name", "").lower():
            candidate_scores[file_id] += 10
        if query_lower in file_record.get("path", "").lower():
            candidate_scores[file_id] += 5

    ranked = []
    for file_id, score in candidate_scores.most_common(max_results * 3):
        file_record = files[file_id]
        ranked.append(
            {
                "path": file_record["path"],
                "name": file_record["name"],
                "snippet": make_snippet(file_record.get("content", ""), query, 700),
                "score": score,
                "file_type": file_record.get("file_type", ""),
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:max_results]


def make_snippet(content: str, query: str, window: int = 500):
    content_lower = content.lower()
    query_lower = query.lower()

    index = content_lower.find(query_lower)
    if index == -1:
        return content[:window].strip()

    start = max(0, index - window // 2)
    end = min(len(content), index + window // 2)
    return content[start:end].strip()
