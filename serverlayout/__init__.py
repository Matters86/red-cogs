from .serverlayout import ServerLayout


async def setup(bot):
    await bot.add_cog(ServerLayout(bot))
