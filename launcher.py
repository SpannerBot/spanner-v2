import sys
import asyncio
import scripts.first_run
import scripts.cli

if not scripts.first_run.dependency_check():
    scripts.first_run.main()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


def main(bot):
    try:
        from rich.traceback import install

        install(console=bot.console, show_locals=True)
        bot.run()
    except KeyError as e:
        # Likely missing an env var
        print("Missing environ var %r" % e)
        scripts.first_run.main()
    except Exception:
        bot.console.print("[red bold]Critical Exception![/]")
        bot.console.print("[red]=== BEGIN CRASH REPORT ===")
        bot.console.print_exception()
        bot.console.print("[red]===  END CRASH REPORT  ===")
        bot.console.print("[red]Spanner v2 has encountered a critical runtime error and has been forced to shut down.")
        bot.console.print("[red]Details are above.")


if __name__ == '__main__':
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
        console.print("[black on red][blink]THIS IS LIKELY A BUG![/] The error occurred in the runner, and is "
                      "unlikely to have propagated from the bot itself.")
        sys.exit(1)


else:
    raise RuntimeError('This file is not supposed to be imported.')
