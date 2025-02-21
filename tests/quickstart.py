import os
from fastapi import FastAPI

from crashless import fastapi_handler  # Add Crashless

app = FastAPI()


@app.get("/")
def read_root():
    return {"message": "The server is running OK!"}


@app.get("/crash")  # This endpoint has a fatal bug :(
def crash():
    result = 8 + '7'
    return {'msg': f"Summing a+b = {result}"}


def in_dev_mode():
    """Knows if you are running in production or development mode"""
    return bool(int(os.environ.get("CRASHLESS_DEBUG_MODE", 0)))


if in_dev_mode():  # If in dev mode adds an exception handler, that will suggest a possible fix.
    app.add_exception_handler(Exception, fastapi_handler.handle_exception)
