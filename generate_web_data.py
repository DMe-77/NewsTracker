#!/usr/bin/env python3
"""
generate_web_data.py - Generate docs/data.json for the dashboard.
"""

import json
import re
import html
import hashlib
from difflib import SequenceMatcher
from datetime import datetime, timezone

try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

INCIDENT_LOG_FILE = "incident_log.json"
TRUCK_STATS_FILE = "truck_stats.json"
OUTPUT_FILE = "docs/data.json"
EMBEDDING_CACHE_FILE = "embedding_cache.json"
MAX_INCIDENTS = 50
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

CHECKPOINT_NAME_MAP = {
    "капитан андреево": "Капитан Андреево",
    "лесово": "Лесово",
    "калотина": "Калотина",
}


def read_json_file(file_path, default_value):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_value

def write_json_file(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_incident_analysis(analysis_text):
    analysis = {
        "status": "🚨 Статус: Информация",
        "location": "📍 Локация: Не е посочена",
        "headline": "📰 Няма заглавие",
    }
    if not isinstance(analysis_text, str):
        return analysis

    for line in analysis_text.splitlines():
        line = line.strip()
        if line.startswith("🚨 Статус:"):
            analysis["status"] = line
        elif line.startswith("📍 Локация:"):
            analysis["location"] = line
        elif line.startswith("📰"):
            analysis["headline"] = line
    return analysis


def normalize_checkpoints(checkpoints):
    normalized = {}
    for key, values in (checkpoints or {}).items():
        display_key = CHECKPOINT_NAME_MAP.get((key or "").strip().lower(), key)
        normalized[display_key] = {
            "total": values.get("total", 0),
            "in": values.get("in"),
            "out": values.get("out"),
        }
    return normalized


def normalize_incidents(incidents):
    processed = []
    for incident in incidents:
        analysis = incident.get("analysis")
        if isinstance(analysis, str):
            analysis = parse_incident_analysis(analysis)
        elif not isinstance(analysis, dict):
            # Support flat incident_logger.py schema.
            status = incident.get("status", "Информация")
            location = incident.get("location", "Не е посочена")
            headline = incident.get("headline", "Няма заглавие")
            analysis = {
                "status": f"🚨 Статус: {status}",
                "location": f"📍 Локация: {location}",
                "headline": f"📰 {headline}",
            }

        links = incident.get("links")
        if not isinstance(links, list):
            # Support flat single-link + sources schema.
            link_url = incident.get("link", "")
            sources = incident.get("sources", [])
            source_domain = sources[0] if isinstance(sources, list) and sources else "source"
            links = [{"url": link_url, "domain": source_domain}] if link_url else []

        processed.append(
            {
                "first_seen_utc": incident.get("first_seen_utc") or incident.get("timestamp"),
                "analysis": analysis,
                "links": links,
            }
        )
    processed.sort(key=lambda x: x.get("first_seen_utc") or "", reverse=True)
    return processed[:MAX_INCIDENTS]

def parse_iso(iso_value):
    if not iso_value:
        return None
    try:
        return datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        return None

def clean_field(text, prefix):
    if not isinstance(text, str):
        return ""
    return text.replace(prefix, "").strip().lower()

def normalize_headline(text):
    text = clean_field(text, "📰")
    text = html.unescape(text)
    text = text.replace("резюме:", "").strip()
    text = text.replace("&apos;", "'").replace("&quot;", '"')
    text = re.sub(r"[\"'`]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text

_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    if SentenceTransformer is None:
        return None
    try:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        return _embedding_model
    except Exception:
        return None

def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def get_title_embedding(normalized_title, embedding_cache, model):
    if not normalized_title or model is None:
        return None
    key = text_hash(normalized_title)
    cached = embedding_cache.get(key)
    if isinstance(cached, list) and cached:
        return cached
    try:
        vector = model.encode(normalized_title, convert_to_numpy=True, normalize_embeddings=True).tolist()
        embedding_cache[key] = vector
        return vector
    except Exception:
        return None

GENERIC_TOKENS = {
    "турция", "турция.", "българия", "българо", "граница", "гкпп",
    "turkey", "bulgaria", "border", "news", "article",
    "задържан", "проверка", "инцидент", "случай",
}

ENTITY_ALIASES = {
    "kapikule": "капитан_андреево",
    "kapıkule": "капитан_андреево",
    "капъкуле": "капитан_андреево",
    "капитан": "капитан_андреево",
    "andreevo": "капитан_андреево",
    "hamzabeyli": "лесово",
    "хамзабейли": "лесово",
    "lesovo": "лесово",
    "лесово": "лесово",
    "malko": "малко_търново",
    "tarnovo": "малко_търново",
    "малко": "малко_търново",
    "търново": "малко_търново",
}

def tokenize(text):
    if not text:
        return set()
    text = text.lower()
    parts = re.findall(r"[a-zа-я0-9\-]{3,}", text, flags=re.IGNORECASE)
    tokens = set()
    for part in parts:
        normalized = ENTITY_ALIASES.get(part, part)
        if normalized in GENERIC_TOKENS:
            continue
        if normalized.isdigit():
            continue
        tokens.add(normalized)
    return tokens

def extract_entities(headline, location):
    h_tokens = tokenize(headline)
    l_tokens = tokenize(location)
    entities = set()
    for tok in h_tokens.union(l_tokens):
        if tok in {"капитан_андреево", "лесово", "малко_търново"}:
            entities.add(tok)
        elif len(tok) >= 6 and tok not in GENERIC_TOKENS:
            entities.add(tok)
    return entities

def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return inter / union if union else 0.0

def time_proximity_score(a_dt, b_dt):
    delta_hours = abs((a_dt - b_dt).total_seconds()) / 3600
    if delta_hours <= 6:
        return 1.0
    if delta_hours <= 12:
        return 0.8
    if delta_hours <= 24:
        return 0.6
    if delta_hours <= 36:
        return 0.35
    return 0.0

def title_similarity(a, b):
    if not a or not b:
        return 0.0
    # Approximate semantic match with sequence + token overlap blend.
    seq = SequenceMatcher(None, a, b).ratio()
    tok = jaccard(tokenize(a), tokenize(b))
    return 0.6 * seq + 0.4 * tok

def cluster_similarity(incident, cluster, embedding_cache, embedding_model):
    title_a = normalize_headline(incident.get("analysis", {}).get("headline", ""))
    loc_a = clean_field(incident.get("analysis", {}).get("location", ""), "📍 Локация:")
    ent_a = extract_entities(title_a, loc_a)
    key_a = tokenize(title_a).union(tokenize(loc_a))
    dt_a = parse_iso(incident.get("first_seen_utc"))
    emb_a = get_title_embedding(title_a, embedding_cache, embedding_model)

    title_b = cluster["canonical_headline"]
    ent_b = cluster["canonical_entities"]
    key_b = cluster["canonical_keywords"]
    dt_b = cluster["last_seen_dt"]
    emb_b = cluster.get("canonical_embedding")

    if not dt_a:
        return 0.0, 0.0, 0.0, 0.0

    seq_raw = SequenceMatcher(None, title_a, title_b).ratio() if title_a and title_b else 0.0
    t_score = title_similarity(title_a, title_b)
    semantic_title = cosine_similarity(emb_a, emb_b) if emb_a and emb_b else t_score
    e_score = jaccard(ent_a, ent_b)
    k_score = jaccard(key_a, key_b)
    time_score = time_proximity_score(dt_a, dt_b)

    base_similarity = (
        0.5 * semantic_title +
        0.3 * e_score +
        0.2 * k_score
    )
    similarity = base_similarity * (0.7 + 0.3 * time_score)
    return similarity, semantic_title, e_score, k_score, time_score, seq_raw, loc_a, emb_a

def build_incident_clusters(incidents):
    chronological = sorted(incidents, key=lambda x: x.get("first_seen_utc") or "")
    clusters = []
    embedding_cache = read_json_file(EMBEDDING_CACHE_FILE, {})
    if not isinstance(embedding_cache, dict):
        embedding_cache = {}
    embedding_model = get_embedding_model()

    for incident in chronological:
        ts = parse_iso(incident.get("first_seen_utc"))
        if not ts:
            continue

        status = incident.get("analysis", {}).get("status", "🚨 Статус: Информация")
        location = incident.get("analysis", {}).get("location", "📍 Локация: Не е посочена")
        headline = incident.get("analysis", {}).get("headline", "📰 Няма заглавие")
        normalized_headline = normalize_headline(headline)
        normalized_location = clean_field(location, "📍 Локация:")

        best_idx = None
        best_score = 0.0
        best_breakdown = (0.0, 0.0, 0.0, 0.0, None)
        for idx, cluster in enumerate(clusters):
            similarity, title_sem_score, e_score, k_score, time_score, seq_raw, loc_a, emb_a = cluster_similarity(
                incident, cluster, embedding_cache, embedding_model
            )
            entity_overlap_count = len(
                extract_entities(normalized_headline, normalized_location)
                .intersection(cluster["canonical_entities"])
            )
            strict_gate = similarity > 0.72 and (entity_overlap_count >= 2 or title_sem_score > 0.86)
            same_location_gate = (
                bool(loc_a) and
                bool(cluster.get("canonical_location")) and
                loc_a == cluster.get("canonical_location")
            )
            # Secondary gate: allow very close headline variants within tight time windows
            # to merge, while still requiring some shared entity/keyword signal.
            near_duplicate_gate = (
                seq_raw >= 0.82 and
                time_score >= 0.6 and
                (same_location_gate or entity_overlap_count >= 1 or k_score >= 0.2)
            )
            passes_gate = strict_gate or near_duplicate_gate
            if passes_gate and similarity > best_score:
                best_idx = idx
                best_score = similarity
                best_breakdown = (title_sem_score, e_score, entity_overlap_count, k_score, emb_a)

        if best_idx is not None:
            cluster = clusters[best_idx]
            cluster["last_seen_dt"] = max(cluster["last_seen_dt"], ts)
            if ts < cluster["first_seen_dt"]:
                cluster["first_seen_dt"] = ts
            cluster["incident_count"] += 1
            cluster["items"].append(incident)
            cluster["sources"].update(
                l.get("domain", "").strip()
                for l in incident.get("links", [])
                if l.get("domain")
            )
            if len(normalized_headline) > len(cluster["canonical_headline"]):
                cluster["canonical_headline"] = normalized_headline
                cluster["headline"] = headline
            cluster["canonical_entities"].update(extract_entities(normalized_headline, normalized_location))
            cluster["canonical_keywords"].update(tokenize(normalized_headline).union(tokenize(normalized_location)))
            if best_breakdown[4]:
                if cluster.get("canonical_embedding"):
                    n = cluster["incident_count"]
                    cluster["canonical_embedding"] = [
                        ((n - 1) * old + new) / n
                        for old, new in zip(cluster["canonical_embedding"], best_breakdown[4])
                    ]
                else:
                    cluster["canonical_embedding"] = best_breakdown[4]
            if "Критично" in status:
                cluster["status"] = "🚨 Статус: Критично"
            elif "Важно" in status and "Критично" not in cluster["status"]:
                cluster["status"] = "🚨 Статус: Важно"
            cluster["avg_title_similarity"] = (
                (cluster["avg_title_similarity"] * (cluster["incident_count"] - 2) + best_breakdown[0])
                / max(1, cluster["incident_count"] - 1)
            )
        else:
            clusters.append(
                {
                    "first_seen_dt": ts,
                    "last_seen_dt": ts,
                    "status": status,
                    "location": location,
                    "headline": headline,
                    "canonical_headline": normalized_headline,
                    "canonical_location": normalized_location,
                    "canonical_entities": extract_entities(normalized_headline, normalized_location),
                    "canonical_keywords": tokenize(normalized_headline).union(tokenize(normalized_location)),
                    "canonical_embedding": get_title_embedding(normalized_headline, embedding_cache, embedding_model),
                    "incident_count": 1,
                    "items": [incident],
                    "avg_title_similarity": 1.0,
                    "sources": {
                        l.get("domain", "").strip()
                        for l in incident.get("links", [])
                        if l.get("domain")
                    },
                }
            )

    materialized = []
    for idx, cluster in enumerate(sorted(clusters, key=lambda c: c["last_seen_dt"], reverse=True), 1):
        cluster_articles = []
        seen_urls = set()
        for item in sorted(cluster["items"], key=lambda x: x.get("first_seen_utc") or "", reverse=True):
            for link in item.get("links", []):
                url = (link.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                cluster_articles.append(
                    {
                        "domain": (link.get("domain") or "source").strip(),
                        "url": url,
                        "headline": item.get("analysis", {}).get("headline", "📰 Няма заглавие"),
                        "first_seen_utc": item.get("first_seen_utc"),
                    }
                )
        materialized.append(
            {
                "id": f"cluster-{idx}",
                "first_seen_utc": cluster["first_seen_dt"].isoformat(),
                "last_seen_utc": cluster["last_seen_dt"].isoformat(),
                "analysis": {
                    "status": cluster["status"],
                    "location": cluster["location"],
                    "headline": cluster["headline"],
                },
                "incident_count": cluster["incident_count"],
                "source_count": len(cluster["sources"]),
                "sources": sorted(cluster["sources"]),
                "cluster_confidence": round(min(0.99, 0.55 + 0.08 * len(cluster["sources"]) + 0.15 * cluster["avg_title_similarity"]), 2),
                "articles": cluster_articles,
            }
        )
    write_json_file(EMBEDDING_CACHE_FILE, embedding_cache)
    return materialized


def normalize_truck_stats(truck_stats):
    processed = []
    for stat in truck_stats:
        raw_date = stat.get("date")
        if not raw_date:
            continue
        try:
            dt_obj = datetime.strptime(raw_date, "%d-%m-%Y")
        except ValueError:
            try:
                dt_obj = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                continue

        processed.append(
            {
                "date": dt_obj.strftime("%Y-%m-%d"),
                "url": stat.get("url", ""),
                "checkpoints": normalize_checkpoints(stat.get("checkpoints", {})),
            }
        )
    processed.sort(key=lambda x: x["date"])
    return processed


def main():
    incidents = read_json_file(INCIDENT_LOG_FILE, [])
    truck_stats = read_json_file(TRUCK_STATS_FILE, [])

    output_data = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "truck_stats": normalize_truck_stats(truck_stats),
        "incidents": normalize_incidents(incidents),
    }
    output_data["incident_clusters"] = build_incident_clusters(output_data["incidents"])

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=4)

    print(
        f"Successfully generated {OUTPUT_FILE} with "
        f"{len(output_data['incidents'])} incidents and "
        f"{len(output_data['truck_stats'])} truck stats."
    )


if __name__ == "__main__":
    main()
