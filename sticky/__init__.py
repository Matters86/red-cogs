from .sticky import Sticky


async def setup(bot):
    await bot.add_cog(Sticky(bot))
