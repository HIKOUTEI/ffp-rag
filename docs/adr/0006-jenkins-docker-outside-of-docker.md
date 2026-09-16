# Jenkins 借宿主机 docker.sock 部署（DooD），而非 SSH 触发

部署目标是一台 1 核 / 2G 的美西云服务器（1Panel 托管，已跑着 OpenResty、Jenkins、
另一个项目）。可选方案有二：

- **SSH 触发**：本地或 GitHub Actions 通过 ssh 登录服务器跑部署脚本，用 uv + systemd
  直接把 uvicorn 跑在宿主机上。
- **Jenkins + docker.sock**（选中）：Jenkins 容器里执行 `docker`，由宿主机 daemon 干活。

## 决定

选 Jenkins + docker.sock。理由：

- 1Panel 预置的 Jenkins 容器**已经**挂好了 `/var/run/docker.sock` 和 `/usr/bin/docker`，
  并以 root 运行——能力是现成的，不需要改容器。
- 部署流程（备份 → 部署 → 构建管理后台 → 复验）落在版本控制的 `Jenkinsfile` 里，
  而不是散在某人机器上的 shell 脚本。
- 容器化让 Python 版本与宿主机脱钩：宿主机只有 3.14，chromadb 的原生依赖没有 cp314
  的 wheel，装不上；镜像里钉 `python:3.12-slim` 即可。

代价：Jenkins 容器等价于宿主机 root（能操作 docker.sock 就能挂载任意宿主机路径）。
这台机器只有我一个使用者，接受。

## DooD 的两个坑（都踩过）

**一、路径归属不同**。`docker build` 的构建上下文由 **CLI** 读取（Jenkins 容器视角，
`/var/jenkins_home/...`，正确）；但 `-v` 和 compose `volumes` 的宿主机侧路径由
**daemon** 解析（宿主机视角）。直接把 `$WORKSPACE` 拿去挂，会指向宿主机上不存在的
`/var/jenkins_home/...`，docker 不报错、静默建一个空目录——服务能起来、检索却是空的。
故 `Jenkinsfile` 里用 `HOST_WS` 把容器路径翻译回宿主机路径，compose 里一律写绝对路径。

**二、`docker compose` 不存在**。1Panel 只挂了 `docker` 主二进制，没挂
`/usr/libexec/docker/cli-plugins/`，而 compose 是 CLI 插件。首次构建因此失败
（`unknown shorthand flag: 'd' in -d`——docker 把 `compose up` 当成了主命令的参数）。
解法是把宿主机的 `docker-compose` 插件复制到 `/var/jenkins_home/.docker/cli-plugins/`
（`jenkins_home` 是卷，1Panel 升级重建容器也不会丢），并在 `Jenkinsfile` 里设
`DOCKER_CONFIG=/var/jenkins_home/.docker`。备选方案是改 1Panel 的 Jenkins 容器加挂载，
但那会被 1Panel 的应用管理覆盖，不如放在卷里稳。

## 相关约束

- **`--workers 1` 是正确性要求，不是调优**：额度计数与登录态存在进程内可见的 sqlite，
  多 worker 会各算各的（见 ADR-0002）。
- **流水线绝不能跑 `scripts.ingest`**：它会从 `corpus/*.md` 全量重建集合，
  抹掉所有 URL 摄入的知识（见 ADR-0004）。
- 可变状态（三个 sqlite + `ingested.jsonl` + 向量库）挂在 `/opt/ffp-rag/` 下，
  部署前由 `backup` 阶段打包，保留最近 15 份。
