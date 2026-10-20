"""Discord Orb Quest announcement bot for Railway."""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("orb-quest-bot")

API_URL = os.getenv("QUEST_API_URL", "https://api.discordquest.com/api/quests")
POLL_SECONDS = max(60, int(os.getenv("POLL_SECONDS", "300")))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "data/config.json"))
SEEN_PATH = Path(os.getenv("SEEN_PATH", "data/seen.json"))
GUILDS = [int(x) for x in os.getenv("DISCORD_GUILD_IDS", "").split(",") if x.strip().isdigit()]

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
http_session = None
config: dict[str, Any] = {"channels": {}, "roles": {}, "owner_user_id": None}
seen_ids: set[str] = set()


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def values(obj: Any):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key, value
            yield from values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from values(value)


def first_field(item: dict, names: tuple[str, ...], default="") -> str:
    wanted = {n.lower() for n in names}
    for key, value in values(item):
        if key.lower() in wanted and isinstance(value, (str, int, float)):
            return str(value)
    return default


def quest_id(q: dict) -> str:
    return first_field(q, ("id", "quest_id", "questId", "uuid", "slug"))


def is_orb_quest(q: dict) -> bool:
    for key, value in values(q):
        if "reward" in key.lower() or key.lower() in {"currency", "currencies"}:
            if isinstance(value, (str, int, float)) and re.search(r"\borbs?\b", str(value), re.I):
                return True
            if isinstance(value, dict) and any(re.search(r"\borbs?\b", str(k) + " " + str(v), re.I) for k, v in value.items()):
                return True
    return False


def is_us_only(q: dict) -> bool:
    # Only classify as US-only when the data explicitly marks a US-only availability.
    for key, value in values(q):
        if any(token in key.lower() for token in ("region", "country", "availability", "locale")):
            strings = [str(value)]
            if isinstance(value, (list, dict)):
                strings += [str(x) for pair in values(value) for x in pair]
            joined = " ".join(strings).lower()
            if ("us" in joined or "usa" in joined or "united states" in joined or "🇺🇸" in joined) and not any(x in joined for x in ("global", "worldwide", "all regions")):
                return True
    return False


def quest_link(q: dict) -> str:
    direct = first_field(q, ("url", "link", "quest_url", "questUrl"))
    return direct if direct.startswith("https://") else "https://discord.com/quest-home"


def quest_embed(q: dict) -> discord.Embed:
    title = first_field(q, ("title", "name"), "New Orb Quest")
    desc = first_field(q, ("description", "summary"))
    reward = first_field(q, ("reward", "rewards", "reward_amount", "rewardAmount"), "Orbs")
    end = first_field(q, ("end_at", "endAt", "ends_at", "expires_at", "expiration"))
    embed = discord.Embed(title=title[:256], url=quest_link(q), description=desc[:4000] or None, color=0x5865F2)
    embed.add_field(name="Reward", value=reward[:1024], inline=True)
    if end:
        embed.add_field(name="Ends", value=end[:1024], inline=True)
    embed.set_footer(text="Quest details and availability can vary by account and region.")
    return embed


