#!/usr/bin/env python3
"""Polite, resumable TheMovieSpoiler -> SQLite importer."""
import argparse
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

BASE = 'https://themoviespoiler.com/'
HEADERS = {'User-Agent': 'MovieSpoilerPersonalIndexer/1.0 (respectful archival indexing)'}
LOG = logging.getLogger('spoilers')


class AccessDenied(Exception):
    """Server explicitly denied access to a normal page or rate-limited requests."""



def fetch(session, url, delay):
    time.sleep(delay + random.uniform(0, 0.5))
    try:
        r = session.get(url, timeout=35)
        if r.status_code in (403, 429):
            raise AccessDenied(f'HTTP {r.status_code} at {url}')
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        LOG.warning('Request failed %s: %s', url, e)
        return None


def is_movie(url):
    p = urlparse(url)
    return p.netloc.lower() in ('themoviespoiler.com', 'www.themoviespoiler.com') and bool(re.fullmatch(r'/movies/[^/]+/?', p.path))


def sitemap_urls(session, delay):
    queue = [urljoin(BASE, 'wp-sitemap.xml'), urljoin(BASE, 'sitemap_index.xml')]
    seen = set()
    movies = set()
    while queue:
        url = queue.pop(0)
        if url in seen or len(seen) > 250:
            continue
        seen.add(url)
        try:
            response = fetch(session, url, delay)
        except AccessDenied as exc:
            if 'HTTP 429' in str(exc):
                raise
            LOG.warning('Sitemap unavailable (%s); trying other sources', exc)
            continue
        if response is None:
            continue
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            continue
        for element in root.iter():
            if element.tag.rsplit('}', 1)[-1] != 'loc' or not element.text:
                continue
            link = element.text.strip()
            if is_movie(link):
                movies.add(link)
            elif link.startswith(BASE) and (link.endswith('.xml') or '.xml?' in link):
                if link not in seen:
                    queue.append(link)
    return movies


def html_urls(session, delay, max_pages):
    """Fallback: collect movie links from homepage and paginated archive."""
    found = set()
    for page in range(1, max_pages + 1):
        url = BASE if page == 1 else urljoin(BASE, f'page/{page}/')
        try:
            response = fetch(session, url, delay)
        except AccessDenied as exc:
            LOG.error('Archive access denied: %s. Stopping; no bypass attempted.', exc)
            break
        if response is None:
            break
        soup = BeautifulSoup(response.text, 'html.parser')
        batch = {urljoin(url, a['href']) for a in soup.select('a[href]') if is_movie(urljoin(url, a['href']))}
        new = batch - found
        found.update(batch)
        LOG.info('Archive page %d: %d links (%d new)', page, len(batch), len(new))
        if not batch or (page > 1 and not new):
            break
    return found


def clean_text(element):
    if element is None:
        return ''
    copy = BeautifulSoup(str(element), 'html.parser')
    for bad in copy.select('script, style, nav, aside, form, .sharedaddy, .crp_related, .yarpp-related, .jp-relatedposts, .advertisement, .adsbygoogle'):
        bad.decompose()
    lines = [re.sub(r'\s+', ' ', x).strip() for x in copy.stripped_strings]
    return '\n\n'.join(x for x in lines if x)


