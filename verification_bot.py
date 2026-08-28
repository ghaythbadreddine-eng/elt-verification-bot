"""
Discord Verification Bot
=======================================
How it works:
1) When a member joins the "Waiting for Move" voice channel:
   - The bot posts an embed in the "VERIFICATION" text channel, pinging @everyone,
     with a Verify button and a Reject button. Only Staff/Admin can actually click the buttons.
2) When a Staff/Admin member clicks Verify:
   - The "Verified" role and "Member" role (or any other roles you set) get added.
   - If the member already has the "Unverified" role, it gets removed.
   - An optional welcome message is sent in the welcome channel (if you set one up).

Requirements:
    pip install discord.py

Before running:
    - Enable SERVER MEMBERS INTENT for your bot in the Discord Developer Portal.
    - Put your token in place of "PUT_YOUR_BOT_TOKEN_HERE" below (from Developer Portal > your bot > Bot > Token).
"""

import os

import discord
from discord.ext import commands

# =========================== CONFIG ===========================
# The token is read from an environment variable instead of being written here,
# so it's safe to upload this file. Set DISCORD_TOKEN in Railway's "Variables" tab.
TOKEN = os.environ.get("DISCORD_TOKEN")

GUILD_ID = 1410440666747633707  # ELT server ID

# Channels
VERIFICATION_CHANNEL_ID = 1542531178526146670  # channel where verify requests get posted
WELCOME_CHANNEL_ID = None                        # welcome channel (optional - leave as None if you don't want a welcome message)
WAITING_VC_ID = 1513904254535073883              # the "Waiting for Move" voice channel

# Roles
UNVERIFIED_ROLE_ID = 1513904174079934657  # removed from the member at verify time if they have it (not given automatically anymore)
VERIFIED_ROLE_ID = 1513904156350353511    # given after verification
STAFF_ROLE_ID = 1513904127837736992       # pinged in the notification, can click the buttons
ADMIN_ROLE_ID = 1513904120803889243       # pinged in the notification, can click the buttons

EXTRA_ROLES_ON_VERIFY = [1513904151309058159]  # MEMBER role - given alongside Verified
# ================================================================

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True  # needed to detect members joining the voice channel

bot = commands.Bot(command_prefix="!", intents=intents)

# Tracks members we've already notified, so we don't repeat it if they leave and rejoin the channel
# (resets automatically if the bot restarts)
pending_verification = set()


def is_staff_or_admin(member: discord.Member) -> bool:
    role_ids = {role.id for role in member.roles}
    return (
        STAFF_ROLE_ID in role_ids
        or ADMIN_ROLE_ID in role_ids
        or member.guild_permissions.administrator
    )


class VerifyView(discord.ui.View):
    """Verify/Reject buttons. timeout=None so they keep working even after a bot restart."""

    def __init__(self, member_id: int):
        super().__init__(timeout=None)
        self.member_id = member_id
        self.children[0].custom_id = f"verify_accept_{member_id}"
        self.children[1].custom_id = f"verify_reject_{member_id}"

    @discord.ui.button(label="✅ Verify", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("You don't have permission to verify members.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.member_id)
        if member is None:
            return await interaction.response.send_message("That member isn't in the server anymore (they may have left).", ephemeral=True)

        unverified_role = guild.get_role(UNVERIFIED_ROLE_ID)
        verified_role = guild.get_role(VERIFIED_ROLE_ID)

        try:
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason=f"Verified by {interaction.user}")
            if verified_role:
                await member.add_roles(verified_role, reason=f"Verified by {interaction.user}")
            for rid in EXTRA_ROLES_ON_VERIFY:
                r = guild.get_role(rid)
                if r:
                    await member.add_roles(r, reason="Extra role after verification")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "The bot doesn't have enough permission to change roles (make sure the bot's role is above the roles it manages).",
                ephemeral=True,
            )

        pending_verification.discard(self.member_id)

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.set_footer(text=f"Verified ✅ by {interaction.user}")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

        if WELCOME_CHANNEL_ID:
            welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
            if welcome_channel:
                await welcome_channel.send(f"🎉 Welcome {member.mention}, you're verified — glad to have you in the server!")

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff_or_admin(interaction.user):
            return await interaction.response.send_message("You don't have permission.", ephemeral=True)

        pending_verification.discard(self.member_id)

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.set_footer(text=f"Rejected ❌ by {interaction.user}")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """Notifies Staff and Admin when a member joins the 'Waiting for Move' voice channel."""
    if member.guild.id != GUILD_ID:
        return

    just_joined_waiting = (
        after.channel is not None
        and after.channel.id == WAITING_VC_ID
        and (before.channel is None or before.channel.id != WAITING_VC_ID)
    )
    if not just_joined_waiting:
        return

    verified_role = member.guild.get_role(VERIFIED_ROLE_ID)
    if verified_role and verified_role in member.roles:
        return  # already verified
    if member.id in pending_verification:
        return  # already has a pending notification

    verification_channel = member.guild.get_channel(VERIFICATION_CHANNEL_ID)
    if verification_channel is None:
        print("⚠️ Couldn't find the verification channel — check VERIFICATION_CHANNEL_ID")
        return

    embed = discord.Embed(
        title="Member awaiting verification",
        description=(
            f"Member: {member.mention}\n"
            f"ID: `{member.id}`\n"
            f"Account created: {discord.utils.format_dt(member.created_at, 'R')}\n"
            f"Joined voice channel: **{after.channel.name}**"
        ),
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Click Verify to let this member in")

    view = VerifyView(member.id)
    pending_verification.add(member.id)
    await verification_channel.send(
        content="@everyone A member in the voice channel needs verification",
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(everyone=True),
    )


if not TOKEN:
    raise SystemExit("DISCORD_TOKEN is not set. Add it in Railway's Variables tab, then redeploy.")

bot.run(TOKEN)
