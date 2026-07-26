# 部署说明

## 本地 WSL

前置条件：

- Docker Engine 与 Docker Compose
- WSL 宿主机 PostgreSQL 16
- 正式数据库 `exchange_aggregator`
- 测试数据库 `exchange_aggregator_test`
- PostgreSQL 允许项目 Docker 子网 `172.30.42.0/24` 以
  `scram-sha-256` 连接上述两个数据库

启动：

```bash
cd /home/yyf/codex/AggregatedAccounts
make dev-up
```

开发覆盖文件把 gateway 映射为：

```yaml
ports:
  - "0.0.0.0:8000:80"
```

## 远程服务器

1. 将项目放入远程 Linux 文件系统。
2. 创建 PostgreSQL 正式库与测试库，并仅放行项目 Docker 子网。
3. 复制 `.env.example` 为 `.env`，填写数据库密码与访问密码。
4. 运行 `make init` 自动生成缺失的主加密密钥和会话密钥。
5. 将 `COOKIE_SECURE=true` 与 `APP_ENV=production` 写入 `.env`。
6. 启动生产覆盖：

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  run --rm backend alembic upgrade head

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  up -d --build
```

生产覆盖仅绑定：

```yaml
ports:
  - "127.0.0.1:8000:80"
```

项目不会占用宿主机 80/443，不管理 Let's Encrypt，也不会覆盖现有 Nginx。

## 宿主机 Nginx 示例

以下配置仅供手工合并，不应自动覆盖服务器现有配置：

```nginx
server {
    listen 80;
    server_name portfolio.example.com;

    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name portfolio.example.com;

    ssl_certificate /etc/letsencrypt/live/portfolio.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portfolio.example.com/privkey.pem;

    client_max_body_size 2m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

## 上线检查

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  ps

curl -f http://127.0.0.1:8000/api/health
make security-check
```

确认：

- gateway 仅绑定 `127.0.0.1:8000`
- backend 与 frontend 没有宿主机端口
- 没有 PostgreSQL 容器
- `.env` 权限是 `600` 且未被 Git 跟踪
- Cookie 带有 `Secure`、`HttpOnly` 和 `SameSite=Lax`
- 宿主机防火墙没有对公网开放 8000 或 5432

## 备份与密钥

备份 PostgreSQL 前应先确认备份文件的访问控制。主加密密钥必须与数据库备份分开
保管；丢失主密钥后，已保存的交易所凭证无法恢复。轮换主密钥需要先实现专用的
离线重加密流程，不能直接替换 `.env` 中的值。

