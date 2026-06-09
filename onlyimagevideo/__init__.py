from .onlyimagevideo import OnlyImageVideo


async def setup(bot):
    await bot.add_cog(OnlyImageVideo(bot))
