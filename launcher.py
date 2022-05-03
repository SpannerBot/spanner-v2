import asyncio
import logging
import os
import textwrap
import traceback

import sys
from pathlib import Path

import dotenv

os.chdir(Path(__file__).parent.absolute())

dotenv_path = Path(__file__).parent.absolute() / ".env"
if not dotenv_path.exists():
    # LOG_LEVEL= INFO  # Can be any of: DEBUG, INFO, WARNING, ERROR, CRITICAL
    # DISCORD_TOKEN= # The token to your bot. Must not be quoted, especially if running from docker (for some reason).
    # OWNER_IDS= ''  # A list of user IDs, separated by colons (e.g. 123:456:789); Defaults to the application owner.
    # SLASH_GUILDS= ''  # A list of guild IDs to create interactions in. If not provided, will create global interactions.
    # DEBUG=true  # true or false, enables debugging features. If false, this will ignore SLASH_GUILDS.
    # COLOURS=true  # true or false, enables rich console features (colours, links, etc). Not recommended for headless runs.
    # JISHAKU_RETAIN=true  # true or false, enables variable retention in jishaku (eval).
    # FANCY_TRACEBACKS=true  # true or false, toggles the rich (pretty) traceback, or plain default python one.
    template = textwrap.dedent(
        """
# See for info: launcher.py, around line 13
LOG_LEVEL=INFO
DISCORD_TOKEN=
OWNER_IDS=
SLASH_GUILDS
DEBUG=true
COLOURS=true
JISHAKU_RETAIN=true
FANCY_TRACEBACKS=true
        """
    )
    dotenv_path.touch()
    with dotenv_path.open("w") as file:
        file.write(template)
    print("Please modify the .env file at: %s" % dotenv_path.absolute())

dotenv.load_dotenv()

os.environ["JISHAKU_RETAIN"] = "true"
log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
FANCY_TRACEBACKS = os.getenv("FANCY_TRACEBACKS", "true").lower().startswith("t")

logging.basicConfig(
    filename="spanner.log",
    level=log_level,
    filemode="w",
    format="%(asctime)s:%(name)s:%(levelname)s:%(message)s",
    datefmt="%d-%m-%Y %H:%M:%S",
    encoding="utf-8",
    errors="replace",
)

logging.info("Configured log level: %s", os.getenv("LOG_LEVEL", "INFO").upper().strip())

if sys.version_info >= (3, 10):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
else:
    import warnings

    warnings.warn(
        PendingDeprecationWarning(
            "Python 3.10 or higher is required for spanner. Some functionality may be unavailable."
        )
    )
    loop = asyncio.get_event_loop()


def main(bot):
    try:
        from rich.traceback import install

        if FANCY_TRACEBACKS:
            install(console=bot.console, show_locals=True)
        bot.run()
    except KeyError as e:
        # Likely missing an env var
        print("Missing environ var %r" % e)
    except (Exception, TypeError):  # two errors to shut the linter up about catching Exception itself
        bot.console.print("[red bold]Critical Exception!")
        bot.console.print("[red]=== BEGIN CRASH REPORT ===")
        if FANCY_TRACEBACKS:
            bot.console.print_exception(extra_lines=2, max_frames=1)
        else:
            traceback.print_exc()
            print(end="", flush=True)
        bot.console.print("[red]===  END CRASH REPORT  ===")
        bot.console.print("[red]Spanner v2 has encountered a critical runtime error and has been forced to shut down.")
        bot.console.print("[red]Details are above.")
        bot.console.print("[red i]Chances are, this is a bug in user-code, not the launcher.")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    try:
        from src.bot.client import bot as bot_instance

        main(bot_instance)
    except (Exception, AttributeError):
        try:
            console = bot_instance.console
        except NameError:
            from rich.console import Console

            console = Console()

        console.print("[red bold blink]Mayday in launcher![/]")
        console.print("[red]=== BEGIN CRASH REPORT ===")
        if FANCY_TRACEBACKS:
            console.print_exception(show_locals=True, extra_lines=3)
        else:
            traceback.print_exc()
            print(end="", flush=True)
        console.print("[red]===  END CRASH REPORT  ===")
        console.print("[red]Spanner v2 has encountered a critical runtime error and has been forced to shut down.")
        console.print("[red]Details are above.")
        console.print(
            "[black on red][blink]THIS IS LIKELY A BUG![/] The error occurred in the runner, and is "
            "unlikely to have propagated from the bot itself."
        )
        sys.exit(1)
    finally:
        logging.info("End of log.")


else:
    raise RuntimeError("This file is not supposed to be imported.")
