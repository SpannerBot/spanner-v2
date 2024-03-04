import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path
from rich.logging import RichHandler

import dotenv
from setproctitle import setproctitle

sys.path.extend(str(Path(__file__).parent.resolve()))

dotenv.load_dotenv()

os.environ["JISHAKU_RETAIN"] = "true"
log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)


async def main(bot):
    try:
        from rich.traceback import install

        if bot.get_config_value("fancy_tracebacks"):
            install(console=bot.console, show_locals=True)

        bot.console.log("Starting connections...")
        await bot.launch()
    except (Exception, TypeError):  # two errors to shut the linter up about catching Exception itself
        bot.console.print("[red bold]Critical Exception!")
        bot.console.print("[red]=== BEGIN CRASH REPORT ===")
        if bot.get_config_value("fancy_tracebacks"):
            bot.console.print_exception(extra_lines=2, max_frames=1)
        else:
            traceback.print_exc()
            print(end="", flush=True)
        bot.console.print("[red]===  END CRASH REPORT  ===")
        bot.console.print("[red]Spanner v2 has encountered a critical runtime error and has been forced to shut down.")
        bot.console.print("[red]Details are above.")
        bot.console.print("[red i]Chances are, this is a bug in user-code, not the launcher.")


async def launch():
    from src.bot.client import bot as bot_instance

    bot_instance.console.log("Preparing to launch spanner...")
    log_path = bot_instance.get_config_value("log_path", "log_file", default=None)
    if log_path:
        log_path = Path(log_path).expanduser().absolute().resolve()
        if log_path.is_dir():
            log_path = log_path / "spanner.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch(exist_ok=True)
        except OSError as e:
            bot_instance.console.log(f"[red]Error setting custom log file: {e}; defaulting.")
            log_path = None

    if not log_path:
        if Path("~/.local").expanduser().exists():
            log_path = Path("~/.local/share/spanner-v2/spanner.log").expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            log_path = Path("spanner.log")
    bot_instance.console.log("Log is located at %s." % (log_path.absolute()))

    LOG_LEVEL = bot_instance.get_config_value("log_level") or logging.INFO
    logging.basicConfig(
        filename=log_path,
        level=LOG_LEVEL,
        filemode="a",
        format="%(asctime)s:%(name)s:%(levelname)s:%(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
        encoding="utf-8",
        errors="replace",
    )
    # add a stream for stdout using rich handler
    logging.getLogger().addHandler(RichHandler(level=LOG_LEVEL, console=bot_instance.console))
    logging.info("Starting log.")
    try:
        setproctitle("spanner")
        bot_instance.console.log("Handing off launcher...")
        await main(bot_instance)
    except (Exception, AttributeError):
        try:
            # noinspection PyUnboundLocalVariable
            console = bot_instance.console
        except NameError:
            from rich.console import Console

            console = Console()

        console.print("[red bold blink]Mayday in launcher![/]")
        console.print("[red]=== BEGIN CRASH REPORT ===")
        traceback.print_exc()
        print(end="", flush=True, file=sys.stderr)
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


if __name__ == "__main__":
    asyncio.run(launch(), debug=True)
