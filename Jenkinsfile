// Jenkins 容器已挂好 /var/run/docker.sock 与 /usr/bin/docker（1Panel 预置），
// 且以 root 运行，所以这里可以直接调 docker / docker compose。
pipeline {
  agent any

  environment {
    // Jenkins 在容器里，但 docker 命令由【宿主机的 daemon】执行：
    // -v 的路径是宿主机视角。WORKSPACE 是容器视角（/var/jenkins_home/...），
    // 直接拿来挂会指向宿主机上不存在的路径，docker 则静默建个空目录。
    // 这里翻译成宿主机上的真实路径。
    HOST_WS   = "${env.WORKSPACE.replace('/var/jenkins_home', '/opt/1panel/apps/jenkins/jenkins/data')}"
    SITE_ROOT = '/opt/1panel/www/sites/ffp.hikoutei.cn/index'
  }

  options {
    timeout(time: 30, unit: 'MINUTES')
    disableConcurrentBuilds()          // 单核机器，别让两次构建互相抢
  }

  stages {
    stage('backup') {
      // Jenkins 容器看不到宿主机的 /opt/ffp-rag，借一个临时容器去打包。
      // 放在部署之前，不依赖人记得手动备份。
      steps {
        sh '''
          docker run --rm \
            -v /opt/ffp-rag/data:/data:ro \
            -v /opt/ffp-rag/chroma_db:/chroma:ro \
            -v /opt/ffp-rag/backups:/backup \
            alpine sh -c "tar czf /backup/$(date +%F-%H%M%S).tar.gz -C / data chroma && \
                          ls -1t /backup/*.tar.gz | tail -n +15 | xargs -r rm"
        '''
      }
    }

    stage('deploy') {
      // compose 的三类路径归属不同：build 上下文和 env_file 由【CLI】读取，
      // volumes 由【daemon】解析（宿主机视角）。Jenkins 容器里这两者对不上——
      // 它看不见 /opt/ffp-rag，`docker compose` 也没有（1Panel 没挂 cli-plugins）。
      // 所以借一个 docker:cli 容器：把工作区和 /opt/ffp-rag 都按宿主机原路径挂进去，
      // CLI 与 daemon 的路径语义就一致了。docker-compose.yml 因此不必为 CI 让步。
      // 详见 docs/adr/0006-jenkins-docker-outside-of-docker.md。
      steps {
        sh '''
          docker run --rm \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v /opt/ffp-rag:/opt/ffp-rag \
            -v "$HOST_WS/backend":/work -w /work \
            docker:cli docker compose up -d --build
        '''
      }
    }

    stage('console') {
      // 管理后台 SPA。在 node 容器里构建，产物直接落到 OpenResty 的站点根目录。
      // 两个卷都用宿主机绝对路径（见 HOST_WS 的说明）。
      // npm 缓存持久化，避免每次 ci 都重新下载——这台机器只有 1 核。
      // 缓存目录不必先 mkdir：-v 的宿主机侧不存在时，daemon 会自动建。
      // （在 Jenkins 容器里 mkdir 反而是错的，那建出来的是容器内的空目录。）
      steps {
        sh '''
          docker run --rm \
            -v "$HOST_WS/frontend":/src -w /src \
            -v /opt/ffp-rag/npm-cache:/root/.npm \
            -v "$SITE_ROOT":/out \
            --memory 900m \
            node:20-alpine sh -c "npm ci --prefer-offline --no-audit --fund=false && npm run build && rm -rf /out/console && cp -r dist /out/console"
          docker exec 1Panel-openresty-Cdj5 nginx -t && docker exec 1Panel-openresty-Cdj5 nginx -s reload
        '''
      }
    }

    stage('verify') {
      steps {
        sh '''
          ok=0
          for i in $(seq 1 20); do
            if docker exec ffp-rag python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"; then
              ok=1; break
            fi
            sleep 3
          done
          if [ "$ok" != "1" ]; then
            echo "服务未在 60s 内就绪"; docker logs --tail 50 ffp-rag; exit 1
          fi
          echo "--- 公网入口复验 ---"
          curl -sf -m 15 -o /dev/null -w "  /health   %{http_code}\\n" https://ffp.hikoutei.cn/health
          curl -sf -m 15 -o /dev/null -w "  /console/ %{http_code}\\n" https://ffp.hikoutei.cn/console/
        '''
      }
    }

    stage('prune') {
      // 盘只剩 9G，镜像已占 4.7G
      steps {
        sh 'docker image prune -f'
      }
    }
  }

  post {
    failure {
      sh 'docker logs --tail 100 ffp-rag || true'
    }
  }
}

// 绝不要在流水线里跑 scripts.ingest：
// store.ingest() 会从 corpus/*.md 全量重建集合，抹掉所有 URL 摄入的知识。
// 知识的增删改走管理后台，不走部署。
