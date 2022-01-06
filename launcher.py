import asyncio
import logging
import sys
import os
from pathlib import Path

os.chdir(Path(__file__).parent.absolute())

os.environ["JISHAKU_RETAIN"] = "true"

if os.environ.get("LOGGING", "true").lower().startswith("tr"):
    logging.basicConfig(
        filename="spanner.log",
        level=logging.INFO,
        filemode="w",
        format="%(asctime)s:%(name)s:%(levelname)s:%(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )

if sys.version_info >= (3, 10):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
else:
    import warnings

    warnings.warn(
        DeprecationWarning("Python 3.10 or higher is required for spanner. Some functionality may be unavailable.")
    )
    loop = asyncio.get_event_loop()


def main(bot):
    try:
        from rich.traceback import install

        install(console=bot.console, show_locals=True)
        bot.run()
    except KeyError as e:
        # Likely missing an env var
        print("Missing environ var %r" % e)
    except Exception:
        bot.console.print("[red bold]Critical Exception!")
        bot.console.print("[red]=== BEGIN CRASH REPORT ===")
        bot.console.print_exception()
        bot.console.print("[red]===  END CRASH REPORT  ===")
        bot.console.print("[red]Spanner v2 has encountered a critical runtime error and has been forced to shut down.")
        bot.console.print("[red]Details are above.")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    try:
        from src.bot.client import bot as bot_instance

        main(bot_instance)
    except Exception:
        try:
            console = bot_instance.console
        except NameError:
            from rich.console import Console

            console = Console()
        console.print("[red bold blink]Mayday in launcher![/]")
        console.print("[red]=== BEGIN CRASH REPORT ===")
        console.print_exception(show_locals=True)
        console.print("[red]===  END CRASH REPORT  ===")
        console.print("[red]Spanner v2 has encountered a critical runtime error and has been forced to shut down.")
        console.print("[red]Details are above.")
        console.print(
            "[black on red][blink]THIS IS LIKELY A BUG![/] The error occurred in the runner, and is "
            "unlikely to have propagated from the bot itself."
        )
        sys.exit(1)


else:
    raise RuntimeError("This file is not supposed to be imported.")
