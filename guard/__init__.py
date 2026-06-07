from .guard import Guard


async def setup(bot):
    await bot.add_cog(Guard(bot))
