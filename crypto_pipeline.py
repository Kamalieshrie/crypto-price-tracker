"""
Crypto Price Tracker
Fetch the top 20 coins by market cap from the CoinGecko API and append
them, with a timestamp, to a SQLite table.

Run:  python crypto_pipeline.py
"""
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

DB_PATH = "crypto.db"
URL = "https://api.coingecko.com/api/v3/coins/markets"
PARAMS = {
    "vs_currency": "usd",
    "order": "market_cap_desc",
    "per_page": 20,
    "page": 1,
    "price_change_percentage": "1h,24h,7d",
}
COLS = [
    "id", "symbol", "name", "market_cap_rank", "current_price",
    "market_cap", "total_volume",
    "price_change_percentage_1h_in_currency",
    "price_change_percentage_24h",
    "price_change_percentage_7d_in_currency",
    "last_updated",
]
RENAME = {
    "price_change_percentage_1h_in_currency": "change_1h",
    "price_change_percentage_24h": "change_24h",
    "price_change_percentage_7d_in_currency": "change_7d",
}
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS prices (
    id TEXT, symbol TEXT, name TEXT, market_cap_rank INTEGER,
    current_price REAL, market_cap REAL, total_volume REAL,
    change_1h REAL, change_24h REAL, change_7d REAL,
    last_updated TEXT, scraped_at TEXT,
    PRIMARY KEY (id, scraped_at)
)"""

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def fetch(retries=3):
    """Call the API, retrying with a growing wait if it fails."""
    headers = {}
    # Optional key. Confirm the header name in the Demo API docs (Authentication page).
    key = os.environ.get("COINGECKO_API_KEY")
    if key:
        headers["x-cg-demo-api-key"] = key
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(URL, params=PARAMS, headers=headers, timeout=15)
            r.raise_for_status()          # raises on 429, 401, 500, ...
            data = r.json()
            if not isinstance(data, list) or not data:
                raise ValueError("Unexpected or empty response")
            return data
        except (requests.RequestException, ValueError) as e:
            logging.warning("Attempt %d/%d failed: %s", attempt, retries, e)
            if attempt < retries:
                time.sleep(20 * attempt)
    raise RuntimeError("API failed after all retries")


def clean(data):
    """Keep our columns, fix names, drop unusable rows, add timestamps."""
    df = pd.DataFrame(data)[COLS].rename(columns=RENAME)
    df = df.dropna(subset=["id", "current_price"])
    df["last_updated"] = pd.to_datetime(df["last_updated"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    df["scraped_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return df


def save(df):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(CREATE_SQL)
        df.to_sql("prices", conn, if_exists="append", index=False)


def main():
    df = clean(fetch())
    save(df)
    logging.info("Saved %d rows to %s", len(df), DB_PATH)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Pipeline failed")
        sys.exit(1)     # non-zero exit makes the GitHub Actions run show as failed
