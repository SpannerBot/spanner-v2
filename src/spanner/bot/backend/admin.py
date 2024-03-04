from fastapi import APIRouter, Depends

from .auth import is_admin

app = APIRouter(
    prefix="/admin",
    dependencies=[Depends(is_admin)],
)


@app.get("/stats")
def get_bot_stats()
