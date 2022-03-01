# User extensions
User extensions are regular discord.py extensions, but loaded into spanner.

## Where to put them
You need to put your `.py` files in this directory.

**Do not put any user extensions in the `official` directory!**
These are not automatically detected and loaded if you put them
in there, so you won't get results. The user cogs are
handled differently to official cogs, and as such should be separated.

## Writing a basic cog
Here is a basic example:

```python
import discord
from discord.ext import commands


class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command()
    async def hello(self, ctx: discord.ApplicationContext, user: discord.User):
        await ctx.respond(f"{user.mention}, {ctx.user.mention} says hi!")


def setup(bot):
    bot.add_cog(MyCog(bot))
```
You can find more detailed guides online.

And that's it, your cog will load automatically on next restart!

### Warning
You cannot overwrite built-in commands. Doing so may cause potential conflicts or errors.

Furthermore, make sure you put the cogs in the `.../user/cogs` directory, NOT `.../user`.
