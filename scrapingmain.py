import sqlite3
from newspaper import build, Config
from concurrent.futures import ThreadPoolExecutor, as_completed
from langdetect import detect, LangDetectException

# ==============================
# Newspaper config
# ==============================
config = Config()
config.request_timeout = 10  # max seconds per request

# ==============================
# Database setup
# ==============================
def init_db():
    conn = sqlite3.connect("cnn_articles.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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

def save_article(cursor, conn, article):
    cursor.execute("""
    INSERT OR IGNORE INTO articles (title, url, summary, keywords, text)
    VALUES (?, ?, ?, ?, ?)
    """, (
        clean_text(article.title),
        clean_text(article.url),
        clean_text(article.summary),
        clean_text(", ".join(article.keywords)),
        clean_text(article.text)
    ))
    conn.commit()

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
# Scraping CNN articles
# ==============================
def scrape_all_articles(workers=8, peos=None, keywords=None):
    cnn_paper = build("https://edition.cnn.com", memoize_articles=False, config=config)

    # Only keep date-stamped 2025 URLs
    raw_articles = [a for a in cnn_paper.articles if a.url.startswith("https://edition.cnn.com/2025/")]

    # Apply slicing if requested
    if peos:
        raw_articles = raw_articles[:peos]

    print(f"Found {len(raw_articles)} CNN articles to scrape.")

    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_article = {executor.submit(process_article, a): a for a in raw_articles}
        for i, future in enumerate(as_completed(future_to_article), start=1):
            result = future.result()

            # Skip failed articles
            if isinstance(result, str):
                print(result)
                continue

            # Language filter (must be English)
            try:
                if detect(result.text) != "en":
                    print(f"Skipped non-English: {result.url}")
                    continue
            except LangDetectException:
                print(f"Could not detect language: {result.url}")
                continue

            # Keyword filter (must match at least one keyword)
            if keywords:
                text_lower = (result.title + " " + result.summary + " " + result.text).lower()
                if not any(kw.lower() in text_lower for kw in keywords):
                    print(f"Skipped (no keyword match): {result.url}")
                    continue

            # Passed all filters — add to results for saving
            results.append(result)
            print(f"Passed filters {i}/{len(raw_articles)}: {result.title}")

    return results

# ==============================
# Search saved articles
# ==============================
def search_articles(term, cursor):
    cursor.execute("""
    SELECT title, url, summary FROM articles
    WHERE LOWER(summary) LIKE ? OR LOWER(text) LIKE ? OR LOWER(keywords) LIKE ?
    """, (f"%{term}%", f"%{term}%", f"%{term}%"))

    results = cursor.fetchall()

    if results:
        for row in results:
            print("="*80)
            print(f"{row[0]}")
            print(f"{row[1]}")
            print(f"{row[2]}\n")
    else:
        print("No articles found.")

# ==============================
# Main Program Menu
# ==============================
if __name__ == "__main__":
    conn, cursor = init_db()

    while True:
        print("\nCNN Article Scraper & Archive (Persistent Edition)")
        print("1. Scrape ALL new articles (skip saved ones, with keyword filter)")
        print("2. Search saved articles")
        print("3. Exit")

        choice = input("Choose an option: ")

        if choice == "1":
            workers = int(input("How many threads to use? (e.g. 8): "))
            peos = input("How many articles to scrape? (press Enter for all): ")
            peos = int(peos) if peos.strip().isdigit() else None

            keyword_input = input("Filter by keywords? (comma separated, Enter for none): ").strip()
            keywords = [kw.strip() for kw in keyword_input.split(",")] if keyword_input else None

            print(f"\n⚡ Scraping CNN articles with {workers} threads...\n")

            scraped = scrape_all_articles(workers, peos, keywords)
            for art in scraped:
                save_article(cursor, conn, art)
                print("="*80)
                print(f"Title: {art.title}")
                print(f"URL: {art.url}")
                print(f"Text Preview: {art.text[:20000]}...\n")

        elif choice == "2":
            term = input("Enter keyword to search: ").lower()
            search_articles(term, cursor)

        elif choice == "3":
            print("Goodbye!")
            break

        else:
            print("Invalid choice. Try again.")
