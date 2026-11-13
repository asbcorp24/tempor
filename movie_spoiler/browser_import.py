#!/usr/bin/env python3
"""Visible Chromium importer. Stops if the site denies access."""
import argparse
import logging
import random
import sqlite3
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

from movie_spoiler_scraper import BASE, is_movie, parse_movie, setup

LOG = logging.getLogger("browser_import")


def open_page(page, url):
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except BrowserTimeout:
        LOG.warning("Page timeout: %s", url)
        return None
    if response and response.status in (403, 429):
        LOG.error("Server denied access (HTTP %s): %s. Stopping.", response.status, url)
        return None
    if response and response.status >= 400:
        LOG.warning("HTTP %s: %s", response.status, url)
        return None
    return page.content()


def main():
    ap = argparse.ArgumentParser(description="Import spoilers using visible Chromium")
    ap.add_argument("--db", default="spoilers.db")
    ap.add_argument("--limit", type=int, default=5, help="Max new movies (0 = unlimited)")
    ap.add_argument("--pages", type=int, default=10, help="Max archive pages")
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    if args.delay < 1:
        ap.error("--delay must be >= 1")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with sqlite3.connect(args.db) as db, sync_playwright() as pw:
        setup(db)
        profile = str(Path(__file__).resolve().parent / ".browser_profile")
        context = pw.chromium.launch_persistent_context(profile, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            urls = set()
            for index in range(1, args.pages + 1):
                url = BASE if index == 1 else urljoin(BASE, f"page/{index}/")
                html = open_page(page, url)
                if html is None:
                    return
                soup = BeautifulSoup(html, "html.parser")
                batch = {urljoin(url, a["href"]) for a in soup.select("a[href]")
                         if is_movie(urljoin(url, a["href"]))}
                new = batch - urls
                urls.update(batch)
                LOG.info("Archive %s: %d movie links (%d new)", index, len(batch), len(new))
                if not batch or (index > 1 and not new):
                    break
                time.sleep(args.delay + random.uniform(0, 0.5))
            existing = set() if args.refresh else {r[0] for r in db.execute("SELECT url FROM movies")}
            todo = sorted(urls - existing)
            if args.limit:
                todo = todo[:args.limit]
            LOG.info("Processing %d movies", len(todo))
            for index, url in enumerate(todo, 1):
                time.sleep(args.delay + random.uniform(0, 0.5))
                html = open_page(page, url)
                if html is None:
                    break
                movie = parse_movie(html, url)
                if not movie:
                    LOG.warning("Could not parse %s", url)
                    continue
                db.execute("""INSERT INTO movies(url,title,year,plot,published_at,genres,fetched_at,ending,poster_url)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(url) DO UPDATE SET title=excluded.title, year=excluded.year,
                    plot=excluded.plot, published_at=excluded.published_at,
                    genres=excluded.genres, fetched_at=excluded.fetched_at,
                    ending=excluded.ending, poster_url=excluded.poster_url""", movie)
                db.commit()
                LOG.info("[%d/%d] Saved %s", index, len(todo), movie[1])
            LOG.info("Total movies in DB: %d", db.execute("SELECT COUNT(*) FROM movies").fetchone()[0])
        finally:
            context.close()


if __name__ == "__main__":
    main()
