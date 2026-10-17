FROM pythonbase AS dependencies
WORKDIR /app
ENV UV_CACHE_DIR=/private-cache UV_PYTHON_DOWNLOADS=never UV_KEYRING_PROVIDER=disabled PYTHONDONTWRITEBYTECODE=1
RUN --network=none --mount=type=bind,from=pythonseed,source=/uv,target=/usr/local/bin/uv,readonly --mount=type=bind,from=pythonseed,source=/wheels,target=/wheelhouse,readonly --mount=type=bind,source=.,target=/source,readonly --mount=type=tmpfs,target=/private-cache,size=268435456 --mount=type=tmpfs,target=/tmp,size=67108864 \
    cp /source/derived-pyproject.toml /app/pyproject.toml && cp /source/.python-version /app/.python-version && \
    uv --version && test "$(uv --version | cut -d ' ' -f 1-2)" = "uv 0.11.29" && \
    uv lock --offline --no-build --no-index --find-links=/wheelhouse --python=/usr/local/bin/python --no-python-downloads && \
    python -I -c 'import json,tomllib; expected=json.load(open("/source/expected-distributions.json")); p=tomllib.load(open("uv.lock","rb"))["package"]; actual={x["name"]:x["version"] for x in p if x["source"]!={"virtual":"."}}; assert actual == expected; assert all(not x.get("sdist") for x in p)' && \
    uv sync --locked --no-dev --offline --no-build --no-install-project --no-index --find-links=/wheelhouse --link-mode=copy --python=/usr/local/bin/python --no-python-downloads && \
    .venv/bin/python -I -c 'import alembic,fastapi,psycopg,pydantic,sqlalchemy,uvicorn; import importlib.metadata as m,json,sys,os; assert sys.version_info[:3] == (3,12,13); assert psycopg.pq.__impl__ == "binary"; d={x.metadata["Name"].lower().replace("_","-"):x.version for x in m.distributions()}; c=os.statvfs("/private-cache"); t=os.statvfs("/tmp"); r={"python":"3.12.13","distributions":d,"psycopg_impl":psycopg.pq.__impl__,"cache_bytes":c.f_frsize*c.f_blocks,"temp_bytes":t.f_frsize*t.f_blocks,"wheelhouse_readonly":bool(os.statvfs("/wheelhouse").f_flag & os.ST_RDONLY),"no_ipv4_routes":len(open("/proc/net/route").read().splitlines())==1,"control_paths_absent":all(not os.path.exists(p) for p in ("/var/run/docker.sock","/run/docker.sock","/probe/context","/probe/python-seed","/app/.git"))}; open("/dependency-result.json","w",encoding="utf-8").write(json.dumps(r,sort_keys=True)+"\n"); print("CLOUDHELM_PYTHON_DEPENDENCIES=verified",flush=True)'

FROM scratch AS verification
COPY --from=dependencies /dependency-result.json /dependency-result.json
COPY --from=dependencies /app/pyproject.toml /derived-pyproject.toml
COPY --from=dependencies /app/uv.lock /derived-uv.lock

FROM pythonbase AS runtime
WORKDIR /app
COPY --from=dependencies /app/.venv ./.venv
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ARG CLOUDHELM_BUILD_INPUT_KEY
RUN --network=none --mount=type=bind,source=.,target=/source,readonly \
    cp /source/pyproject.toml /source/uv.lock /source/.python-version /source/alembic.ini /app/ && cp -R /source/app /source/migrations /app/ && \
    .venv/bin/python -I -c 'import sys; sys.path.insert(0,"/app"); import app.main,os,json; from alembic.config import Config; from alembic.script import ScriptDirectory; head=ScriptDirectory.from_config(Config("/app/alembic.ini")).get_current_head(); paths=set(app.main.app.openapi()["paths"]); assert {"/health","/ready","/api/notes"} <= paths; r={"python":".".join(map(str,sys.version_info[:3])),"build_input_key":os.environ["CLOUDHELM_BUILD_INPUT_KEY"],"migration_head":head,"backend_imported":True,"database_unconfigured":app.main.app.state.engine is None,"no_ipv4_routes":len(open("/proc/net/route").read().splitlines())==1,"control_paths_absent":all(not os.path.exists(p) for p in ("/var/run/docker.sock","/run/docker.sock","/probe/context","/probe/python-seed","/app/.git","/wheelhouse"))}; open("/backend-result.json","w",encoding="utf-8").write(json.dumps(r,sort_keys=True)+"\n"); print("CLOUDHELM_BACKEND_RUNTIME="+json.dumps(r,sort_keys=True),flush=True)'
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
