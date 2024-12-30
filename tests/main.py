from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel
from crashless import fastapi_handler

app = FastAPI()
app.add_exception_handler(Exception, fastapi_handler.handle_exception)


class User(BaseModel):
    id: int
    name: str
    email: str
    user_age: Optional[int]

    def get_his_squared_age(self):
        return self.user_age**2


def sum_users_squared_ages(user1, user2):
    age1 = user1.get_squared_age()
    age2 = user2.get_squared_age()
    return age1 + age2


@app.get("/crash")  # This endpoint has a fatal bug :(
def crash():
    user1 = User(id=1, name='Peter', email='peter@the.great', user_age=42)
    user2 = User(id=2, name='Alexander', email='alexander@the.great', user_age=42)
    result = sum_users_squared_ages(user1, user2)
    return {'msg': f"Summing squared ages = {result}"}
