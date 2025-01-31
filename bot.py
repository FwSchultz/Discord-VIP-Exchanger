import os
import re
import requests
import aiohttp
import discord
import unicodedata
import logging
import asyncio
from api_client import APIClient
from logging.handlers import RotatingFileHandler
from discord.ext import commands
from discord import Intents
from dotenv import load_dotenv
from database import Database

# Umgebungsvariablen laden
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RCON_API_TOKEN = os.getenv("RCON_API_TOKEN")
RCON_API_URL = os.getenv("RCON_API_URL")
DB_FILE = os.getenv("DB_FILE", "vips.db")
ALLOWED_ROLES = os.getenv("ALLOWED_ROLES", "").split(",")
LOG_FILE = "send_vip.log"
VIP_FILTERS = os.getenv("VIP_FILTERS", "").split(",")
VIP_REGEX = re.compile(os.getenv("VIP_REGEX", r"(\S+)\s(.+)\s(\d{4}-\d{2}-\d{2}T.+)"))
AUTO_SYNC_INTERVAL = int(os.getenv("AUTO_SYNC_INTERVAL", 24))  # In Stunden
VIP_LOG_CHANNEL = int(os.getenv("VIP_LOG_CHANNEL", 0))

# Logger einrichten
logger = logging.getLogger("VIPBotLogger")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8")
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def log_to_file(log_message, level="INFO"):
    """Schreibt Nachrichten mit verschiedenen Log-Levels in die Protokolldatei."""
    if level == "INFO":
        logger.info(log_message)
    elif level == "DEBUG":
        logger.debug(log_message)
    elif level == "ERROR":
        logger.error(log_message)
    else:
        logger.warning(f"Unbekanntes Log-Level: {level}. Nachricht: {log_message}")

# Datenbank-Setup
db = Database(DB_FILE)
db.setup_tables()

# API-Client für Hauptserver und Zielserver erstellen
main_api = APIClient(base_url=RCON_API_URL, token=RCON_API_TOKEN)
target_api = APIClient(base_url=os.getenv("TARGET_API_URL"), token=os.getenv("TARGET_API_TOKEN"))

# Intents für den Bot definieren
intents = Intents.default()
intents.message_content = True

class VIPBot(commands.Bot):
    async def setup_hook(self):
        self.loop.create_task(auto_sync_vips())

# Bot initialisieren
bot = VIPBot(command_prefix="!", intents=intents, reconnect=True)


def check_allowed_roles():
    """Decorator, um zu überprüfen, ob der Benutzer die erforderliche Rolle hat."""
    async def predicate(ctx):
        if not ALLOWED_ROLES:
            return True
        user_roles = [str(role.id) for role in ctx.author.roles]
        return any(role_id in ALLOWED_ROLES for role_id in user_roles)
    return commands.check(predicate)
    