async def fetch_quests() -> list[dict]:
    async with http_session.get(API_URL, timeout=25) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    for key in ("quests", "data", "results", "items"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return [x for x in data[key] if isinstance(x, dict)]
    raise ValueError("Quest API response did not contain a quest list; inspect Railway logs and update the parser if needed.")


async def poll_loop():
    await client.wait_until_ready()
    global seen_ids
    while not client.is_closed():
        try:
            quests = [q for q in await fetch_quests() if is_orb_quest(q) and quest_id(q)]
            current = {quest_id(q) for q in quests}
            if not seen_ids:
                # First run establishes a baseline so old campaigns are not announced as new.
                seen_ids = current
                save_json(SEEN_PATH, sorted(seen_ids))
                log.info("Baseline loaded with %d active Orb Quest(s).", len(seen_ids))
            else:
                for q in quests:
                    qid = quest_id(q)
                    if qid in seen_ids:
                        continue
                    seen_ids.add(qid)
                    if is_us_only(q):
                        # Discord cannot send messages into this ChatGPT conversation. Railway logs
                        # are the available in-chat equivalent until an owner DM is configured.
                        log.info("US Orb Quest found (kept out of Discord channel): %s | %s", first_field(q, ("title", "name"), qid), quest_link(q))
                        continue
                    for guild_id, channel_id in config.get("channels", {}).items():
                        channel = client.get_channel(int(channel_id))
                        if channel is None:
                            try:
                                channel = await client.fetch_channel(int(channel_id))
                            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                                log.exception("Cannot access configured channel %s", channel_id)
                                continue
                        role_id = config.get("roles", {}).get(str(guild_id))
                        content = f"<@&{role_id}>" if role_id else None
                        try:
                            await channel.send(content=content, embed=quest_embed(q), allowed_mentions=discord.AllowedMentions(roles=True))
                        except discord.HTTPException:
                            log.exception("Failed to post quest %s to channel %s", qid, channel_id)
                save_json(SEEN_PATH, sorted(seen_ids))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Quest poll failed; retrying after the polling interval.")
        await asyncio.sleep(POLL_SECONDS)


def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return bool(interaction.guild and interaction.user.guild_permissions.manage_guild)
    return app_commands.check(predicate)


@tree.command(name="setchannel", description="设置 Orb Quest 通知频道")
@app_commands.describe(channel="接收新 Orb Quest 通知的频道")
@admin_only()
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    config.setdefault("channels", {})[str(interaction.guild_id)] = channel.id
    save_json(CONFIG_PATH, config)
    await interaction.response.send_message(f"新 Orb Quest 将发送到 {channel.mention}。美国地区任务不会发到 Discord 频道。", ephemeral=True)


@tree.command(name="setnotifyrole", description="设置可选的 Orb Quest 通知角色")
@app_commands.describe(role="新任务发布时要 @ 的角色；留空则关闭角色提醒")
@admin_only()
async def setnotifyrole(interaction: discord.Interaction, role: discord.Role | None = None):
    roles = config.setdefault("roles", {})
    if role is None:
        roles.pop(str(interaction.guild_id), None)
        msg = "已关闭角色 @ 提醒。"
    else:
        roles[str(interaction.guild_id)] = role.id
        msg = f"新任务会提醒 {role.mention}。"
    save_json(CONFIG_PATH, config)
    await interaction.response.send_message(msg, ephemeral=True)


@tree.command(name="queststatus", description="查看 Orb Quest bot 的频道与监测状态")
@admin_only()
async def queststatus(interaction: discord.Interaction):
    channel_id = config.get("channels", {}).get(str(interaction.guild_id))
    channel_text = f"<#{channel_id}>" if channel_id else "尚未设置（使用 /setchannel）"
    role_id = config.get("roles", {}).get(str(interaction.guild_id))
    role_text = f"<@&{role_id}>" if role_id else "未启用"
    await interaction.response.send_message(f"通知频道：{channel_text}\n通知角色：{role_text}\n轮询间隔：{POLL_SECONDS} 秒", ephemeral=True)


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        message = "此指令仅限拥有管理服务器权限的成员使用。"
    else:
        log.exception("Slash command failed", exc_info=error)
        message = "指令执行失败，请查看 Railway 日志。"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@client.event
async def on_ready():
    log.info("Logged in as %s (%s)", client.user, client.user.id)
    # The application ID is populated only after the client has logged in.
    # Syncing commands before client.start() raises discord.errors.MissingApplicationID.
    if getattr(client, "_orb_commands_synced", False):
        return
    try:
        if GUILDS:
            for guild_id in GUILDS:
                guild = discord.Object(id=guild_id)
                tree.copy_global_to(guild=guild)
                await tree.sync(guild=guild)
        else:
            await tree.sync()
        client._orb_commands_synced = True
        log.info("Slash commands synced.")
    except Exception:
        log.exception("Failed to sync slash commands.")


async def main():
    global http_session, config, seen_ids
    import aiohttp

    config = load_json(CONFIG_PATH, {"channels": {}, "roles": {}, "owner_user_id": None})
    seen_ids = set(load_json(SEEN_PATH, []))
    http_session = aiohttp.ClientSession()
    async with client:
        task = asyncio.create_task(poll_loop())
        try:
            await client.start(os.environ["DISCORD_TOKEN"])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await http_session.close()


if __name__ == "__main__":
    asyncio.run(main())
