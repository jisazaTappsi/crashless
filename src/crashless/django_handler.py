from threading import Timer

from django.http import JsonResponse

from crashless import handler


def handle_exception(exc: Exception):
    """Makes sure that messages display in the correct order in the terminal"""
    Timer(interval=0.05, function=handler.threaded_function, args=(exc,)).start()
    return JsonResponse(status_code=500, data=handler.get_content_message(exc))