@bot.command()
@check_allowed_roles()
async def restore_vip(ctx, player_id: str):
    """Stellt einen gelöschten VIP aus der Backup-Tabelle wieder her."""
    try:
        restored_vip = db.restore_vip(player_id)
        if restored_vip:
            player_id, description, expiration = restored_vip
            log_to_file(f"🔄 VIP wiederhergestellt: {player_id} - {description} - {expiration}", level="INFO")
            embed = discord.Embed(
                title="✅ VIP wiederhergestellt",
                description=f"Der VIP `{player_id}` wurde erfolgreich wiederhergestellt.",
                color=discord.Color.green()
            )
            embed.add_field(name="📋 Beschreibung", value=description, inline=False)
            embed.add_field(name="⏳ Ablaufdatum", value=expiration, inline=False)
        else:
            embed = discord.Embed(
                title="❌ VIP nicht gefunden",
                description=f"Es gibt keinen gelöschten VIP mit der ID `{player_id}`.",
                color=discord.Color.red()
            )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)
    except Exception as e:
        log_to_file(f"Fehler beim Wiederherstellen des VIPs {player_id}: {str(e)}", level="ERROR")
        embed = discord.Embed(
            title="❌ Fehler",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

@bot.command()
@check_allowed_roles()
async def update_vips(ctx):
    """VIP-Liste aktualisieren und Daten synchronisieren."""
    try:
        headers = {"Authorization": f"Bearer {RCON_API_TOKEN}"}
        response = requests.get(f"{RCON_API_URL}/api/download_vips", headers=headers)

        if response.status_code == 200:
            raw_data = unicodedata.normalize("NFKC", response.content.decode("utf-8", errors="replace").strip())
            lines = raw_data.split("\n")

            # Filter und Regex anwenden
            filtered_lines = [line for line in lines if any(filter_term in line for filter_term in VIP_FILTERS)]
            parsed_vips = [
                re.match(VIP_REGEX, line).groups() for line in filtered_lines if re.match(VIP_REGEX, line)
            ]

            # Tabelle aktualisieren
            db.delete_all("vips")
            db.bulk_insert("vips", parsed_vips)

            await ctx.send("VIP-Datenbank erfolgreich aktualisiert.")
        else:
            log_to_file(f"Fehler beim Abrufen der VIPs: {response.status_code}")
            await ctx.send("Fehler beim Abrufen der VIPs.")
    except Exception as e:
        log_to_file(f"Fehler: {str(e)}")
        await ctx.send(f"Ein Fehler ist aufgetreten: {str(e)}")

async def _update_vips(ctx):
    """Aktualisiert die VIP-Datenbank für Hauptserver und Zielserver."""
    try:
        headers = {"Authorization": f"Bearer {RCON_API_TOKEN}"}
        target_headers = {"Authorization": f"Bearer {os.getenv('TARGET_API_TOKEN')}"}

        # **VIPs vom Hauptserver abrufen**
        response = requests.get(f"{RCON_API_URL}/api/download_vips", headers=headers)
        if response.status_code == 200:
            raw_data = unicodedata.normalize("NFKC", response.content.decode("utf-8", errors="replace").strip())
            lines = raw_data.split("\n")

            filtered_lines = [line for line in lines if any(filter_term in line for filter_term in VIP_FILTERS)]
            parsed_vips = [
                re.match(VIP_REGEX, line).groups() for line in filtered_lines if re.match(VIP_REGEX, line)
            ]

            # **Hauptserver-Tabelle aktualisieren**
            db.delete_all("vips")
            db.bulk_insert("vips", parsed_vips)
            log_to_file("VIP-Datenbank vom Hauptserver wurde aktualisiert.", level="INFO")
        else:
            log_to_file(f"Fehler beim Abrufen der VIPs vom Hauptserver: {response.status_code}", level="ERROR")
            await ctx.send("❌ Fehler beim Abrufen der VIPs vom Hauptserver.")
            return False

        # **VIPs vom Zielserver abrufen (für receiver_vips)**
        target_response = requests.get(f"{os.getenv('TARGET_API_URL')}/api/download_vips", headers=target_headers)
        if target_response.status_code == 200:
            target_raw_data = unicodedata.normalize("NFKC", target_response.content.decode("utf-8", errors="replace").strip())
            target_lines = target_raw_data.split("\n")

            target_filtered_lines = [line for line in target_lines if any(filter_term in line for filter_term in VIP_FILTERS)]
            target_parsed_vips = [
                re.match(VIP_REGEX, line).groups() for line in target_filtered_lines if re.match(VIP_REGEX, line)
            ]

            # **Zielserver-Tabelle aktualisieren**
            db.delete_all("receiver_vips")
            db.bulk_insert("receiver_vips", target_parsed_vips)
            log_to_file("VIP-Datenbank vom Zielserver (receiver_vips) wurde aktualisiert.", level="INFO")
        else:
            log_to_file(f"Fehler beim Abrufen der VIPs vom Zielserver: {target_response.status_code}", level="ERROR")
            await ctx.send("❌ Fehler beim Abrufen der VIPs vom Zielserver.")
            return False

        return True
    except Exception as e:
        log_to_file(f"Fehler beim Aktualisieren der VIP-Daten: {str(e)}", level="ERROR")
        await ctx.send(f"❌ Fehler beim Aktualisieren der VIP-Daten: {str(e)}")
        return False
        
async def auto_sync_vips():
    """Automatische Synchronisation basierend auf dem Intervall in der .env-Datei."""
    await bot.wait_until_ready()  # Warten, bis der Bot bereit ist
    while not bot.is_closed():
        log_to_file(f"⏳ Automatische VIP-Synchronisation gestartet (Intervall: {AUTO_SYNC_INTERVAL} Stunden)...", level="INFO")

        sync_result = await sync_vips_task()
        if sync_result:
            await apply_sync_task()

        # Umrechnung von Stunden in Sekunden (1 Stunde = 3600 Sekunden)
        await asyncio.sleep(AUTO_SYNC_INTERVAL * 3600)

async def sync_vips_task():
    """Führt `sync_vips` aus und gibt zurück, ob Änderungen erkannt wurden."""
    try:
        success = await _update_vips(None)  # Datenbank aktualisieren
        if not success:
            return False

        main_vips = {row[0]: row for row in db.fetch_all("vips")}
        target_vips = {row[0]: row for row in db.fetch_all("receiver_vips")}

        to_add = [main_vips[player_id] for player_id in main_vips if player_id not in target_vips]
        to_remove = [target_vips[player_id] for player_id in target_vips if player_id not in main_vips]

        db.delete_all("sync")
        if to_add:
            db.bulk_insert("sync", to_add)
        if to_remove:
            for player_id, description, expiration in to_remove:
                db.execute_query("INSERT INTO sync (player_id, description, expiration) VALUES (?, ?, ?)", (player_id, description, expiration))

        if to_add or to_remove:
            log_to_file(f"🔄 Automatische VIP-Synchronisation: {len(to_add)} hinzugefügt, {len(to_remove)} entfernt.", level="INFO")
            
            # Falls ein Log-Channel existiert, sende eine Nachricht
            if VIP_LOG_CHANNEL:
                channel = bot.get_channel(VIP_LOG_CHANNEL)
                if channel:
                    embed = discord.Embed(
                        title="🔄 Automatische VIP-Synchronisation",
                        description="Folgende Änderungen wurden erkannt:",
                        color=discord.Color.orange()
                    )
                    embed.add_field(name="✅ Hinzugefügt", value="\n".join([f"🟢 `{player_id}` - {description}" for player_id, description, expiration in to_add]) or "Keine neuen VIPs.", inline=False)
                    embed.add_field(name="❌ Entfernt", value="\n".join([f"🔴 `{player_id}` - {description}" for player_id, description, expiration in to_remove]) or "Keine VIPs entfernt.", inline=False)
                    embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
                    await channel.send(embed=embed)

            return True
        return False

    except Exception as e:
        log_to_file(f"❌ Fehler bei der automatischen VIP-Synchronisation: {str(e)}", level="ERROR")
        return False

async def apply_sync_task():
    """Führt `apply_sync` automatisch aus, wenn Änderungen erkannt wurden."""
    try:
        target_headers = {"Authorization": f"Bearer {os.getenv('TARGET_API_TOKEN')}"}
        add_vip_url = f"{os.getenv('TARGET_API_URL')}/api/add_vip"
        remove_vip_url = f"{os.getenv('TARGET_API_URL')}/api/remove_vip"

        sync_data = db.fetch_all("sync")
        if not sync_data:
            return

        main_vips = {row[0]: row for row in db.fetch_all("vips")}
        target_vips = {row[0]: row for row in db.fetch_all("receiver_vips")}

        to_add = [row for row in sync_data if row[0] in main_vips and row[0] not in target_vips]
        to_remove = [row for row in sync_data if row[0] in target_vips and row[0] not in main_vips]

        added_count = 0
        removed_count = 0

        for player_id, description, expiration in to_add:
            async with aiohttp.ClientSession(headers=target_headers) as session:
                async with session.post(add_vip_url, json={"player_id": player_id, "description": description, "expiration": expiration}) as response:
                    if response.status == 200:
                        added_count += 1
                        log_to_file(f"✅ Automatisch hinzugefügt: {player_id} - {description}")
                    else:
                        error_text = await response.text()
                        log_to_file(f"❌ Fehler beim Hinzufügen von {player_id}: {error_text}", level="ERROR")

        for player_id, _, _ in to_remove:
            async with aiohttp.ClientSession(headers=target_headers) as session:
                async with session.post(remove_vip_url, json={"player_id": player_id}) as response:
                    if response.status == 200:
                        removed_count += 1
                        log_to_file(f"✅ Automatisch entfernt: {player_id}")
                    else:
                        error_text = await response.text()
                        log_to_file(f"❌ Fehler beim Entfernen von {player_id}: {error_text}", level="ERROR")

        db.delete_all("sync")

        if VIP_LOG_CHANNEL:
            channel = bot.get_channel(VIP_LOG_CHANNEL)
            if channel:
                embed = discord.Embed(
                    title="✅ Automatische VIP-Synchronisation abgeschlossen",
                    description=f"`{added_count}` VIPs hinzugefügt, `{removed_count}` VIPs entfernt.",
                    color=discord.Color.green()
                )
                embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
                await channel.send(embed=embed)

    except Exception as e:
        log_to_file(f"❌ Fehler beim automatischen Anwenden der Synchronisation: {str(e)}", level="ERROR")

@bot.command()
@check_allowed_roles()
async def export_vips(ctx):
    """Exportiert die aktuelle VIP-Liste in eine Datei."""
    if not await _update_vips(ctx):
        return

    try:
        output_file = os.getenv("VIP_LIST_FILE", "vip_list.txt")
        vips = db.fetch_all("vips")

        if not vips:
            embed = discord.Embed(
                title="ℹ️ Keine VIP-Daten gefunden",
                description="Die VIP-Datenbank ist leer. Keine Datei zum Exportieren.",
                color=discord.Color.blue()
            )
            embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
            await ctx.send(embed=embed)
            return

        with open(output_file, "w", encoding="utf-8") as file:
            for player_id, description, expiration in vips:
                file.write(f"{player_id} {description} {expiration}\n")

        embed = discord.Embed(
            title="📥 VIP-Liste exportiert",
            description="Die aktuelle VIP-Liste wurde exportiert. Lade sie hier herunter:",
            color=discord.Color.green()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")

        await ctx.send(embed=embed, file=discord.File(output_file))

    except Exception as e:
        log_to_file(f"Fehler beim Exportieren der VIP-Liste: {str(e)}", level="ERROR")

        embed = discord.Embed(
            title="❌ Fehler beim Exportieren",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")

        await ctx.send(embed=embed)

@bot.command()
@check_allowed_roles()
async def sync_vips(ctx):
    """Vergleicht die VIP-Listen und speichert Änderungen in der `sync`-Tabelle, bevor sie an den Zielserver gesendet werden."""
    if not await _update_vips(ctx):
        return

    try:
        main_vips = {row[0]: row for row in db.fetch_all("vips")}
        target_vips = {row[0]: row for row in db.fetch_all("receiver_vips")}

        to_add = []
        to_remove = []
        to_update = []

        for player_id, description, expiration in main_vips.values():
            if player_id not in target_vips:
                to_add.append((player_id, description, expiration))
            elif target_vips[player_id][2] != expiration:
                to_update.append((player_id, description, expiration))

        for player_id in target_vips:
            if player_id not in main_vips:
                to_remove.append(target_vips[player_id])

        # `sync`-Tabelle leeren und Änderungen speichern
        db.delete_all("sync")

        if to_add:
            db.bulk_insert("sync", to_add)
        if to_remove:
            for player_id, description, expiration in to_remove:
                db.execute_query("INSERT INTO sync (player_id, description, expiration) VALUES (?, ?, ?)", (player_id, description, expiration))
        if to_update:
            for player_id, description, expiration in to_update:
                db.execute_query("INSERT INTO sync (player_id, description, expiration) VALUES (?, ?, ?)", (player_id, description, expiration))

        log_to_file(f"{len(to_add)} VIPs zur `sync`-Tabelle hinzugefügt.", level="INFO")
        log_to_file(f"{len(to_remove)} VIPs zur Entfernung in `sync` gespeichert.", level="INFO")
        log_to_file(f"{len(to_update)} VIPs mit aktualisiertem Ablaufdatum gespeichert.", level="INFO")

        # **📢 Log-Channel Update**
        if VIP_LOG_CHANNEL:
            channel = bot.get_channel(VIP_LOG_CHANNEL)
            if channel:
                embed = discord.Embed(
                    title="🔄 VIP-Synchronisation – Änderungen erkannt",
                    description="Diese Änderungen wurden ermittelt. Nutze `!apply_sync`, um sie zu übernehmen.",
                    color=discord.Color.orange()
                )
                if to_add:
                    embed.add_field(
                        name="✅ Hinzugefügt",
                        value="\n".join([f"🟢 `{player_id}` - {description} - {expiration}" for player_id, description, expiration in to_add]) or "Keine neuen VIPs.",
                        inline=False
                    )
                if to_remove:
                    embed.add_field(
                        name="❌ Entfernt",
                        value="\n".join([f"🔴 `{player_id}` - {description}" for player_id, description, expiration in to_remove]) or "Keine VIPs entfernt.",
                        inline=False
                    )
                if to_update:
                    embed.add_field(
                        name="🔄 Ablaufdatum aktualisiert",
                        value="\n".join([f"📝 `{player_id}` - {description} → `{expiration}`" for player_id, description, expiration in to_update]) or "Keine Ablaufdatum-Änderungen.",
                        inline=False
                    )
                embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
                await channel.send(embed=embed)

        await ctx.send("✅ Synchronisation abgeschlossen. Änderungen mit `!apply_sync` übernehmen.")

    except Exception as e:
        log_to_file(f"Fehler bei der Synchronisation: {str(e)}", level="ERROR")
        embed = discord.Embed(
            title="❌ Fehler bei der VIP-Synchronisation",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

@bot.command()
@check_allowed_roles()
async def apply_sync(ctx):
    """Wendet die geplanten VIP-Änderungen an, indem sie an den Zielserver gesendet werden."""
    try:
        target_headers = {"Authorization": f"Bearer {os.getenv('TARGET_API_TOKEN')}"}
        add_vip_url = f"{os.getenv('TARGET_API_URL')}/api/add_vip"
        remove_vip_url = f"{os.getenv('TARGET_API_URL')}/api/remove_vip"

        sync_data = db.fetch_all("sync")
        if not sync_data:
            embed = discord.Embed(
                title="ℹ️ Keine Änderungen in `sync` gespeichert",
                description="Nutze zuerst `!sync_vips`, um Änderungen zu berechnen.",
                color=discord.Color.blue()
            )
            embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
            await ctx.send(embed=embed)
            return

        main_vips = {row[0]: row for row in db.fetch_all("vips")}
        target_vips = {row[0]: row for row in db.fetch_all("receiver_vips")}

        to_add = [row for row in sync_data if row[0] in main_vips and row[0] not in target_vips]
        to_remove = [row for row in sync_data if row[0] in target_vips and row[0] not in main_vips]

        added_count = 0
        removed_count = 0

        for player_id, description, expiration in to_add:
            async with aiohttp.ClientSession(headers=target_headers) as session:
                async with session.post(add_vip_url, json={"player_id": player_id, "description": description, "expiration": expiration}) as response:
                    if response.status == 200:
                        added_count += 1
                        log_to_file(f"✅ VIP hinzugefügt: {player_id} - {description} - {expiration}")
                    else:
                        error_text = await response.text()
                        log_to_file(f"❌ Fehler beim Hinzufügen von VIP {player_id}: {error_text}", level="ERROR")

        for player_id, _, _ in to_remove:
            async with aiohttp.ClientSession(headers=target_headers) as session:
                async with session.post(remove_vip_url, json={"player_id": player_id}) as response:
                    if response.status == 200:
                        removed_count += 1
                        log_to_file(f"✅ VIP entfernt: {player_id}")
                    else:
                        error_text = await response.text()
                        log_to_file(f"❌ Fehler beim Entfernen von VIP {player_id}: {error_text}", level="ERROR")

        db.delete_all("sync")

        embed = discord.Embed(
            title="✅ VIP-Änderungen übernommen",
            description=f"Es wurden `{added_count}` VIPs hinzugefügt und `{removed_count}` VIPs entfernt.",
            color=discord.Color.green()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

    except Exception as e:
        log_to_file(f"Fehler beim Anwenden der Synchronisation: {str(e)}", level="ERROR")
        embed = discord.Embed(
            title="❌ Fehler bei der Synchronisation",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

@bot.command()
@check_allowed_roles()
async def show_sync(ctx):
    """Zeigt die geplanten VIP-Änderungen in der `sync`-Tabelle an."""
    try:
        sync_data = db.fetch_all("sync")
        if not sync_data:
            embed = discord.Embed(
                title="ℹ️ Keine geplanten Änderungen",
                description="Die `sync`-Tabelle ist leer. Nutze `!sync_vips`, um Änderungen zu berechnen.",
                color=discord.Color.blue()
            )
            embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="📋 Geplante VIP-Änderungen",
            description="Diese VIPs sind in der `sync`-Tabelle gespeichert.",
            color=discord.Color.blue()
        )

        for player_id, description, expiration in sync_data:
            embed.add_field(
                name=f"🆔 `{player_id}`",
                value=f"📋 **Beschreibung**: `{description}`\n⏳ **Ablaufdatum**: `{expiration}`",
                inline=False
            )

        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

    except Exception as e:
        log_to_file(f"Fehler beim Abrufen von `sync`: {str(e)}", level="ERROR")
        embed = discord.Embed(
            title="❌ Fehler beim Abrufen der `sync`-Daten",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

@bot.command()
@check_allowed_roles()
async def clear_vips(ctx):
    """Löscht alle VIP-Daten und speichert sie vor dem Löschen in der Backup-Tabelle."""
    try:
        vips = db.fetch_all("vips")
        for player_id, description, expiration in vips:
            db.backup_vip(player_id, description, expiration)
        db.delete_all("vips")
        db.delete_all("receiver_vips")
        db.delete_all("sync")
        log_to_file("Alle VIP-Daten wurden gelöscht und gesichert.", level="INFO")
        embed = discord.Embed(
            title="🗑 VIP-Datenbank geleert",
            description="Alle VIP-Daten wurden gelöscht und ins Backup verschoben.",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)
    except Exception as e:
        log_to_file(f"Fehler beim Löschen der VIP-Daten: {str(e)}", level="ERROR")
        embed = discord.Embed(
            title="❌ Fehler beim Löschen der VIP-Daten",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

@bot.command()
@check_allowed_roles()
async def check_vip(ctx, name: str):
    """Sucht nach einem VIP in der Datenbank basierend auf einem Teilstring des Namens."""
    try:
        query = "SELECT * FROM vips WHERE description LIKE ?"
        results = db.execute_query(query, (f"%{name}%",))

        if results:
            embed = discord.Embed(
                title="🔍 VIP-Suche",
                description=f"Ergebnisse für `{name}`:",
                color=discord.Color.blue()
            )
            for player_id, description, expiration in results:
                embed.add_field(
                    name=f"🆔 `{player_id}`",
                    value=f"📋 **Beschreibung**: `{description}`\n⏳ **Ablaufdatum**: `{expiration}`",
                    inline=False
                )
        else:
            embed = discord.Embed(
                title="❌ Kein VIP gefunden",
                description=f"Kein VIP enthält `{name}` in der Datenbank.",
                color=discord.Color.red()
            )

        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
        await ctx.send(embed=embed)

    except Exception as e:
        log_to_file(f"Fehler beim Überprüfen von VIPs mit Name `{name}`: {str(e)}", level="ERROR")

        embed = discord.Embed(
            title="❌ Fehler bei der VIP-Suche",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")

        await ctx.send(embed=embed)
        
@bot.command()
@check_allowed_roles()
async def show_backup(ctx):
    """Exportiert das VIP-Backup als Datei."""
    try:
        backup_vips = db.fetch_all("vip_backup")

        if not backup_vips:
            embed = discord.Embed(
                title="ℹ️ Kein VIP-Backup gefunden",
                description="Es wurden keine gelöschten VIPs im Backup gespeichert.",
                color=discord.Color.blue()
            )
            embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")
            await ctx.send(embed=embed)
            return

        backup_file = "vip_backup.txt"

        with open(backup_file, "w", encoding="utf-8") as file:
            for player_id, description, expiration, deleted_at in backup_vips:
                file.write(f"{player_id} {description} {expiration} {deleted_at}\n")

        embed = discord.Embed(
            title="📥 VIP-Backup exportiert",
            description="Die gelöschten VIPs wurden exportiert. Lade die Datei hier herunter:",
            color=discord.Color.green()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")

        await ctx.send(embed=embed, file=discord.File(backup_file))

    except Exception as e:
        log_to_file(f"Fehler beim Exportieren des VIP-Backups: {str(e)}", level="ERROR")

        embed = discord.Embed(
            title="❌ Fehler beim Exportieren des VIP-Backups",
            description=f"Ein Fehler ist aufgetreten: `{str(e)}`",
            color=discord.Color.red()
        )
        embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")

        await ctx.send(embed=embed)

@bot.command()
@check_allowed_roles()
async def vipbot(ctx):
    """Zeigt eine Übersicht aller verfügbaren Befehle des VIP-Bots."""
    embed = discord.Embed(
        title="🤖 VIP-Bot Befehle",
        description="Hier sind alle verfügbaren Befehle für den VIP-Bot:",
        color=discord.Color.blue()
    )

    # Synchronisation & Verwaltung
    embed.add_field(name="🔄 `!sync_vips`", value="Berechnet Änderungen und speichert sie in `sync`.", inline=False)
    embed.add_field(name="📋 `!show_sync`", value="Zeigt die geplanten VIP-Änderungen aus `sync` an.", inline=False)
    embed.add_field(name="✅ `!apply_sync`", value="Wendet die geplanten Änderungen aus `sync` an und sendet sie an den Zielserver.", inline=False)
    
    # VIP-Datenbank
    embed.add_field(name="📥 `!export_vips`", value="Exportiert die aktuelle VIP-Liste und sendet sie als Datei.", inline=False)
    embed.add_field(name="🗑 `!clear_vips`", value="Speichert VIPs im Backup und löscht sie aus `vips`, `receiver_vips` und `sync`.", inline=False)
    embed.add_field(name="🔍 `!check_vip <name>`", value="Überprüft, ob ein VIP mit einem bestimmten Namen in der Datenbank existiert (auch Teilstrings).", inline=False)
    
    # Backup & Wiederherstellung
    embed.add_field(name="🛡 `!show_backup`", value="Zeigt alle VIPs im Backup an.", inline=False)
    embed.add_field(name="♻️ `!restore_vip <player_id>`", value="Stellt einen gelöschten VIP aus dem Backup wieder her.", inline=False)

    embed.add_field(name="ℹ️ `!vipbot`", value="Zeigt diese Befehlsübersicht an.", inline=False)
    embed.add_field(
        name="ℹ️ `!?????`", 
        value="Kommende Features-Ideen an [Fw.Schultz](https://discord.com/users/275297833970565121).", 
        inline=False
    )

    embed.set_footer(text="VIP-Bot | Erstellt von Fw.Schultz")

    await ctx.send(embed=embed)


# Bot starten
bot.run(DISCORD_BOT_TOKEN)
