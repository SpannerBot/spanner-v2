import asyncio
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.tree import Tree

from src.utils import load_colon_int_list

os.chdir(Path(__file__).parent)


def get_file_tree(directory: Path = None, tree: Tree = None) -> Tree:
    home = directory or Path.cwd()
    tree = tree or Tree(str(home.absolute()))
    paths = sorted(
        home.iterdir(),
        key=lambda _path: (_path.is_file(), _path.name.lower()),
    )
    for path in paths:
        if path.name.startswith((".", "__")) or "venv" in [x.name for x in path.parents]:
            continue
        if path.is_dir():
            tree2 = tree.add(f"[bold][link file://{path}]{path.name}")
            get_file_tree(path, tree2)
        else:
            tree.add(f"[dim][link file://{path}]{path.name}")
    return tree


@click.group()
def cli():
    pass


@cli.group(name="info")
def see_info():
    """Displays information about this instance"""


@see_info.command()
@click.option("--verbose", default=False, help="Display verbose information", is_flag=True)
def version(verbose: bool = False):
    """Displays version-related information"""
    import discord
    import sys

    output = subprocess.run(
        (sys.executable, "-m", "pip", "list", "--format=json"), capture_output=True, encoding=sys.stdout.encoding
    )
    packages_data = json.loads(output.stdout.strip())

    spanner_version = subprocess.run(
        ("git", "rev-parse", "--short", "HEAD"), capture_output=True, encoding=sys.stdout.encoding
    )
    spanner_version = spanner_version.stdout.strip() or 'unknown'
    spanner_version = (
        discord.utils.find(lambda item: item["name"] == "spanner", packages_data) or {"version": spanner_version}
    )["version"]

    configs = []
    # In order of lookup:
    if Path("./config.json").exists():
        configs.append(("Local", Path("./config.json").absolute()))
    if Path("~/.config/spanner-v2/config.json").exists():
        configs.append(("Global", Path("~/.config/spanner-v2/config.json").absolute()))
    if Path("./.env").exists():
        configs.append(("Local-Old\N{WARNING SIGN}", Path("./.env").absolute()))

    lines = [
        "py-cord version: {0.major}.{0.minor}.{0.micro}{0.releaselevel[0]}{0.serial}".format(discord.version_info),
        "Python version: {0.major}.{0.minor}.{0.micro}{0.releaselevel[0]}{0.serial}".format(sys.version_info),
        "\t- Executable: " + sys.executable,
        *[
            "\t- %s Config: %s" % (name, path)
            for name, path in configs
        ],
        "Spanner version: " + spanner_version,
        "System: " + platform.platform(),
    ]
    if verbose:
        lines.append(("-" * 5) + "Package Data" + ("-" * 5))
        for package_data in packages_data:
            lines.append("{0[name]}: {0[version]}".format(package_data))

    if verbose:
        click.echo_via_pager("\n".join(lines))
    else:
        click.echo("\n".join(lines))


@see_info.command(name="file-tree")
def view_file_tree():
    """Shows the project's file tree. useful for finding missing files."""
    Console().print(get_file_tree())


@cli.command(name="convert")
def convert_config():
    """Converts your old environment file to a config file"""
    new = {}
    with open("./.env") as old_file:
        for line in old_file.readlines():
            line = line.strip()
            try:
                name, value = line.split("=", 1)
            except ValueError as e:
                print("Failed to process line:", repr(line), "-", e)
                print("Skipping")
                continue
            name: str = name.lower()
            if ":" in value:
                try:
                    value = load_colon_int_list(value)
                except ValueError:
                    pass
            elif value.isdigit():
                value = int(value)
            elif value.lower() in ["true", "false", "none", "null"]:
                value = {"t": True, "f": False, "n": None}[value.lower()[0]]

            if name.endswith("s") and not isinstance(value, list):
                value = [value]

            new[name.lower()] = value
    try:
        json.dumps(new)
    except json.JSONDecodeError as err:
        click.echo(f"Failed to parse new config: {err}")
    else:
        with open("config.json", "w+") as new_file:
            json.dump(new, new_file, indent=4, default=str)
        if input("Done. Remove old file? [y/N] ").lower().startswith("y"):
            os.remove(".env")
            click.echo("Done and removed old file.")
        else:
            click.echo("Done.")
        click.echo("You may want to edit config.json to make sure that this tool generated everything correctly.")


