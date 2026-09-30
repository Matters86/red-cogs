from .ideas import Ideas


async def setup(bot):
    await bot.add_cog(Ideas(bot))
