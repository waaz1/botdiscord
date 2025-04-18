
import os
import io
import discord
from discord import ui
import sqlite3
import datetime
import json
from discord.ext import commands
import asyncio

# Setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Database setup
def setup_database():
    conn = sqlite3.connect('tickets.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tickets
                 (ticket_id INTEGER PRIMARY KEY,
                  user_id INTEGER,
                  channel_id INTEGER,
                  status TEXT,
                  priority TEXT,
                  assigned_to INTEGER,
                  created_at TIMESTAMP,
                  last_activity TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ticket_settings
                 (guild_id INTEGER PRIMARY KEY,
                  language TEXT DEFAULT 'it',
                  auto_close_hours INTEGER DEFAULT 48,
                  tickets_per_hour INTEGER DEFAULT 1)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS ticket_logs
                 (log_id INTEGER PRIMARY KEY,
                  ticket_id INTEGER,
                  action TEXT,
                  performed_by INTEGER,
                  timestamp TIMESTAMP)''')
    conn.commit()
    conn.close()

class TicketModal(ui.Modal, title='Crea Ticket'):
    def __init__(self):
        super().__init__()
        self.add_item(ui.TextInput(label='Oggetto', placeholder='Inserisci oggetto ticket...'))
        self.add_item(ui.TextInput(label='Descrizione', style=discord.TextStyle.paragraph))
        self.add_item(ui.TextInput(label='Priorità', placeholder='alta/media/bassa'))

    async def on_submit(self, interaction: discord.Interaction):
        conn = sqlite3.connect('tickets.db')
        c = conn.cursor()

        priority = self.children[2].value.lower()
        if priority not in ['alta', 'media', 'bassa']:
            priority = 'media'

        # Create ticket channel
        guild = interaction.guild
        category = guild.get_channel(1362029287238144172)
        if not category:
            await interaction.response.send_message("Errore: categoria ticket non trovata!", ephemeral=True)
            return

        ticket_count = len(category.channels) + 1
        channel_name = f'ticket-{ticket_count}'
        
        # Set permissions
        staff_role = guild.get_role(1362037862995857538)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True),
            staff_role: discord.PermissionOverwrite(read_messages=True)
        }

        channel = await category.create_text_channel(channel_name, overwrites=overwrites)

        # Create ticket embed with priority colors
        colors = {'alta': discord.Color.red(),
                 'media': discord.Color.orange(),
                 'bassa': discord.Color.green()}
                 
        embed = discord.Embed(
            title=f"Ticket #{ticket_count}",
            description="Ticket di supporto creato",
            color=colors[priority],
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Oggetto", value=self.children[0].value)
        embed.add_field(name="Descrizione", value=self.children[1].value)
        embed.add_field(name="Priorità", value=priority.upper())
        embed.set_footer(text=f"Creato da {interaction.user}")

        # Save to database
        c.execute('''INSERT INTO tickets 
                     (user_id, channel_id, status, priority, created_at, last_activity)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (interaction.user.id, channel.id, 'open', priority, 
                   datetime.datetime.now(), datetime.datetime.now()))
        conn.commit()
        conn.close()

        # Ticket management buttons
        class TicketButtons(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=None)

            @discord.ui.button(label="Chiudi Ticket", style=discord.ButtonStyle.danger)
            async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
                if staff_role not in interaction.user.roles:
                    await interaction.response.send_message("Solo lo staff può chiudere i ticket!", ephemeral=True)
                    return

                # Save and send transcript
                transcript = []
                async for message in channel.history(limit=None, oldest_first=True):
                    transcript.append(f"[{message.created_at}] {message.author}: {message.content}")

                transcript_text = "\n".join(transcript)
                transcript_channel = interaction.guild.get_channel(1362918431170629702)
                
                if transcript_channel:
                    file = discord.File(
                        fp=io.StringIO(transcript_text),
                        filename=f"transcript-{channel.name}.txt"
                    )
                    await transcript_channel.send(
                        f"Transcript del ticket {channel.name}",
                        file=file
                    )
                
                await interaction.response.send_message("Ticket chiuso e trascrizione salvata nel canale transcript.")
                await asyncio.sleep(5)
                await channel.delete()

            @discord.ui.button(label="Assegna", style=discord.ButtonStyle.primary)
            async def assign_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
                if staff_role not in interaction.user.roles:
                    await interaction.response.send_message("Solo lo staff può assegnare i ticket!", ephemeral=True)
                    return

                conn = sqlite3.connect('tickets.db')
                c = conn.cursor()
                c.execute('''UPDATE tickets SET assigned_to = ? WHERE channel_id = ?''',
                         (interaction.user.id, channel.id))
                conn.commit()
                conn.close()

                await interaction.response.send_message(f"Ticket assegnato a {interaction.user.mention}")

        view = TicketButtons()
        priority_mention = {
            'alta': f"{staff_role.mention} **PRIORITÀ ALTA**",
            'media': staff_role.mention,
            'bassa': staff_role.mention
        }

        await channel.send(content=priority_mention[priority], embed=embed, view=view)
        await interaction.response.send_message(f"Ticket creato! Controlla {channel.mention}", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Bot avviato come {bot.user}')
    setup_database()
    
    # Start auto-close check
    bot.loop.create_task(check_inactive_tickets())

async def check_inactive_tickets():
    while True:
        conn = sqlite3.connect('tickets.db')
        c = conn.cursor()
        c.execute('''SELECT channel_id FROM tickets 
                     WHERE status = 'open' 
                     AND last_activity < datetime('now', '-48 hours')''')
        inactive_tickets = c.fetchall()
        
        for (channel_id,) in inactive_tickets:
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.send("⚠️ Questo ticket verrà chiuso automaticamente per inattività tra 24 ore.")
                
        conn.close()
        await asyncio.sleep(86400)  # Check every 24 hours

@bot.command()
async def stats(ctx):
    if not ctx.author.guild_permissions.manage_channels:
        await ctx.send("Non hai i permessi per usare questo comando!")
        return
        
    conn = sqlite3.connect('tickets.db')
    c = conn.cursor()
    c.execute('''SELECT status, COUNT(*) FROM tickets GROUP BY status''')
    stats = c.fetchall()
    conn.close()
    
    embed = discord.Embed(title="Statistiche Ticket", color=discord.Color.blue())
    for status, count in stats:
        embed.add_field(name=status.capitalize(), value=str(count))
    
    await ctx.send(embed=embed)

@bot.command()
async def mytickets(ctx):
    conn = sqlite3.connect('tickets.db')
    c = conn.cursor()
    c.execute('''SELECT ticket_id, status, created_at FROM tickets WHERE user_id = ?''',
              (ctx.author.id,))
    tickets = c.fetchall()
    conn.close()
    
    if not tickets:
        await ctx.send("Non hai nessun ticket.", ephemeral=True)
        return
        
    embed = discord.Embed(title="I tuoi Ticket", color=discord.Color.blue())
    for ticket_id, status, created_at in tickets:
        embed.add_field(name=f"Ticket #{ticket_id}", 
                       value=f"Stato: {status}\nCreato il: {created_at}",
                       inline=False)
    
    await ctx.send(embed=embed, ephemeral=True)

@bot.command()
async def panel(ctx):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("Non hai i permessi per creare pannelli ticket!")
        return

    embed = discord.Embed(
        title="Supporto Ticket",
        description="Clicca il pulsante sotto per creare un nuovo ticket di supporto",
        color=discord.Color.blue()
    )

    class TicketButton(discord.ui.Button):
        def __init__(self):
            super().__init__(style=discord.ButtonStyle.primary, label="Crea Ticket")

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_modal(TicketModal())

    view = discord.ui.View(timeout=None)
    view.add_item(TicketButton())

    await ctx.send(embed=embed, view=view)

try:
    token = os.getenv("TOKEN") or ""
    if token == "":
        raise Exception("Aggiungi il tuo token nel pannello Secrets.")
    bot.run(token)
except discord.HTTPException as e:
    if e.status == 429:
        print("I server Discord hanno negato la connessione per troppe richieste")
    else:
        raise e
