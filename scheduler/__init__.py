from .scheduler import Scheduler


async def setup(bot):
    await bot.add_cog(Scheduler(bot))
