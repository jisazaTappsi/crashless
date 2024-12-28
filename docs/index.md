# Crashless
**Crash proof your code**

Crashless enables you to catch those pesky bugs during backend development and correct them in real-time. Makes your development cycle smooth, so you can actually focus on building what actually matters.


## Installation

Crashless is published as a Python package and can be installed with pip, ideally by using a virtual environment. Open up a terminal and install Crashless with:

    pip install crashless


## Add to FastAPI in 3 steps

1. Copy and paste the following server with a crashed endpoint to a file called `main.py`:

        from fastapi import FastAPI
    
        app = FastAPI()


        @app.get("/")
        def read_root():
            return {"message": "The server is running OK!"}
    
    
        @app.get("/crash")  # This endpoint has a fatal bug :(
        def crash():
            result = 8 + '7'
            return {'msg': f"Summing a+b = {result}"}
        
        
        # Adds Crashless
        import sys
        from crashless import fastapi_handler  # Imports library
        
        
        def in_dev_mode():
            """Knows if you are running in production or development mode"""
            return sys.argv[1] == 'dev'
        
        
        if in_dev_mode():  # If in dev mode adds an exception handler, that will suggest a possible fix.
            app.add_exception_handler(Exception, fastapi_handler.handle_exception)


    As you can see the `/crash` endpoint has an issue.


2. Run the server with:

        fastapi dev main.py

    If you don't have the fastapi command follow instructions [here][1].

    [1]: <https://fastapi.tiangolo.com/fastapi-cli/> "fastapi CLI installation"



3. Go to <http://127.0.0.1:8000> and check that it's running OK.

    Then go to <http://127.0.0.1:8000/crash> and see how it crashes.

    Now go to the terminal, where the server is running, and you'll see something like this:

        TypeError: unsupported operand type(s) for +: 'int' and 'str'

        Error detected, let's fix it!
        The following code changes will be applied:
 
         @app.get("/crash")  # This endpoint has a fatal bug :(
         def crash():
        -    result = 8 + '7'
        +    result = 8 + int('7')
         return {'msg': f"Summing a+b = {result}"}


        Explanation: The error occurred because you cannot add an integer and a string directly. The fix converts the string '7' to
        an integer using int('7') before performing the addition.

   You can apply changes by ENTERING a `y`. The changes will take place and the api reloads. If you try again you get 15!


## Add to Django in 3 steps

coming soon!

## Add to Flask in 3 steps

coming soon!


## Links

**Source Code:** <https://github.com/jisazaTappsi/crashless>

**Python library**: <https://pypi.org/project/crashless/>
