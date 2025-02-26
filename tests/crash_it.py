import requests

from crashless.handler import print_with_color, BColors


if __name__ == '__main__':
    res = requests.get('http://localhost:9000/crash')
    if res.status_code != 200:
        print_with_color(
            f"Endpoint successfully crashed with code: {res.status_code} and error: {res.json().get('error')}",
            BColors.FAIL
        )