def parse_movie(html, url):
    """Extract full plot and separate Cut to the Chase ending from a movie page."""
    soup = BeautifulSoup(html, 'html.parser')
    article = soup.select_one('article.type-movies, article.movies')
    if article is None:
        return None
    content = article.select_one('.entry-content')
    title_node = content.select_one('h1.entry-title') if content else None
    if content is None or title_node is None:
        return None
    title = title_node.get_text(' ', strip=True)
    poster_node = article.select_one('.post-thumbnail img')
    poster = ''
    if poster_node:
        poster = urljoin(url, poster_node.get('src', ''))
    if not poster:
        meta = soup.select_one('meta[property="og:image"]')
        poster = meta.get('content', '') if meta else ''

    # The actual page has a short ending section after #cut-to-the-chase.
    # Use only direct paragraph children to avoid related-movie text.
    plot_parts, ending_parts = [], []
    ending_started = False
    for child in content.children:
        if not getattr(child, 'name', None):
            continue
        if child.get('id') == 'cut-to-the-chase':
            ending_started = True
            continue
        if child.name != 'p':
            continue
        # Ignore embedded trailers, ad widgets and empty paragraphs.
        if child.find(['iframe', 'video']):
            continue
        value = child.get_text(' ', strip=True)
        if not value:
            continue
        (ending_parts if ending_started else plot_parts).append(value)

    plot = '\n\n'.join(plot_parts)
    ending = '\n\n'.join(ending_parts)
    if len(plot) < 150:
        return None
    date_node = soup.select_one('time[datetime]')
    published = date_node.get('datetime', '') if date_node else ''
    if not published:
        meta = soup.select_one('meta[property="article:published_time"]')
        published = meta.get('content', '') if meta else ''
    year_match = re.search(r'\((19\d{2}|20\d{2})\)', title)
    year = int(year_match.group(1)) if year_match else None
    genres = ', '.join(sorted({c.removeprefix('genres-').replace('-', ' ').title()
                               for c in article.get('class', []) if c.startswith('genres-')}))
    return (url, title, year, plot, published, genres,
            datetime.now(timezone.utc).isoformat(), ending, poster)


def setup(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS movies (
        url TEXT PRIMARY KEY, title TEXT NOT NULL, year INTEGER,
        plot TEXT NOT NULL, published_at TEXT, genres TEXT,
        fetched_at TEXT NOT NULL
    )''')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(movies)')}
    if 'ending' not in columns:
        conn.execute("ALTER TABLE movies ADD COLUMN ending TEXT DEFAULT ''")
    if 'poster_url' not in columns:
        conn.execute("ALTER TABLE movies ADD COLUMN poster_url TEXT DEFAULT ''")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(title)')
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description='Import The Movie Spoiler articles into SQLite')
    parser.add_argument('--db', default='spoilers.db')
    parser.add_argument('--delay', type=float, default=2.0, help='Seconds between requests (default 2)')
    parser.add_argument('--limit', type=int, default=0, help='Limit processed movies; 0 means all')
    parser.add_argument('--pages', type=int, default=100, help='Max archive pages for fallback')
    parser.add_argument('--refresh', action='store_true', help='Re-fetch already saved movies')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    if args.delay < 1:
        parser.error('--delay must be >= 1 second')
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    with requests.Session() as session, sqlite3.connect(args.db) as conn:
        session.headers.update(HEADERS)
        setup(conn)
        try:
            urls = sitemap_urls(session, args.delay)
            LOG.info('Sitemaps: %d movie URLs', len(urls))
            if not urls:
                LOG.info('No sitemap links; trying public HTML archive')
                urls = html_urls(session, args.delay, args.pages)
        except AccessDenied as exc:
            LOG.error('Request rate-limited or denied: %s. Stopping.', exc)
            return
        if not urls:
            LOG.error('No movie URLs found. Check site layout/access; nothing saved.')
            return
        completed = {row[0] for row in conn.execute('SELECT url FROM movies')} if not args.refresh else set()
        todo = sorted(urls - completed)
        if args.limit:
            todo = todo[:args.limit]
        LOG.info('Found %d; saved already %d; processing %d', len(urls), len(completed), len(todo))
        ok = 0
        for index, url in enumerate(todo, 1):
            try:
                response = fetch(session, url, args.delay)
            except AccessDenied as exc:
                LOG.error('Access denied: %s. Stopping.', exc)
                break
            if response is None:
                continue
            movie = parse_movie(response.text, url)
            if not movie:
                LOG.warning('[%d/%d] Could not extract article: %s', index, len(todo), url)
                continue
            conn.execute('''INSERT INTO movies(url,title,year,plot,published_at,genres,fetched_at,ending,poster_url)
                            VALUES(?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(url) DO UPDATE SET title=excluded.title,year=excluded.year,
                            plot=excluded.plot,published_at=excluded.published_at,
                            genres=excluded.genres,fetched_at=excluded.fetched_at,
                            ending=excluded.ending,poster_url=excluded.poster_url''', movie)
            conn.commit()
            ok += 1
            LOG.info('[%d/%d] saved %s (%d chars)', index, len(todo), movie[1], len(movie[3]))
        LOG.info('Finished. Saved this run: %d; total in DB: %d', ok, conn.execute('SELECT count(*) FROM movies').fetchone()[0])


if __name__ == '__main__':
    main()
