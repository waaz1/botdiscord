
import os
import discord
from discord import ui
import sqlite3
import datetime
from discord.ext import commands

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
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()

class TicketModal(ui.Modal, title='Create Ticket'):
    def __init__(self):
        super().__init__()
        self.add_item(ui.TextInput(label='Subject', placeholder='Enter ticket subject...'))
        self.add_item(ui.TextInput(label='Description', style=discord.TextStyle.paragraph))

    async def on_submit(self, interaction: discord.Interaction):
        # Create ticket channel
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name='Tickets')
        if not category:
            category = await guild.create_category('Tickets')

        ticket_count = len(category.channels) + 1
        channel_name = f'ticket-{ticket_count}'
        
        # Set permissions
        staff_role = guild.get_role(1362037862995857538)  # Staff role ID
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True),
            staff_role: discord.PermissionOverwrite(read_messages=True)
        }

        channel = await category.create_text_channel(channel_name, overwrites=overwrites)

        # Create ticket embed
        embed = discord.Embed(
            title=f"Ticket #{ticket_count}",
            description="Support ticket created",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="Subject", value=self.children[0].value)
        embed.add_field(name="Description", value=self.children[1].value)
        embed.set_footer(text=f"Created by {interaction.user}")

        # Save to database
        conn = sqlite3.connect('tickets.db')
        c = conn.cursor()
        c.execute('''INSERT INTO tickets (user_id, channel_id, status, created_at)
                     VALUES (?, ?, ?, ?)''',
                  (interaction.user.id, channel.id, 'open', datetime.datetime.now()))
        conn.commit()
        conn.close()

        # Create close button
        class CloseButton(discord.ui.Button):
            def __init__(self):
                super().__init__(style=discord.ButtonStyle.danger, label="Close Ticket")

            async def callback(self, interaction: discord.Interaction):
                if staff_role not in interaction.user.roles:
                    await interaction.response.send_message("Only staff can close tickets!", ephemeral=True)
                    return

                conn = sqlite3.connect('tickets.db')
                c = conn.cursor()
                c.execute('''UPDATE tickets SET status = ? WHERE channel_id = ?''',
                         ('closed', channel.id))
                conn.commit()
                conn.close()

                await channel.delete()

        view = discord.ui.View()
        view.add_item(CloseButton())

        await channel.send(content=f"{staff_role.mention} New ticket created!", embed=embed, view=view)
        await interaction.response.send_message(f"Ticket created! Check {channel.mention}", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Bot is ready as {bot.user}')
    setup_database()

@bot.command()
async def panel(ctx):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You don't have permission to create ticket panels!")
        return

    embed = discord.Embed(
        title="Support Tickets",
        description="Click the button below to create a new support ticket",
        color=discord.Color.blue()
    )

    class TicketButton(discord.ui.Button):
        def __init__(self):
            super().__init__(style=discord.ButtonStyle.primary, label="Create Ticket")

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_modal(TicketModal())

    view = discord.ui.View(timeout=None)
    view.add_item(TicketButton())

    await ctx.send(embed=embed, view=view)

try:
    token = os.getenv("TOKEN") or ""
    if token == "":
        raise Exception("Please add your token to the Secrets pane.")
    bot.run(token)
except discord.HTTPException as e:
    if e.status == 429:
        print("The Discord servers denied the connection for making too many requests")
        print("Get help from https://stackoverflow.com/questions/66724687/in-discord-py-how-to-solve-the-error-for-toomanyrequests")
    else:
        raise e
