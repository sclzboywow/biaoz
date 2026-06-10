#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_library_db_path() -> str:
    return os.getenv("LIBRARY_DB_PATH") or os.path.join(BASE_DIR, "library.db")


def init_library_db() -> str:
    db_path = get_library_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS lib_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qq_user_id TEXT NOT NULL UNIQUE,
            nickname TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS raw_crawl_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT,
            raw_title TEXT,
            raw_code TEXT,
            raw_payload TEXT,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            keywords TEXT,
            status TEXT DEFAULT 'active',
            ticket_cost INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_documents_code ON documents(code);
        CREATE INDEX IF NOT EXISTS idx_documents_title ON documents(title);
        CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);

        CREATE TABLE IF NOT EXISTS document_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            alias_norm TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents(id),
            UNIQUE(alias_norm)
        );
        CREATE INDEX IF NOT EXISTS idx_document_aliases_doc ON document_aliases(document_id);

        CREATE TABLE IF NOT EXISTS pan_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL UNIQUE,
            pan_file_path TEXT,
            pan_fs_id TEXT,
            file_name TEXT,
            file_size INTEGER,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (document_id) REFERENCES documents(id)
        );

        CREATE TABLE IF NOT EXISTS pan_share_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pan_asset_id INTEGER NOT NULL,
            pan_share_url TEXT NOT NULL,
            pan_extract_code TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (pan_asset_id) REFERENCES pan_assets(id)
        );
        CREATE INDEX IF NOT EXISTS idx_pan_share_asset ON pan_share_links(pan_asset_id, is_active);

        CREATE TABLE IF NOT EXISTS ticket_wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            balance INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES lib_users(id)
        );

        CREATE TABLE IF NOT EXISTS ticket_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            group_id TEXT,
            pack_code TEXT NOT NULL,
            ticket_count INTEGER NOT NULL,
            amount_cent INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            pay_url TEXT,
            alipay_trade_no TEXT,
            expired_at REAL,
            paid_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES lib_users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_ticket_orders_user ON ticket_orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_ticket_orders_status ON ticket_orders(status);

        CREATE TABLE IF NOT EXISTS search_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            group_id TEXT NOT NULL,
            query_text TEXT NOT NULL,
            results_json TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES lib_users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_search_sessions_user_group ON search_sessions(user_id, group_id);
        CREATE INDEX IF NOT EXISTS idx_search_sessions_expires ON search_sessions(expires_at);

        CREATE TABLE IF NOT EXISTS download_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            group_id TEXT,
            document_id INTEGER NOT NULL,
            pan_asset_id INTEGER,
            share_link_id INTEGER,
            ticket_cost INTEGER NOT NULL DEFAULT 1,
            pan_share_url TEXT,
            pan_extract_code TEXT,
            status TEXT NOT NULL DEFAULT 'success',
            created_at REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES lib_users(id),
            FOREIGN KEY (document_id) REFERENCES documents(id)
        );
        CREATE INDEX IF NOT EXISTS idx_download_logs_user ON download_logs(user_id, created_at);
        """
    )
    conn.commit()
    _ensure_download_log_columns(conn)
    conn.close()
    return db_path


def _ensure_download_log_columns(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(download_logs)")
    cols = {row[1] for row in cur.fetchall()}
    if "doc_code" not in cols:
        cur.execute("ALTER TABLE download_logs ADD COLUMN doc_code TEXT")
    if "doc_title" not in cols:
        cur.execute("ALTER TABLE download_logs ADD COLUMN doc_title TEXT")
    conn.commit()
