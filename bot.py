import discord
from discord.ext import commands
from discord.commands import Option

import json
import io
import os
import asyncio

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates

from time import time
from datetime import datetime

from ledger import *

ledger_data = PersistentLedger("secrets/nledger.json")

description = """
    Bot to store poker ledgers for poker game nights.
"""

secrets = json.load(open("secrets/secrets.json"))

intents = discord.Intents.all()
intents.members = True
intents.message_content = True

bot = discord.Bot()
ledger = discord.SlashCommandGroup("ledger", "ledger command group")
misc = discord.SlashCommandGroup("misc", "used for misc commands")
client = discord.Client()

plt.rcParams["font.family"] = "sans-serif"

"""
HELPER FUNCTIONS
"""


def money_fmt(amount: int) -> str:
    if amount < 0:
        return f"-${-amount}"
    else:
        return f"${amount}"


async def disp_name(ident) -> str:
    try:
        user = await bot.fetch_user(ident)
        name = user.display_name if user else ident
    except Exception as e:
        name = ident

    return name


# Function to create a bank balance graph for a specific player
async def create_player_bank_graph(ledger_data: PersistentLedger, ident: str):
    running_balance = 0
    timestamps = []
    balances = []

    name = await disp_name(ident)

    async with ledger_data.lock:
        for entry in ledger_data.data:
            if entry["u_from"] == ident:
                running_balance -= entry["amount"]
            elif entry["u_to"] == ident:
                running_balance += entry["amount"]

            timestamps.append(datetime.fromtimestamp(entry["t"]))
            balances.append(running_balance)

    fig, ax = plt.subplots()
    ax.plot(timestamps, balances, label=name)

    ax.set_xlabel("Round")
    ax.set_ylabel("Bank Balance")
    ax.set_title(f"{name}'s Bank Balance History")
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    fig.set_facecolor("#2596be")

    # Force x-axis ticks to be integers
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    # Save the plot to a BytesIO object
    image_stream = io.BytesIO()
    plt.savefig(image_stream, format="png")
    image_stream.seek(0)

    # Clear the plot for the next use
    plt.clf()

    return image_stream


# Function to create a bank balance graph for a specific player
async def create_leaderboard_graph(ledger_data: PersistentLedger):
    fig, ax = plt.subplots()

    players = await ledger_data.unique_players()
    running_bals = {player: 0 for player in players}

    timestamps = []
    balances = {player: [] for player in players}

    async with ledger_data.lock:
        for entry in ledger_data.data:
            running_bals[entry["u_from"]] -= entry["amount"]
            running_bals[entry["u_to"]] += entry["amount"]

            if running_bals["pot"] <= 0:
                # when everyone's settled, add to the graph
                for player in players:
                    balances[player].append(running_bals[player])

                timestamps.append(datetime.fromtimestamp(entry["t"]))

    for player in players:
        if player == "pot" or player == "U.S. Federal Reserve":
            continue
        ax.plot(timestamps, balances[player], label=await disp_name(player))

    ax.set_xlabel("Round")
    ax.set_ylabel("Bank Balance")
    ax.set_title(f"Bank Balance History")
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    fig.set_facecolor("#2596be")

    # Shrink current axis by 20%
    box = ax.get_position()
    ax.set_position([box.x0, box.y0, box.width * 0.7, box.height])

    # Put a legend to the right of the current axis
    ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))

    fig_width, _ = plt.gcf().get_size_inches()

    # Get transformed x-tick labels
    unique_dates = set(tick.get_text() for tick in plt.gca().get_xticklabels())

    # Force there to be only the minimum of unique dates or the width of current figure
    ax.xaxis.set_major_locator(
        ticker.MaxNLocator(min(len(unique_dates), int(fig_width)))
    )

    # Save the plot to a BytesIO object
    image_stream = io.BytesIO()
    plt.savefig(image_stream, format="png")
    image_stream.seek(0)

    # Clear the plot for the next use
    plt.clf()

    return image_stream


"""
UPDATE COMMAND FUNCTIONS
"""


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


@ledger.command(name="buyin", description="Buy in, default $200")
async def buyin(ctx, member: discord.Member = None, amount: int = 200):

    member = member or ctx.author

    ident = str(member.id)
    name = member.display_name

    async with ledger_data.lock:
        ledger_data.append(
            {"u_from": ident, "u_to": "pot", "amount": amount, "t": time()}
        )

    balance = await ledger_data.player_balance(ident)

    message = f"Updated Player **{name}'s** bank account!\n"

    color = discord.Colour.green()

    message += f"Bank Account Total: {money_fmt(balance)}\n"

    embed = discord.Embed(
        title=f"Updating Bank Account",
        description=message,
        colour=color,
    )

    await ctx.respond(embed=embed)


@ledger.command(
    name="updatebank",
    description="Update bank amount with how many chips are remaining",
)
async def updatebank(ctx, amount: int, member: discord.Member = None):
    if member is None:
        member = ctx.author

    ident = str(member.id)
    name = member.display_name

    pot_balance = await ledger_data.player_balance("pot")

    message = (
        f"Amount is more than the pot! Make sure you have counted the correct amount.\n"
    )
    color = discord.Colour.red()

    if amount > pot_balance:
        embed = discord.Embed(
            title=f"No.",
            description=message,
            colour=color,
        )

        await ctx.respond(embed=embed)

        return

    async with ledger_data.lock:
        ledger_data.append(
            {"u_from": "pot", "u_to": ident, "amount": amount, "t": time()}
        )

    color = discord.Colour.green()

    new_amount = await ledger_data.player_balance(ident)

    message = f"Updated Player **{name}'s** bank account!\n"

    if new_amount < 0:
        message += f"Bank Account Total: -${-new_amount}\n\n"
        message += f"Player is in **debt** :("
        color = discord.Colour.red()
    else:
        message += f"Bank Account Total: ${new_amount}\n"

    embed = discord.Embed(
        title=f"Updating Bank Account",
        description=message,
        colour=color,
    )

    await ctx.respond(embed=embed)


