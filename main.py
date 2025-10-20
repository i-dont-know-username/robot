import os
import json
from datetime import datetime
import discord
from discord.ext import commands
from discord import app_commands
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv
from supabase import create_client, Client  # New import

load_dotenv()

# Bot setup (unchanged)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Config (removed MOD_CHANNEL_ID; now from DB)
TOKEN = os.getenv('DISCORD_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Colors & FastAPI (unchanged)
EMBED_COLOR = 0x00A2FF
app = FastAPI()

@app.get("/keepalive")
async def keepalive():
    return {"status": "alive", "bot": "RoBot running"}

# DB setup (added settings table init)
def init_db():
    if not supabase:
        print("Warning: Supabase not configured—falling back to in-memory (data lost on restart).")
        return
    # Create settings table if needed
    try:
        supabase.table('settings').insert({'key': 'mod_channel_id', 'value': 0}).execute()
        print("Supabase connected with settings!")
    except Exception as e:
        print(f"DB Error: {e}")

init_db()

# Helper: Get setting from DB
async def get_setting(key: str):
    if not supabase:
        return 0
    try:
        response = supabase.table('settings').select('value').eq('key', key).execute()
        return response.data[0]['value'] if response.data else 0
    except:
        return 0

# Helper: Set setting in DB
async def set_setting(key: str, value: int):
    if not supabase:
        return False
    try:
        supabase.table('settings').upsert({'key': key, 'value': value}).execute()
        return True
    except:
        return False

# Helper: Load JSON field (unchanged)
def load_json(field):
    try:
        return json.loads(field) if field else []
    except:
        return []

# Helper: Save JSON field (unchanged)
def save_json(data):
    return json.dumps(data)

# Embed helper (unchanged)
def create_embed(title, description="", fields=None, color=EMBED_COLOR):
    embed = discord.Embed(title=title, description=description, color=color)
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    embed.timestamp = datetime.utcnow()
    embed.set_footer(text="RoBot - Roblox Dev Marketplace")
    return embed

@bot.event
async def on_ready():
    print(f'{bot.user} is online!')
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(e)

# New: /setmodchannel command (admin-only)
@bot.tree.command(name="setmodchannel", description="Set the mod channel for reports (Admin/Owner only)")
@app_commands.describe(channel="The channel to receive reports")
async def setmodchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    # Check permissions
    if not interaction.user.guild_permissions.administrator and interaction.user != interaction.guild.owner:
        await interaction.response.send_message(embed=create_embed("Access Denied", "Only admins/owners can set the mod channel.", color=0xFF0000), ephemeral=True)
        return
    
    success = await set_setting('mod_channel_id', channel.id)
    if success:
        embed = create_embed("Mod Channel Set!", f"Reports will now go to {channel.mention}.", color=0x00FF00)
    else:
        embed = create_embed("Error", "Failed to save setting—check DB connection.", color=0xFF0000)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# /register (unchanged from last)
@bot.tree.command(name="register", description="Register your developer profile")
@app_commands.describe(
    experience="Years of Roblox dev experience (0-50)",
    specializations="Comma-separated list, e.g., UI/UX,Scripting",
    payment_methods="Comma-separated list, e.g., PayPal,Robux",
    rate="Your rate (USD per hour/project)",
    bio="Short bio (max 500 chars)"
)
async def register(interaction: discord.Interaction, experience: int, specializations: str, payment_methods: str, rate: float, bio: str):
    if len(bio) > 500:
        await interaction.response.send_message(embed=create_embed("Error", "Bio too long (max 500 chars).", color=0xFF0000), ephemeral=True)
        return
    
    specs = [s.strip() for s in specializations.split(',') if s.strip()]
    payments = [p.strip() for p in payment_methods.split(',') if p.strip()]
    
    if not supabase:
        await interaction.response.send_message(embed=create_embed("Error", "Database not ready—try again later."), ephemeral=True)
        return
    
    data = {
        'user_id': interaction.user.id,
        'experience': experience,
        'specializations': save_json(specs),
        'payment_methods': save_json(payments),
        'rate': rate,
        'bio': bio
    }
    
    try:
        supabase.table('users').upsert(data).execute()  # Upsert for update/insert
        embed = create_embed("Profile Registered!", f"**Experience:** {experience} years\n**Rate:** ${rate}\n**Specializations:** {', '.join(specs) or 'None'}\n**Payments:** {', '.join(payments) or 'None'}\n**Bio:** {bio or 'None'}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed("Error", f"Failed to save: {str(e)}"), ephemeral=True)

# /profile (unchanged)
@bot.tree.command(name="profile", description="View a user profile")
@app_commands.describe(user="The user to view (optional: defaults to you)")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    if not supabase:
        await interaction.response.send_message(embed=create_embed("Error", "Database not ready."), ephemeral=True)
        return
    
    try:
        response = supabase.table('users').select('*').eq('user_id', target.id).execute()
        row = response.data[0] if response.data else None
        
        if not row:
            await interaction.response.send_message(embed=create_embed("No Profile", f"{target.mention} has no registered profile."), ephemeral=True)
            return
        
        specs = load_json(row['specializations'])
        payments = load_json(row['payment_methods'])
        embed = create_embed(
            f"{target.display_name}'s Profile",
            row['bio'] or "No bio.",
            [
                ("Experience", f"{row['experience']} years", True),
                ("Rate", f"${row['rate']}", True),
                ("Specializations", ', '.join(specs) or 'None', False),
                ("Payment Methods", ', '.join(payments) or 'None', False)
            ]
        )
        embed.set_thumbnail(url=target.avatar.url if target.avatar else None)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed("Error", f"Failed to fetch: {str(e)}"), ephemeral=True)

# /search (unchanged)
@bot.tree.command(name="search", description="Search for developers matching your criteria")
@app_commands.describe(
    min_experience="Min years of experience",
    max_budget="Max rate you can pay (USD)",
    specializations="Required specializations (comma-separated, optional)",
    payment_methods="Accepted payment methods (comma-separated, optional)"
)
async def search(interaction: discord.Interaction, min_experience: int = 0, max_budget: float = 999, specializations: str = "", payment_methods: str = ""):
    req_specs = [s.strip() for s in specializations.split(',') if s.strip()] if specializations else []
    req_payments = [p.strip() for p in payment_methods.split(',') if p.strip()] if payment_methods else []
    
    if not supabase:
        await interaction.response.send_message(embed=create_embed("Error", "Database not ready."), ephemeral=True)
        return
    
    try:
        response = supabase.table('users').select('*').gte('experience', min_experience).lte('rate', max_budget).execute()
        rows = response.data
        
        matches = []
        for row in rows:
            specs = load_json(row['specializations'])
            payments = load_json(row['payment_methods'])
            spec_match = not req_specs or any(any(req.lower() in spec.lower() for req in req_specs) for spec in specs)
            pay_match = not req_payments or any(any(req.lower() in pay.lower() for req in req_payments) for pay in payments)
            if spec_match and pay_match:
                user = bot.get_user(row['user_id'])
                matches.append({
                    'user': user or f"ID: {row['user_id']}",
                    'exp': row['experience'],
                    'rate': row['rate'],
                    'specs': specs,
                    'bio': row['bio'][:100] + '...' if len(row['bio']) > 100 else row['bio']
                })
        
        if not matches:
            await interaction.response.send_message(embed=create_embed("No Matches", f"No devs found for your criteria. Try broadening filters!"), ephemeral=False)
            return
        
        embed = create_embed(f"Search Results ({len(matches)} matches)", "Here are top matches:")
        for i, match in enumerate(matches[:5], 1):
            user_mention = match['user'].mention if hasattr(match['user'], 'mention') else match['user']
            embed.add_field(
                name=f"{i}. {user_mention}",
                value=f"**Exp:** {match['exp']}y | **Rate:** ${match['rate']}\n**Specs:** {', '.join(match['specs'][:2])}\n**Bio:** {match['bio']}",
                inline=False
            )
        if len(matches) > 5:
            embed.set_footer(text=f"Showing 1-5 of {len(matches)}. Use /profile for details.")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed("Error", f"Search failed: {str(e)}"), ephemeral=True)

