import sqlite3
import os
import datetime

class Database:
    def __init__(self, db_file):
        self.db_file = db_file
        self.conn = sqlite3.connect(self.db_file)
        self.cursor = self.conn.cursor()

    def setup_tables(self):
        """Erstellt die notwendigen Tabellen, falls sie nicht existieren."""
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS vips (
            player_id TEXT PRIMARY KEY,
            description TEXT,
            expiration TEXT
        )
        """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS receiver_vips (
            player_id TEXT PRIMARY KEY,
            description TEXT,
            expiration TEXT
        )
        """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync (
            player_id TEXT PRIMARY KEY,
            description TEXT,
            expiration TEXT
        )
        """)
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS vip_backup (
            player_id TEXT PRIMARY KEY,
            description TEXT,
            expiration TEXT,
            deleted_at TEXT
        )
        """)
        self.conn.commit()

    def execute_query(self, query, params=()):
        """Führt eine Abfrage aus und gibt das Ergebnis zurück."""
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.fetchall()

    def bulk_insert(self, table, data):
        """Fügt mehrere Einträge in eine Tabelle ein."""
        self.cursor.executemany(f"""
        INSERT OR REPLACE INTO {table} (player_id, description, expiration)
        VALUES (?, ?, ?)
        """, data)
        self.conn.commit()

    def delete_all(self, table):
        """Löscht alle Einträge aus einer Tabelle."""
        self.cursor.execute(f"DELETE FROM {table}")
        self.conn.commit()

    def fetch_all(self, table):
        """Gibt alle Daten aus einer Tabelle zurück."""
        self.cursor.execute(f"SELECT * FROM {table}")
        return self.cursor.fetchall()

    def backup_vip(self, player_id, description, expiration):
        """Speichert gelöschte VIPs in der Backup-Tabelle und ersetzt vorhandene Einträge."""
        timestamp = datetime.datetime.utcnow().isoformat()
        self.execute_query("""
        INSERT OR REPLACE INTO vip_backup (player_id, description, expiration, deleted_at)
        VALUES (?, ?, ?, ?)
        """, (player_id, description, expiration, timestamp))

    def restore_vip(self, player_id):
        """Stellt einen gelöschten VIP aus dem Backup wieder her."""
        result = self.execute_query("SELECT * FROM vip_backup WHERE player_id = ?", (player_id,))
        if not result:
            return None
        
        player_id, description, expiration, deleted_at = result[0]
        self.execute_query("INSERT INTO vips (player_id, description, expiration) VALUES (?, ?, ?)", (player_id, description, expiration))
        self.execute_query("DELETE FROM vip_backup WHERE player_id = ?", (player_id,))
        return (player_id, description, expiration)

    def close(self):
        """Schließt die Verbindung zur Datenbank."""
        self.conn.close()
