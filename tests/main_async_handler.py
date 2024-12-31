import traceback
from threading import Timer

from fastapi import FastAPI
from requests import Request
from starlette.responses import JSONResponse

app = FastAPI()


@app.get("/crash")  # This endpoint has a fatal bug :(
def crash():
    return {'msg': f"Summing squared ages = {'2' + 2 }"}


def get_stacktrace(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def sync_function():
    print('This message should be below stacktrace')


def custom_handle_exception(request: Request, exc: Exception):
    Timer(interval=0.05, function=sync_function, args=()).start()
    return JSONResponse(status_code=500, content={'msg': 'Returning content'})


app.add_exception_handler(Exception, custom_handle_exception)
