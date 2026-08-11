import re
from pathlib import Path


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")

session_import = (
    "from auth_session import "
    "create_session_cookie, router as auth_session_router\n"
)

if session_import not in main:
    marker = "from rag.rag_api import router as rag_router\n"
    require(marker in main, "main.py import 위치를 찾지 못했습니다.")
    main = main.replace(marker, marker + session_import, 1)

if "app.include_router(auth_session_router)" not in main:
    marker = "app.include_router(rag_router)\n"
    require(marker in main, "세션 라우터 등록 위치를 찾지 못했습니다.")
    main = main.replace(
        marker,
        marker + "app.include_router(auth_session_router)\n",
        1,
    )

cors_pattern = re.compile(
    r"allow_origins=\[[\s\S]*?\],\n"
    r"\s*allow_credentials=True,"
)

main, count = cors_pattern.subn(
    '''allow_origins=[
        "http://localhost:5173",
        FRONTEND_URL.rstrip("/"),
    ],
    allow_credentials=True,''',
    main,
    count=1,
)
require(count == 1, "CORS 설정을 찾지 못했습니다.")

main = main.replace("secure=False,", "secure=True,")

redirect_pattern = re.compile(
    r"\n    encoded_user = quote\([\s\S]*?"
    r"\n    response = RedirectResponse\(\n"
    r"        url=frontend_redirect_url,\n"
    r"        status_code=302,\n"
    r"    \)\n"
)

redirect_replacement = '''
    frontend_redirect_url = (
        f"{FRONTEND_URL.rstrip('/')}/login?auth=success"
    )

    response = RedirectResponse(
        url=frontend_redirect_url,
        status_code=302,
    )
    create_session_cookie(response, db_user["id"])
'''

main, count = redirect_pattern.subn(
    redirect_replacement,
    main,
)
require(
    count == 2,
    f"Kakao/Naver 콜백 발견 개수가 2가 아닙니다: {count}",
)

main_path.write_text(main, encoding="utf-8")


google_path = Path("google_auth.py")
google = google_path.read_text(encoding="utf-8")

if "from fastapi.responses import JSONResponse" not in google:
    google = google.replace(
        "from fastapi import APIRouter, HTTPException\n",
        "from fastapi import APIRouter, HTTPException\n"
        "from fastapi.responses import JSONResponse\n",
        1,
    )

if "from auth_session import create_session_cookie" not in google:
    google = google.replace(
        "from pydantic import BaseModel\n",
        "from pydantic import BaseModel\n\n"
        "from auth_session import create_session_cookie\n",
        1,
    )

if "인증되지 않은 Google 이메일입니다." not in google:
    marker = '    name = payload.get("name")\n'
    require(marker in google, "Google 이메일 검증 위치를 찾지 못했습니다.")
    google = google.replace(
        marker,
        '''    if payload.get("email_verified") is not True:
        raise HTTPException(
            status_code=401,
            detail="인증되지 않은 Google 이메일입니다.",
        )

''' + marker,
        1,
    )

return_pattern = re.compile(
    r"\n    return \{\n"
    r'        "id": row\[0\],[\s\S]*?'
    r"\n    \}\s*$"
)

return_replacement = '''
    user = {
        "id": row[0],
        "provider": row[1],
        "provider_user_id": row[2],
        "name": row[3],
        "email": row[4],
        "profile_image_url": row[5],
    }

    response = JSONResponse(content=user)
    create_session_cookie(response, row[0])
    return response
'''

google, count = return_pattern.subn(
    return_replacement,
    google,
)
require(count == 1, "Google 응답 부분을 찾지 못했습니다.")

google_path.write_text(google, encoding="utf-8")
print("인증 코드 수정 완료")
