from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins="*",
    allow_methods="*",
    allow_credentials=True
)
app.state.bot = None


@app.on_event("startup")
async def startup():
    from .client import bot
    app.state.bot = bot
    app.state.bot.console.log("Web server started.")