# /report (updated to fetch mod channel from DB)
@bot.tree.command(name="report", description="Report a user for review")
@app_commands.describe(user="The user to report", reason="Reason for report (e.g., scam, spam)")
async def report(interaction: discord.Interaction, user: discord.Member, reason: str):
    if len(reason) > 1000:
        await interaction.response.send_message(embed=create_embed("Error", "Reason too long (max 1000 chars).", color=0xFF0000), ephemeral=True)
        return
    
    if not supabase:
        await interaction.response.send_message(embed=create_embed("Error", "Database not ready."), ephemeral=True)
        return
    
    try:
        data = {
            'reporter_id': interaction.user.id,
            'reported_id': user.id,
            'reason': reason
        }
        supabase.table('reports').insert(data).execute()
        
        mod_channel_id = await get_setting('mod_channel_id')
        mod_channel = bot.get_channel(mod_channel_id)
        if mod_channel:
            report_embed = create_embed(
                "New Report Received",
                f"**Reporter:** {interaction.user.mention} (ID: {interaction.user.id})\n**Reported:** {user.mention} (ID: {user.id})\n**Reason:** {reason}",
                color=0xFF9900
            )
            await mod_channel.send(embed=report_embed)
        else:
            print(f"Warning: Mod channel not set (ID: {mod_channel_id}). Set with /setmodchannel.")
        
        await interaction.response.send_message(embed=create_embed("Report Submitted", f"Thanks for reporting {user.mention}. Mods will review it soon."), ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed("Error", f"Report failed: {str(e)}"), ephemeral=True)

# Run (unchanged)
if __name__ == "__main__":
    if os.getenv('RENDER'):
        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('PORT', 8000)))
    else:
        bot.run(TOKEN)
