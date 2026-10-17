FROM nodebase AS build
WORKDIR /app
ENV HOME=/private-cache/home NPM_CONFIG_CACHE=/private-cache/npm NPM_CONFIG_USERCONFIG=/private-cache/user.npmrc NPM_CONFIG_GLOBALCONFIG=/private-cache/global.npmrc
COPY package.json package-lock.json index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN --network=none --mount=type=bind,from=npmseed,source=/,target=/seed,ro --mount=type=tmpfs,target=/private-cache,size=268435456 --mount=type=tmpfs,target=/tmp,size=67108864 \
    node -e 'const fs=require("fs"); const cp=require("child_process"); if(process.version!=="v22.23.2")process.exit(21); try{const fd=fs.openSync("/seed/manifest.json","r+");fs.closeSync(fd);process.exit(22);}catch(e){if(e.code!=="EROFS")throw e;} for(const [p,n]of [["/private-cache",268435456],["/tmp",67108864]]){const s=fs.statfsSync(p);if(s.type!==0x1021994||s.bsize*s.blocks!==n)process.exit(27);} if(fs.readFileSync("/proc/net/route","utf8").trim().split("\n").length!==1)process.exit(23); for(const p of ["/var/run/docker.sock","/run/docker.sock","/probe/context","/app/.git"])if(fs.existsSync(p))process.exit(24); fs.mkdirSync("/private-cache/home",{recursive:true}); console.log("CLOUDHELM_FRONTEND_TOOLCHAIN="+JSON.stringify({node:process.version,npm:cp.execFileSync("npm",["--version"],{encoding:"utf8"}).trim(),seed_readonly:true,no_ipv4_routes:true,control_paths_absent:true}));' \
    && for tarball in /seed/*.tgz; do npm cache add --offline --ignore-scripts --no-audit --no-fund "$tarball" || exit; done \
    && npm ci --offline --ignore-scripts --include=dev --include=optional --no-audit --no-fund \
    && npm run build \
    && node -e 'const fs=require("fs"),c=require("crypto"); const files=[]; function walk(p){for(const d of fs.readdirSync(p,{withFileTypes:true}).sort((a,b)=>a.name.localeCompare(b.name))){const n=p+"/"+d.name; if(d.isDirectory())walk(n); else if(d.isFile()){const b=fs.readFileSync(n);files.push({path:n.slice(5),bytes:b.length,sha256:"sha256:"+c.createHash("sha256").update(b).digest("hex")});}else process.exit(25);}} walk("dist");if(!files.some(f=>f.path==="index.html")||files.length<3)process.exit(26);console.log("CLOUDHELM_FRONTEND_DIST="+JSON.stringify(files));'

FROM nginxbase AS runtime
RUN --network=none ["rm", "-f", "/usr/share/nginx/html/index.html", "/usr/share/nginx/html/50x.html"]
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://127.0.0.1/ || exit 1
