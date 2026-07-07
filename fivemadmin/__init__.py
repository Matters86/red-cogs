from .adminpanel import AdminPanel


async def setup(bot):
    await bot.add_cog(AdminPanel(bot))
