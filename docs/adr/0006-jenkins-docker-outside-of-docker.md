# Jenkins 借宿主机 docker.sock 部署（DooD），而非 SSH 触发

部署目标是一台 1 核 / 2G 的美西云服务器（1Panel 托管，已跑着 OpenResty、Jenkins、
另一个项目）。可选方案有二：

- **SSH 触发**：本地或 GitHub Actions 通过 ssh 登录服务器跑部署脚本，用 uv + systemd
  直接把 uvicorn 跑在宿主机上。
- **Jenkins + docker.sock**（选中）：Jenkins 容器里执行 `docker`，由宿主机 daemon 干活。

## 决定一：用 Jenkins + docker.sock

选 Jenkins + docker.sock。理由：

- 1Panel 预置的 Jenkins 容器**已经**挂好了 `/var/run/docker.sock` 和 `/usr/bin/docker`，
  并以 root 运行——能力是现成的，不需要改容器。
- 部署流程（备份 → 部署 → 构建管理后台 → 复验）落在版本控制的 `Jenkinsfile` 里，
  而不是散在某人机器上的 shell 脚本。
- 容器化让 Python 版本与宿主机脱钩：宿主机只有 3.14，chromadb 的原生依赖没有 cp314
  的 wheel，装不上；镜像里钉 `python:3.12-slim` 即可。

代价：Jenkins 容器等价于宿主机 root（能操作 docker.sock 就能挂载任意宿主机路径）。
这台机器只有我一个使用者，接受。

## DooD 的路径坑（踩了两轮）

DooD 下 compose 的路径有**两种归属**，这是所有麻烦的根源：

| 配置 | 谁来解析 | 视角 |
|---|---|---|
| `build:` 上下文 | CLI | CLI 所在容器 |
| `env_file:` | CLI | CLI 所在容器 |
| `volumes:` 宿主机侧 | daemon | **宿主机** |

**第一轮**：直接把 `$WORKSPACE` 拿去挂。它是 Jenkins 容器视角的
`/var/jenkins_home/...`，daemon 在宿主机上找不到，于是**不报错、静默建一个空目录**——
服务能起来、检索却是空的。这是最阴险的一个，因为它不会失败。

**第二轮**：在 Jenkins 容器里跑 `docker compose up -d --build`，连着失败两次：

1. `unknown shorthand flag: 'd' in -d`——1Panel 只挂了 `docker` 主二进制，没挂
   `/usr/libexec/docker/cli-plugins/`，而 compose 是 CLI 插件，容器里压根没有
   `docker compose`，`compose up` 被当成了主命令的参数。
2. 补上插件后：`env file /opt/ffp-rag/.env not found`——`.env` 在宿主机上好好的，
   但 Jenkins 容器看不见 `/opt/ffp-rag`。

## 决定二：compose CLI 跑在「路径与宿主机一致」的容器里

不在 Jenkins 容器里跑 compose，而是借一个 `docker:cli` 容器，把工作区和
`/opt/ffp-rag` 都**按宿主机原路径**挂进去，在里面执行 `docker compose up -d --build`。
这样 CLI 视角与 daemon 视角重合，上表三行全部成立。

否决的备选：

- **给 1Panel 的 Jenkins 容器加挂 `/opt/ffp-rag`**（改
  `/opt/1panel/apps/jenkins/jenkins/docker-compose.yml`）。一行就能修，但要重启
  Jenkins（另一个项目的 CI 也在上面），且 1Panel 应用升级时可能把该文件重新生成。
- **把密钥搬进 Jenkins Credentials，用 `environment:` 注入**。这是标准 CI 做法，
  但会让密钥的真相源一分为二（`/opt/ffp-rag/.env` 与 Jenkins 各一份），
  单人单机不值这个复杂度。

代价是多一层嵌套容器需要理解——本 ADR 就是为了让下次不用重新调查一遍。
`HOST_WS` 仍然保留（`console` 阶段的 `-v` 依然要宿主机路径）。

## 相关约束

- **`--workers 1` 是正确性要求，不是调优**：额度计数与登录态存在进程内可见的 sqlite，
  多 worker 会各算各的（见 ADR-0002）。
- **流水线绝不能跑 `scripts.ingest`**：它会从 `corpus/*.md` 全量重建集合，
  抹掉所有 URL 摄入的知识（见 ADR-0004）。
- 可变状态（三个 sqlite + `ingested.jsonl` + 向量库）挂在 `/opt/ffp-rag/` 下，
  部署前由 `backup` 阶段打包，保留最近 15 份。
