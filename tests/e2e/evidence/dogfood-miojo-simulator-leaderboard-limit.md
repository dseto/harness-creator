# Evidência — dogfood `dogfood-miojo-leaderboard-limit` (cobaia nova: miojo-simulator-3.0, Python/FastAPI)

## Regressão (testes pré-existentes)

Execução ANTES da correção (deve estar vermelha no teste novo):

```
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia
configfile: pyproject.toml
plugins: anyio-4.13.0, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests/test_basic.py::test_create_run_and_finish PASSED                   [ 25%]
tests/test_basic.py::test_validation_error_returns_friendly_message PASSED [ 50%]
tests/test_leaderboard_limit.py::test_negative_limit_is_rejected FAILED  [ 75%]
tests/test_leaderboard_limit.py::test_oversized_limit_is_rejected FAILED [100%]

================================== FAILURES ===================================
_______________________ test_negative_limit_is_rejected _______________________

    def test_negative_limit_is_rejected():
        client = TestClient(app)
        res = client.get("/leaderboard", params={"limit": -1})
>       assert res.status_code == 422
E       assert 200 == 422
E        +  where 200 = <Response [200 OK]>.status_code

tests\test_leaderboard_limit.py:14: AssertionError
---------------------------- Captured stderr call -----------------------------
2026-07-16 14:29:32,650 DEBUG asyncio: Using proactor: IocpProactor

2026-07-16 14:29:32,654 INFO httpx: HTTP Request: GET http://testserver/leaderboard?limit=-1 "HTTP/1.1 200 OK"

------------------------------ Captured log call ------------------------------
DEBUG    asyncio:proactor_events.py:633 Using proactor: IocpProactor
INFO     httpx:_client.py:1025 HTTP Request: GET http://testserver/leaderboard?limit=-1 "HTTP/1.1 200 OK"
______________________ test_oversized_limit_is_rejected _______________________

    def test_oversized_limit_is_rejected():
        client = TestClient(app)
        res = client.get("/leaderboard", params={"limit": 999999})
>       assert res.status_code == 422
E       assert 200 == 422
E        +  where 200 = <Response [200 OK]>.status_code

tests\test_leaderboard_limit.py:20: AssertionError
---------------------------- Captured stderr call -----------------------------
2026-07-16 14:29:32,859 DEBUG asyncio: Using proactor: IocpProactor

2026-07-16 14:29:32,862 INFO httpx: HTTP Request: GET http://testserver/leaderboard?limit=999999 "HTTP/1.1 200 OK"

------------------------------ Captured log call ------------------------------
DEBUG    asyncio:proactor_events.py:633 Using proactor: IocpProactor
INFO     httpx:_client.py:1025 HTTP Request: GET http://testserver/leaderboard?limit=999999 "HTTP/1.1 200 OK"
============================== warnings summary ===============================
..\..\..\..\..\..\Roaming\Python\Python314\site-packages\fastapi\testclient.py:1
  C:\Users\danie\AppData\Roaming\Python\Python314\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

backend\schemas.py:51
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\schemas.py:51: PydanticDeprecatedSince20: Pydantic V1 style `@validator` validators are deprecated. You should migrate to Pydantic V2 style `@field_validator` validators, see the migration guide for more details. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    @validator("chefName")

backend\schemas.py:61
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\schemas.py:61: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    class RunDetail(BaseModel):

backend\main.py:65
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\main.py:65: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

..\..\..\..\..\..\Roaming\Python\Python314\site-packages\fastapi\applications.py:4675
  C:\Users\danie\AppData\Roaming\Python\Python314\site-packages\fastapi\applications.py:4675: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)  # ty: ignore[deprecated]

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\db.py:102: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    now = datetime.utcnow().isoformat()

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\simulation.py:167: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    start_time = datetime.utcnow()

tests/test_basic.py: 33 warnings
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\db.py:142: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    ts = datetime.utcnow().isoformat()

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
tests/test_basic.py::test_validation_error_returns_friendly_message
tests/test_basic.py::test_validation_error_returns_friendly_message
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\simulation.py:199: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    if (datetime.utcnow() - start_time).total_seconds() > timeout_s:

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\db.py:179: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    values.append(datetime.utcnow().isoformat())

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_leaderboard_limit.py::test_negative_limit_is_rejected - ass...
FAILED tests/test_leaderboard_limit.py::test_oversized_limit_is_rejected - as...
================== 2 failed, 2 passed, 52 warnings in 4.50s ===================
```

