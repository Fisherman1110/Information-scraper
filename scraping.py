import sqlite3
from newspaper import build, Config
from concurrent.futures import ThreadPoolExecutor, as_completed
from langdetect import detect, LangDetectException

# ==============================
# Config for Newspaper
# ==============================
config = Config()
config.request_timeout = 10  # max seconds per request

# ==============================
# Trusted news sources
# ==============================
SOURCES = {
    "CNN": "https://edition.cnn.com",
    "BBC": "https://www.bbc.com",
    "Al Jazeera": "https://www.aljazeera.com",
    "Times of Israel": "https://www.timesofisrael.com"
}

# ==============================
# Database setup
# ==============================
def init_db():
    conn = sqlite3.connect("news_articles.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        title TEXT,
        url TEXT UNIQUE,
        summary TEXT,
        keywords TEXT,
        text TEXT
    )
    """)
    conn.commit()
    return conn, cursor

def clean_text(text):
    if not text:
        return ""
    return text.replace("\x00", "").strip()

def save_article(cursor, conn, article, source):
    cursor.execute("""
    INSERT OR IGNORE INTO articles (source, title, url, summary, keywords, text)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        source,
        clean_text(article.title),
        clean_text(article.url),
        clean_text(article.summary),
        clean_text(", ".join(article.keywords)),
        clean_text(article.text)
    ))
    conn.commit()

# ==============================
# URL Filters
# ==============================
BAD_PATTERNS = [
    "/ads/", "/advertorial/", "/iplayer/", "/reel/", "/av/", "/promo/", "/sponsored/"
]

GOOD_PATTERNS = {
    "BBC": ["/news/", "/sport/"],
    "CNN": ["/2025/"],  # only 2025 for CNN
    # others can be empty list if all articles are OK
    "Al Jazeera": [],
    "Times of Israel": []
}

def is_valid_article(article, source):
    url = article.url.lower()
    if any(bad in url for bad in BAD_PATTERNS):
        return False
    good_patterns = GOOD_PATTERNS.get(source, [])
    if good_patterns and not any(good in url for good in good_patterns):
        return False
    return True

# ==============================
# Article processing
# ==============================
def process_article(article):
    try:
        article.download()
        article.parse()
        article.nlp()
        return article
    except Exception as e:
        return f"Failed to process {article.url}: {e}"

# ==============================
# Scraping function
# ==============================
def scrape_sources(workers=8, keywords=None, max_per_source=None):
    all_raw_articles = []

    # 1️⃣ Build articles from all sources
    for source_name, url in SOURCES.items():
        print(f"🔹 Building source: {source_name}")
        paper = build(url, memoize_articles=False, config=config)
        source_articles = [a for a in paper.articles if is_valid_article(a, source_name)]
        if max_per_source:
            source_articles = source_articles[:max_per_source]
        print(f"   Found {len(source_articles)} articles in {source_name}")
        all_raw_articles.extend([(a, source_name) for a in source_articles])

    print(f"Total articles to scrape: {len(all_raw_articles)}")

    # 2️⃣ Process articles in threads
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_article = {executor.submit(process_article, a[0]): a for a in all_raw_articles}
        for i, future in enumerate(as_completed(future_to_article), start=1):
            article, source = future_to_article[future]
            result = future.result()

            if isinstance(result, str):
                print(f"❌ {result}")
                continue

            # Language filter
            try:
                if detect(result.text) != "en":
                    print(f"⛔ Skipped non-English: {result.url}")
                    continue
            except LangDetectException:
                print(f"⚠️ Could not detect language: {result.url}")
                continue

            # Keyword filter
            if keywords:
                text_lower = (result.title + " " + result.summary + " " + result.text).lower()
                if not any(kw.lower() in text_lower for kw in keywords):
                    print(f"⛔ Skipped (no keyword match): {result.url}")
                    continue

            # Passed all filters
            results.append((result, source))
            print(f"✅ {i}/{len(all_raw_articles)} Passed: {result.title}")

    return results

# ==============================
# Search saved articles
# ==============================
def search_articles(term, cursor):
    cursor.execute("""
    SELECT source, title, url, summary FROM articles
    WHERE LOWER(summary) LIKE ? OR LOWER(text) LIKE ? OR LOWER(keywords) LIKE ?
    """, (f"%{term}%", f"%{term}%", f"%{term}%"))

    results = cursor.fetchall()
    if results:
        for row in results:
            print("="*80)
            print(f"[{row[0]}] {row[1]}")
            print(f"{row[2]}")
            print(f"{row[3]}\n")
    else:
        print("No articles found.")

# ==============================
# Main Program Menu
# ==============================
if __name__ == "__main__":
    conn, cursor = init_db()

    while True:
        print("\n📰 Multi-Source News Scraper")
        print("1. Scrape new articles (with optional keyword filter)")
        print("2. Search saved articles")
        print("3. Exit")

        choice = input("Choose an option: ").strip()

        if choice == "1":
            workers = int(input("How many threads? (e.g., 8): "))
            max_articles = input("Max articles per source? (Enter for all): ")
            max_articles = int(max_articles) if max_articles.strip().isdigit() else None

            keyword_input = input("Filter by keywords? (comma-separated, Enter for none): ").strip()
            keywords = [kw.strip() for kw in keyword_input.split(",")] if keyword_input else None

            scraped = scrape_sources(workers=workers, keywords=keywords, max_per_source=max_articles)
            for art, source in scraped:
                save_article(cursor, conn, art, source)
                print("="*80)
                print(f"[{source}] {art.title}")
                print(f"URL: {art.url}")
                print(f"Text preview: {art.text[:20000]}\n")

        elif choice == "2":
            term = input("Enter keyword to search: ").lower()
            search_articles(term, cursor)

        elif choice == "3":
            print("Goodbye!")
            break

        else:
            print("Invalid choice. Try again.")
