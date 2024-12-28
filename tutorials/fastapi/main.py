from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def read_root():
    return {"message": "The server is running OK!"}


@app.get("/crash")  # This endpoint has a fatal bug :(
def crash():
    a = 8
    b = 7  # Changed 'b' to an integer
    print("Ooops, I'll crash ...")
    result = a + b
    return {'msg': f"Summing a+b = {result}"}


# Adds Crashless
import sys
from crashless import fastapi_handler  # Imports library


def in_dev_mode():
    """Knows if you are running in production or development mode"""
    return sys.argv[1] == 'dev'


if in_dev_mode():  # If in dev mode adds an exception handler, that will suggest a possible fix.
    app.add_exception_handler(Exception, fastapi_handler.handle_exception)
