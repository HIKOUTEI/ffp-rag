// Jenkins 容器已挂好 /var/run/docker.sock 与 /usr/bin/docker（1Panel 预置），
// 且以 root 运行，所以这里可以直接调 docker / docker compose。
pipeline {
  agent any

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
      steps {
        dir('backend') {
          sh 'docker compose up -d --build'
        }
      }
    }

    stage('verify') {
      steps {
        sh '''
          for i in $(seq 1 20); do
            docker exec ffp-rag python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')" \
              && exit 0
            sleep 3
          done
          echo "服务未在 60s 内就绪"; docker logs --tail 50 ffp-rag; exit 1
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
