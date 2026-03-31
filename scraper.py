#!/usr/bin/env python3
"""
HelloAsso Scraper — Recherche d'associations via l'API Algolia interne.

Usage:
    python3 scraper.py "croix rouge"
    python3 scraper.py "association sportive" --city Paris --max-pages 5
    python3 scraper.py "environnement" --output results.json
    python3 scraper.py "solidarité" --output results.csv
"""

import argparse
import csv
import json
import sys
import time

import requests

ALGOLIA_URL = "https://www.helloasso.com/algolia/1/indexes/*/queries"
ALGOLIA_APP_ID = "KOCVQI75M9"
ALGOLIA_API_KEY = "980128990635aaa7c2595b668df87497"
HITS_PER_PAGE = 30
REQUEST_DELAY = 2.0  # secondes entre chaque requête (rate limiting Cloudflare)
MAX_RETRIES = 3

HEADERS = {
    "Content-Type": "application/json",
    "x-algolia-application-id": ALGOLIA_APP_ID,
    "x-algolia-api-key": ALGOLIA_API_KEY,
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.helloasso.com/e/recherche/associations",
    "Origin": "https://www.helloasso.com",
}

# Index disponibles : prod_organizations, prod_activities, prod_projects,
# prod_cities, prod_content, prod_tags, prod_partners


def set_delay(value: float):
    global REQUEST_DELAY
    REQUEST_DELAY = value


def search_page(query: str, index: str, page: int, filters: str = "") -> dict:
    """Effectue une recherche sur une page donnée avec retry automatique."""
    params_parts = [f"hitsPerPage={HITS_PER_PAGE}", f"page={page}"]
    if filters:
        params_parts.append(f"filters={filters}")

    payload = {
        "requests": [
            {
                "indexName": index,
                "query": query,
                "params": "&".join(params_parts),
            }
        ]
    }

    for attempt in range(MAX_RETRIES):
        resp = requests.post(ALGOLIA_URL, headers=HEADERS, json=payload, timeout=15)

        if resp.status_code == 200:
            return resp.json()["results"][0]

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            # Plafonner le wait à 120s max pour rester raisonnable
            wait = min(retry_after + 5, 120)
            print(f"\n⏳ Rate limité (429). Retry-After: {retry_after}s. "
                  f"Attente {wait}s (tentative {attempt + 1}/{MAX_RETRIES})...")
            time.sleep(wait)
            continue

        # Autres erreurs
        resp.raise_for_status()

    print("❌ Trop de tentatives échouées (rate limiting persistant).")
    print("   Essayez plus tard ou augmentez --delay.")
    sys.exit(1)


def build_filters(city: str = "", department: str = "", region: str = "") -> str:
    """Construit la chaîne de filtres Algolia."""
    parts = []
    if city:
        parts.append(f"place_city:{city}")
    if department:
        parts.append(f"place_department:{department}")
    if region:
        parts.append(f"place_region:{region}")
    return " AND ".join(parts)


def search_all(
    query: str,
    index: str = "prod_organizations",
    max_pages: int = 10,
    filters: str = "",
) -> list[dict]:
    """Récupère toutes les pages de résultats."""
    all_hits = []
    page = 0

    result = search_page(query, index, page, filters)
    total_hits = result.get("nbHits", 0)
    total_pages = result.get("nbPages", 0)
    all_hits.extend(result.get("hits", []))

    print(f"Trouvé {total_hits} résultats ({total_pages} pages)")

    pages_to_fetch = min(total_pages, max_pages)
    for page in range(1, pages_to_fetch):
        time.sleep(REQUEST_DELAY)
        print(f"  Page {page + 1}/{pages_to_fetch}...", end="\r")
        result = search_page(query, index, page, filters)
        hits = result.get("hits", [])
        if not hits:
            break
        all_hits.extend(hits)

    print(f"\nRécupéré {len(all_hits)} associations")
    return all_hits


def flatten_hit(hit: dict) -> dict:
    """Aplatit un résultat Algolia pour l'export CSV."""
    geo = hit.get("_geoloc") or {}
    return {
        "objectID": hit.get("objectID", ""),
        "name": hit.get("name", ""),
        "description": (hit.get("description") or "")[:300],
        "url": hit.get("url", "").replace("https://www.helloasso.com", "", 1) if hit.get("url", "").startswith("https://") else hit.get("url", ""),
        "logo": hit.get("logo", ""),
        "city": hit.get("place_city", ""),
        "zipcode": hit.get("place_zipcode", ""),
        "department": hit.get("place_department", ""),
        "region": hit.get("place_region", ""),
        "address": hit.get("place_address", ""),
        "lat": geo.get("lat", ""),
        "lng": geo.get("lng", ""),
        "org_type": hit.get("org_type", ""),
        "category_tags": ", ".join(hit.get("category_tags") or []),
        "ha_tags": ", ".join(hit.get("ha_tags") or []),
        "active_forms_count": hit.get("active_forms_count", 0),
        "creation_date": hit.get("creation_date", ""),
        "score": hit.get("score", ""),
    }


def save_json(hits: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hits, f, ensure_ascii=False, indent=2)
    print(f"Sauvegardé dans {path}")


def save_csv(hits: list[dict], path: str):
    rows = [flatten_hit(h) for h in hits]
    if not rows:
        print("Aucun résultat à sauvegarder.")
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Sauvegardé dans {path}")


def print_summary(hits: list[dict], limit: int = 20):
    """Affiche un résumé des résultats dans le terminal."""
    for i, hit in enumerate(hits[:limit], 1):
        name = hit.get("name", "?")
        city = hit.get("place_city", "")
        dept = hit.get("place_department", "")
        url = hit.get("url", "")
        loc = f"{city} ({dept})" if city else dept
        print(f"  {i:3}. {name}")
        if loc:
            print(f"       loc: {loc}")
        if url:
            full_url = url if url.startswith("http") else f"https://www.helloasso.com{url}"
            print(f"       url: {full_url}")
        print()
    if len(hits) > limit:
        print(f"  ... et {len(hits) - limit} autres résultats")


def main():
    parser = argparse.ArgumentParser(
        description="Scraper HelloAsso — recherche d'associations"
    )
    parser.add_argument("query", help="Terme de recherche")
    parser.add_argument(
        "--index",
        default="prod_organizations",
        help="Index Algolia (default: prod_organizations)",
    )
    parser.add_argument("--city", default="", help="Filtrer par ville")
    parser.add_argument("--department", default="", help="Filtrer par département")
    parser.add_argument("--region", default="", help="Filtrer par région")
    parser.add_argument(
        "--max-pages", type=int, default=10, help="Nombre max de pages (default: 10)"
    )
    parser.add_argument(
        "--output", "-o", default="", help="Fichier de sortie (.json ou .csv)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY,
        help=f"Délai entre requêtes en secondes (default: {REQUEST_DELAY})",
    )

    args = parser.parse_args()
    set_delay(args.delay)

    filters = build_filters(
        city=args.city, department=args.department, region=args.region
    )

    print(f'Recherche: "{args.query}"')
    if filters:
        print(f"Filtres: {filters}")
    print()

    hits = search_all(args.query, args.index, args.max_pages, filters)

    if not hits:
        print("Aucun résultat trouvé.")
        sys.exit(0)

    print_summary(hits)

    if args.output:
        if args.output.endswith(".csv"):
            save_csv(hits, args.output)
        else:
            save_json(hits, args.output)


if __name__ == "__main__":
    main()