Resultado agregado depois da correção — zero regressão:

```
======================= 4 passed, 52 warnings in 4.23s ========================
```


## Nova funcionalidade

Execução DEPOIS da correção (deve estar verde, incluindo test_negative_limit_is_rejected e test_oversized_limit_is_rejected):

```
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.1.1, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia
configfile: pyproject.toml
plugins: anyio-4.13.0, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests/test_basic.py::test_create_run_and_finish PASSED                   [ 25%]
tests/test_basic.py::test_validation_error_returns_friendly_message PASSED [ 50%]
tests/test_leaderboard_limit.py::test_negative_limit_is_rejected PASSED  [ 75%]
tests/test_leaderboard_limit.py::test_oversized_limit_is_rejected PASSED [100%]

============================== warnings summary ===============================
..\..\..\..\..\..\Roaming\Python\Python314\site-packages\fastapi\testclient.py:1
  C:\Users\danie\AppData\Roaming\Python\Python314\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

backend\schemas.py:51
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\schemas.py:51: PydanticDeprecatedSince20: Pydantic V1 style `@validator` validators are deprecated. You should migrate to Pydantic V2 style `@field_validator` validators, see the migration guide for more details. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    @validator("chefName")

backend\schemas.py:61
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\schemas.py:61: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    class RunDetail(BaseModel):

backend\main.py:65
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\main.py:65: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

..\..\..\..\..\..\Roaming\Python\Python314\site-packages\fastapi\applications.py:4675
  C:\Users\danie\AppData\Roaming\Python\Python314\site-packages\fastapi\applications.py:4675: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)  # ty: ignore[deprecated]

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\db.py:102: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    now = datetime.utcnow().isoformat()

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\simulation.py:167: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    start_time = datetime.utcnow()

tests/test_basic.py: 33 warnings
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\db.py:142: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    ts = datetime.utcnow().isoformat()

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
tests/test_basic.py::test_validation_error_returns_friendly_message
tests/test_basic.py::test_validation_error_returns_friendly_message
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\simulation.py:199: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    if (datetime.utcnow() - start_time).total_seconds() > timeout_s:

tests/test_basic.py::test_create_run_and_finish
tests/test_basic.py::test_validation_error_returns_friendly_message
  C:\Users\danie\AppData\Local\Temp\pytest-of-danie\pytest-240\test_contract_dogfood_miojo_le0\cobaia\backend\db.py:179: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    values.append(datetime.utcnow().isoformat())

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 4 passed, 52 warnings in 4.23s ========================
```


## Diff aplicado

```diff
--- a/backend/main.py
+++ b/backend/main.py
@@ -30,7 +30,7 @@
 from datetime import datetime
 from typing import AsyncGenerator, Dict, Optional, List
 
-from fastapi import FastAPI, HTTPException, Path
+from fastapi import FastAPI, HTTPException, Path, Query
 from fastapi.responses import StreamingResponse, JSONResponse
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.exceptions import RequestValidationError
@@ -256,7 +256,7 @@
     response_model=LeaderboardResponse,
     summary="Get leaderboard",
 )
-async def get_leaderboard(limit: int = 10) -> LeaderboardResponse:
+async def get_leaderboard(limit: int = Query(10, ge=1, le=100)) -> LeaderboardResponse:
     """Compute the top chefs sorted by their best score.
 
     The leaderboard groups runs by chefName, selects the maximum score for
```


## Execução do agente

- `is_error`: False
- `permission_denials`: []
- `num_turns`: 9

Últimos ~500 caracteres da resposta:

```
4 passed, 0 fail. T-01 done.
```


