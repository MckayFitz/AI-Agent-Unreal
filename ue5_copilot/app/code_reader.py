def search_files(files, query: str, max_results: int = 5):
    terms = [term.lower() for term in query.split() if term.strip()]
    query_lower = query.lower().strip()
    matches = []

    for file in files:
        content = file.get("content", "")
        name_lower = file.get("name", "").lower()
        content_lower = content.lower()
        score = 0

        if not query_lower:
            continue

        if query_lower in name_lower:
            score += 10
        if query_lower in content_lower:
            score += 8

        for term in terms:
            if term in name_lower:
                score += 4
            if term in content_lower:
                score += content_lower.count(term)

        if score > 0:
            snippet = make_snippet(content, query, 700)
            matches.append({
                "path": file["path"],
                "name": file["name"],
                "snippet": snippet,
                "score": score
            })

    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:max_results]


def make_snippet(content: str, query: str, window: int = 500):
    content_lower = content.lower()
    query_lower = query.lower()

    index = content_lower.find(query_lower)
    if index == -1:
        return content[:window].strip()

    start = max(0, index - window // 2)
    end = min(len(content), index + window // 2)
    return content[start:end].strip()
