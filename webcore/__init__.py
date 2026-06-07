from .webcore import WebCore


async def setup(bot):
    await bot.add_cog(WebCore(bot))