"""
DISPLAY COMMAND FUNCTIONS
"""


@ledger.command(name="help", description="Get help on how to use the ledger commands")
async def help(ctx):
    message = """
    **/ledger buyin** - Buy into the game, default $200
    **/ledger updatebank** - Update bank amount with how many chips are remaining
    **/ledger individual_stats** - Get your or another player's Poker stats
    **/ledger leaderboard** - Current Poker Leaderboard
    **/ledger mint** - create new money out of thin air
    **/ledger hands** - Ranks of Hands in Texas Holdem Poker
    """

    embed = discord.Embed(
        title="Ledger Commands",
        description=message,
        colour=discord.Colour.blue(),
    )

    await ctx.respond(embed=embed)


@ledger.command(
    name="individual_stats", description="Get your or another player's Poker stats"
)
async def individ_stats(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    ident = str(member.id)
    name = member.display_name

    stats_message = f"Player **{name}**\n\n"

    color = discord.Colour.blue()

    balance = await ledger_data.player_balance(ident)
    if balance < 0:
        stats_message += f"Bank Account Total: -${-balance}\n\n"
        stats_message += f"Player is in **debt** :("
        color = discord.Colour.red()
    else:
        stats_message += f"Bank Account Total: ${balance}\n"

    embed = discord.Embed(
        title="Statistics",
        description=stats_message,
        colour=color,
    )

    try:
        # Create the bank balance graph for the specified player
        image_stream = await create_player_bank_graph(ledger_data, ident)

        # Send the graph to Discord
        file = discord.File(image_stream, filename=f"{name}_bank_graph.png")
        # await ctx.respond(file=file)

    except ValueError as e:
        await ctx.respond(str(e))

    await ctx.respond(file=file, embed=embed)


@ledger.command(
    name="leaderboard",
    description="Current Poker Leaderboard",
)
async def leaderboard(ctx):
    await ctx.defer()

    player_bals = {}
    async with ledger_data.lock:
        for entry in ledger_data.data:
            player_bals[entry["u_from"]] = (
                player_bals.get(entry["u_from"], 0) - entry["amount"]
            )
            player_bals[entry["u_to"]] = (
                player_bals.get(entry["u_to"], 0) + entry["amount"]
            )

    sorted_players = sorted(player_bals.items(), key=lambda x: x[1], reverse=True)

    message = ""

    # Iterate through all players
    for rank, (username, value) in enumerate(sorted_players, start=1):
        username = await disp_name(username)
        message += f"{rank}. **{username}**: "

        if value < 0:
            message += f"-${-value}\n"
        else:
            message += f"${value}\n"

    title = f"Leaderboard: Bank Balance"

    embed = discord.Embed(
        title=title,
        description=message,
        colour=discord.Colour.blue(),
    )

    try:
        # Create the bank balance graph
        image_stream = await create_leaderboard_graph(ledger_data)

        # Send the graphs to Discord
        file_graph = discord.File(image_stream, filename=f"leaderboard_bank_graph.png")
    except ValueError as e:
        await ctx.respond(str(e))

    await ctx.respond(file=file_graph, embed=embed)


@ledger.command(name="mint", description="create new money out of thin air")
async def mint(ctx, amount: int, member: discord.Member = None):
    if member is None:
        member = ctx.author

    ident = str(member.id)
    name = member.display_name

    async with ledger_data.lock:
        total_minted = sum(
            transaction["amount"]
            for transaction in ledger_data.data
            if transaction["u_from"] == "U.S. Federal Reserve"
            and transaction["u_to"] == ident
        )
        if amount > 800 - total_minted:
            message = f"Player **{name}'s** already money minted!\n"
            color = discord.Colour.red()

            embed = discord.Embed(
                title=f"No. You are not a money-minter.",
                description=message,
                colour=color,
            )

            await ctx.respond(embed=embed)

            return

        ledger_data.append(
            {
                "u_from": "U.S. Federal Reserve",
                "u_to": ident,
                "amount": amount,
                "t": time(),
            }
        )

    balance = await ledger_data.player_balance(ident)

    message = f"Updated Player **{name}'s** bank account!\n"

    color = discord.Colour.green()

    message += f"Bank Account Total: {money_fmt(balance)}\n"

    embed = discord.Embed(
        title=f"Updating Bank Account",
        description=message,
        colour=color,
    )

    await ctx.respond(embed=embed)


@ledger.command(name="hands", description="Ranks of Hands in Texas Holdem Poker")
async def hands(ctx):
    try:
        with open("poker-hands-rank.png", "rb") as f:
            picture = discord.File(f)
            await ctx.respond(file=picture)
    except Exception as e:
        print(e)
        embed = discord.Embed(
            title="Error!",
            description=f"Something is wrong internally :(",
            color=discord.Colour.red(),
        )
        return await ctx.respond(embed=embed)


"""
SETUP FUNCTIONS
"""

if __name__ == "__main__":
    bot.add_application_command(misc)
    bot.add_application_command(ledger)
    bot.run(secrets["TOKEN"])
