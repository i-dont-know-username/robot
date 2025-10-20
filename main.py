import os
import json
import sqlite3
from datetime import datetime
import discord
from discord.ext import commands
from discord import app_commands
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv

load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Config
TOKEN = os.getenv('DISCORD_TOKEN')
MOD_CHANNEL_ID = int(os.getenv('MOD_CHANNEL_ID', 0))
DB_PATH = 'data/robot.db'  # Render mounts /app/data

# Colors for professional embeds (Roblox blue theme)
EMBED_COLOR = 0x00A2FF

# FastAPI for keepalive (Render free tier)
app = FastAPI()

@app.get("/keepalive")
async def keepalive():
    return {"status": "alive", "bot": "RoBot running"}

# Database setup
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Users table (dev profiles)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            experience INTEGER DEFAULT 0,
            specializations TEXT DEFAULT '[]',  -- JSON list
            payment_methods TEXT DEFAULT '[]',  -- JSON list
            rate REAL DEFAULT 0.0,  -- Hourly/project rate
            bio TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Reports table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reported_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    return sqlite3.connect(DB_PATH)

# Helper: Load JSON field
def load_json(field):
    try:
        return json.loads(field) if field else []
    except:
        return []

# Helper: Save JSON field
def save_json(data):
    return json.dumps(data)

# Embed helper
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

# /register command (for devs)
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
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, experience, specializations, payment_methods, rate, bio)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (interaction.user.id, experience, save_json(specs), save_json(payments), rate, bio))
    conn.commit()
    conn.close()
    
    embed = create_embed("Profile Registered!", f"**Experience:** {experience} years\n**Rate:** ${rate}\n**Specializations:** {', '.join(specs) or 'None'}\n**Payments:** {', '.join(payments) or 'None'}\n**Bio:** {bio or 'None'}")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# /profile command (view own or other's)
@bot.tree.command(name="profile", description="View a user profile")
@app_commands.describe(user="The user to view (optional: defaults to you)")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (target.id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await interaction.response.send_message(embed=create_embed("No Profile", f"{target.mention} has no registered profile."), ephemeral=True)
        return
    
    specs = load_json(row[2])
    payments = load_json(row[3])
    embed = create_embed(
        f"{target.display_name}'s Profile",
        row[5] or "No bio.",
        [
            ("Experience", f"{row[1]} years", True),
            ("Rate", f"${row[4]}", True),
            ("Specializations", ', '.join(specs) or 'None', False),
            ("Payment Methods", ', '.join(payments) or 'None', False)
        ]
    )
    embed.set_thumbnail(url=target.avatar.url if target.avatar else None)
    await interaction.response.send_message(embed=embed)

# /search command (for hirers)
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
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, experience, specializations, payment_methods, rate, bio
        FROM users 
        WHERE experience >= ? AND rate <= ?
    ''', (min_experience, max_budget))
    rows = cursor.fetchall()
    conn.close()
    
    matches = []
    for row in rows:
        specs = load_json(row[2])
        payments = load_json(row[3])
        # Check intersections
        spec_match = not req_specs or any(s.lower() in spec.lower() for spec in specs for s in req_specs)
        pay_match = not req_payments or any(p.lower() in pay.lower() for pay in payments for p in req_payments)
        if spec_match and pay_match:
            user = bot.get_user(row[0])
            matches.append({
                'user': user or f"ID: {row[0]}",
                'exp': row[1],
                'rate': row[4],
                'specs': specs,
                'bio': row[5][:100] + '...' if len(row[5]) > 100 else row[5]
            })
    
    if not matches:
        await interaction.response.send_message(embed=create_embed("No Matches", f"No devs found for your criteria. Try broadening filters!"), ephemeral=False)
        return
    
    # Paginated embed (simple: first page with up to 5, add reaction for more if needed)
    embed = create_embed(f"Search Results ({len(matches)} matches)", "Here are top matches:")
    for i, match in enumerate(matches[:5], 1):
        user_mention = match['user'].mention if isinstance(match['user'], discord.User) else match['user']
        embed.add_field(
            name=f"{i}. {user_mention}",
            value=f"**Exp:** {match['exp']}y | **Rate:** ${match['rate']}\n**Specs:** {', '.join(match['specs'][:2])}\n**Bio:** {match['bio']}",
            inline=False
        )
    if len(matches) > 5:
        embed.set_footer(text=f"Showing 1-5 of {len(matches)}. Use /profile for details.")
    
    await interaction.response.send_message(embed=embed, ephemeral=False)

# /report command
@bot.tree.command(name="report", description="Report a user for review")
@app_commands.describe(user="The user to report", reason="Reason for report (e.g., scam, spam)")
async def report(interaction: discord.Interaction, user: discord.Member, reason: str):
    if len(reason) > 1000:
        await interaction.response.send_message(embed=create_embed("Error", "Reason too long (max 1000 chars).", color=0xFF0000), ephemeral=True)
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, ?)',
                   (interaction.user.id, user.id, reason))
    conn.commit()
    conn.close()
    
    # Send to mod channel
    mod_channel = bot.get_channel(MOD_CHANNEL_ID)
    if mod_channel:
        report_embed = create_embed(
            "New Report Received",
            f"**Reporter:** {interaction.user.mention} (ID: {interaction.user.id})\n**Reported:** {user.mention} (ID: {user.id})\n**Reason:** {reason}",
            color=0xFF9900
        )
        await mod_channel.send(embed=report_embed)
    
    await interaction.response.send_message(embed=create_embed("Report Submitted", f"Thanks for reporting {user.mention}. Mods will review it soon."), ephemeral=True)

# Run bot (with FastAPI for Render)
if __name__ == "__main__":
    if os.getenv('RENDER'):  # Render env
        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv('PORT', 8000)))
    else:
        bot.run(TOKEN)
