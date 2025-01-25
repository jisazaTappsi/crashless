from typing import Dict

from fastapi import FastAPI
from crashless import fastapi_handler


class Employee:
    def __init__(self, name, age):
        self.name = name
        self.age = age


def find_employee_node(employee, organization_node):
    if employee == organization_node.employee:
        return organization_node

    for subordinate_node in organization_node.subordinate_nodes:
        candidate_node = find_employee_node(employee, subordinate_node)
        if candidate_node:
            return candidate_node

    return None


def get_level(employee, organization):
    employee_node = find_employee_node(employee, organization)
    return employee_node.level if employee_node else None


def get_peers_with_level(level, organization_node):
    if level == organization_node.level:
        return {organization_node.employee}  # won't go further down.

    employee_peers = set()
    for subordinate_node in organization_node.subordinate_nodes:
        employee_peers |= get_peers_with_level(level, subordinate_node)
    return employee_peers


def get_peers(employee, organization):
    level = get_level(employee, organization)
    peers = get_peers_with_level(level, organization)
    return {p for p in peers if p != employee}  # exclude the employee.


app = FastAPI()
app.add_exception_handler(Exception, fastapi_handler.handle_exception)


@app.get("/crash")  # This endpoint has a fatal bug :(
def crash(organization: Dict = None):
    employee = Employee(name='Pedro', age=42)
    get_peers(employee=employee, organization=organization)
    return {'msg': 'success'}
