"""
This script is called on every startup of the bot.

It checks to see if the user has already set the bot up, and if not, guide them through setting it up.
"""
import os
import re
import sys
from typing import Dict, Callable, Literal
from pathlib import Path

# Some useful constants from builtin imports
PROJECT = (Path(__file__) / ".." / "..").resolve()  # directory
REQUIREMENTS_FILE = PROJECT / "requirements.txt"
EXECUTABLE = Path(sys.executable).resolve()  # resolve() because it could be a symlink and I'm picky
DISCORD_TOKEN_REGEX = re.compile(r"([a-zA-Z0-9]{24}\.[a-zA-Z0-9]{6}\.[a-zA-Z0-9_\-]{27}|mfa\.[a-zA-Z0-9_\-]{84})")


def dependency_check() -> Literal[True, False]:
    try:
        from rich.console import Console
        import dotenv
        import discord
        import httpx
    except ImportError:
        return False
    return True


# noinspection PyPep8Naming
def main():
    if not dependency_check():
        print(
            "Hm. It looks like you're missing dependencies. Please run '%s -m pip install -Ur %s'"
            % (EXECUTABLE, REQUIREMENTS_FILE),
            file=sys.stderr,
        )
        sys.exit(1)
    from rich.console import Console
    import dotenv

    console = Console()
    console.log("It looks like you're not set up yet, or your configuration is invalid!")
    console.log("Just checking to see what needs setting up...")

    if Path.cwd() != PROJECT:
        console.log(
            "[yellow]Your Current Working Directory is %s, not %s. Consider passing `--enforce-cwd` to runtime.[/]"
            % (Path.cwd(), PROJECT)
        )
        console.log("[yellow]If you did this, you can ignore this warning - it hasn't applied yet.")

    if (PROJECT / ".env").exists():
        console.log("[green].env file found (%s)[/]" % (PROJECT / ".env").resolve())
        try:
            dotenv.load_dotenv(dotenv_path=PROJECT / ".env")
        except Exception as e:
            console.log("[red]Error loading .env file: %s[/]" % e)
            console.log(
                "[red][bold]This error is fatal.[/] Please fix your environment file using the information above."
            )
            sys.exit(1)
        else:
            console.log("[green]Loaded .env![/]")
    else:
        console.log(
            "[yellow]You do not appear to have a [b].env[/] file. Please create one (expected location: %s)"
            % (PROJECT / ".env")
        )

    REQUIRED_VARS: Dict[str, Callable[[str], bool]] = {
        "DISCORD_TOKEN": lambda x: x is not None and DISCORD_TOKEN_REGEX.match(x) is not None,
        "OWNER_IDS": lambda x: all(y.isdigit() for y in x.split(":")) or not bool(x),
        "SLASH_GUILDS": lambda x: all(y.isdigit() for y in x.split(":")) or not bool(x),
        "DEBUG": lambda x: x.lower() in ["true", "false"],
    }
    ALL_OKAY = True
    console.log("Checking all required environment variables are set (and correctly)...")
    for key, value in os.environ.items():
        if key in REQUIRED_VARS.keys():
            try:
                valid = REQUIRED_VARS[key](value)
                if not valid:
                    console.log(
                        "[red]Environment variable %r is not set correctly. Consult README for correct format." % key
                    )
                    ALL_OKAY = False
                else:
                    console.log("[green]%r is set correctly." % key)
                    REQUIRED_VARS.pop(key)
            except Exception as e:
                console.log("[red][bold]Unable to check %r due to an error[/] - %r" % (key, e))
                ALL_OKAY = False

    if not ALL_OKAY:
        console.log(
            "[red]Some required environment variables were not set (correctly), so the bot will not start."
            "Please correct these, and restart."
        )
        sys.exit(1)

    for key in REQUIRED_VARS.keys():
        console.log("[red]Environment variable %r is not set. Consult README for corret format." % key)
        sys.exit(1)

    console.log(
        ":thumbs_up:[green] All looks good!\nIf you're getting this tool running when you shouldn't be,"
        "please open an issue on [github](https://github.com/EEKIM10/spanner-v2)."
    )
    sys.exit()


if __name__ == "__main__":
    os.chdir(PROJECT)
    main()
