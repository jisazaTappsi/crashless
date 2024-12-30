import uvicorn


if __name__ == '__main__':
    """This script is used only for development, runs FastAPI with reload, from uvicorn server"""
    uvicorn.run('main:app', host='0.0.0.0', port=9000, proxy_headers=True, reload=True)