@cli.command(name="setup")
def make_setup():
    """Guides you though setting up the bot."""
    click.echo(
        "First, you'll need to give me a token that your *main* bot will use. Do not give me a token that you"
        " will use to test on.\nIf you don't have a token or don't want to have one, just press enter."
    )
    main_token = input("> ")
    click.echo(
        "Great! Now, you should give me a development token (a second bot that you'll use for testing)."
        " If you want to skip straight to production (for whatever reason), just hit enter.\n"
        "Note that this will disable debug mode."
    )
    dev_token = input("> ")
    click.echo("Amazing. On that note, would you like to enable debug mode? (yes or no)")
    debug_mode = input("> ")
    if debug_mode.lower().startswith("y"):
        debug_mode = True
        click.echo(
            "In debug mode, slash commands are created exclusively in provided test servers. This means you can"
            " see your changes to commands in roughly real time, instead of the hour wait for global "
            "commands."
        )
        click.echo(
            "Please enter a server ID you want to use each time the `> ` prompt comes up. "
            "Once you have finished adding servers, just press enter (with nothing after the prompt), and we"
            " will move on to the next step."
        )
        debug_guild_ids = []
        force_done = 0
        while True:
            try:
                _raw_id = input("> ")
                if not _raw_id:
                    if len(debug_guild_ids) == 0 and force_done < 2:
                        click.echo(
                            "With no debug guilds supplied, debug mode will be turned off.\n"
                            "If you are sure this is what you want, hit enter again. Otherwise, please"
                            " supply at least one server ID."
                        )
                        force_done += 1
                    else:
                        if force_done == 2:
                            debug_mode = False
                        break
                debug_guild_ids.append(int(_raw_id))
            except ValueError:
                click.echo("Please input server IDs only.")
        if debug_mode:
            click.echo(f"Aright, added {len(debug_guild_ids)} debug guilds.")
            click.echo(
                "Please make sure that your bot is added to every server you just listed, otherwise there will be a"
                " (non-fatal) error message at startup."
            )
        else:
            click.echo("Alright, disabled debug mode and didn't add any debug servers.")
    else:
        debug_mode = False

    owner_ids = None
    click.echo(
        "Now, we should set some owners (so that only you and whoever you say can run important commands)."
        " By default, with no user IDs provided, the bot will be 'owned' by whoever has the bot's profile"
        " on the developer portal. However, you can customise who 'owns' the bot by supplying user IDs."
        "\nWould you like to override the default ownership settings? [y/N]"
    )
    debug_guild_ids = None
    if input("> ").lower().startswith("y"):
        owner_ids = []
        click.echo(
            "Please enter a user ID you want to use each time the `> ` prompt comes up. "
            "Once you have finished adding users, just press enter (with nothing after the prompt), and we"
            " will move on to the next step."
        )
        debug_guild_ids = []
        force_done = 0
        while True:
            try:
                _raw_id = input("> ")
                if not _raw_id:
                    if len(debug_guild_ids) == 0 and force_done < 2:
                        click.echo(
                            "With no user IDs supplied, the default ownership settings will be applied.\n"
                            "If this is what you want, press enter again. Otherwise, provide a user ID."
                        )
                        force_done += 1
                    else:
                        if force_done == 2:
                            owner_ids = None
                        break
                owner_ids.append(int(_raw_id))
            except ValueError:
                click.echo("Please input server IDs only.")
        click.echo(
            f"Aright, added {len(owner_ids)} owners." if owner_ids else "Alright, using default ownership settings."
        )

    click.echo(
        "Spanner will log important events to a file called 'spanner.log'. You can control what level of "
        "information is logged to this file by setting a log level.\n"
        "Please say any of the following: DEBUG, INFO, WARNING, ERROR, CRITICAL.\n"
        "DEBUG is great for debugging or extremely verbose information, but will take up a lot of storage "
        "after a while. On the contrary, WARNING is great if you just want to catch warnings and errors, "
        "however provides less information."
    )
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    while True:
        _raw_value = input("> ").upper().strip()
        if _raw_value not in valid_levels:
            click.echo("Only the following values are accepted: %s" % ", ".join(valid_levels))
        else:
            log_level = _raw_value
            break

    click.echo(
        "You can also set a channel where errors (from people running commands) will be logged."
        " If you want to be able to receive error and bug reports from users, without having to scower"
        " the console output, you can get brief message explaining the error in a remote channel.\n"
        "If you want this, please put that channel's ID in now. Otherwise, press enter to skip."
    )
    try:
        error_channel = int(input("> "))
    except ValueError:
        error_channel = None

    click.echo("Finally, do you want your console output to look fancy? [Y/n]")
    colour = not input("> ").lower().startswith("n")
    click.echo("Awesome! Generating config file now...")
    with open("config.json", "w+") as config_file:
        json.dump(
            {
                "bot_token": main_token or dev_token,
                "dev_bot_token": dev_token,
                "owner_ids": owner_ids,
                "colour": colour,
                "slash_guilds": debug_guild_ids,
                "debug": debug_mode,
                "log_level": log_level,
                "error_channel": error_channel,
            },
            config_file,
            indent=4,
        )
    click.echo(f"All set! You can either run `{sys.executable} {sys.argv[0]} run`, or edit `config.json`!")


@cli.command()
def run():
    """Starts the bot"""
    from src import launcher

    click.echo("Launching bot...")
    os.chdir(Path(launcher.__file__).parents[1])
    click.echo("Changed working directory to %s." % Path(launcher.__file__).parents[1])
    try:
        asyncio.run(launcher.launch())
    finally:
        click.echo("Bot process finished.")


@cli.command(name="update")
def update_bot():
    """Runs pipx upgrade."""
    try:
        subprocess.run(("pipx", "upgrade", "-e", "spanner"))
    except FileNotFoundError:
        click.echo("PipX does not appear to be on PATH. Unable to update.")
        click.echo("Please run `pipx upgrade -e spanner'.")


if __name__ == "__main__":
    cli()
