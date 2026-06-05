from .autoroom import AutoRoom


async def setup(bot):
    await bot.add_cog(AutoRoom(bot))
